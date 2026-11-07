#!/usr/bin/env python3
"""User-level desktop launchers and on-demand launch for AaaS applications."""

import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts/run_aaas.py"
WORKSPACE_TMP = Path("/run/media/mrkus/Aaas/aaas-workspace/tmp")
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")
ANCHORS = ("com.android.settings", "com.android.contacts")


def applications_dir(env=None):
    env = os.environ if env is None else env
    data_home = Path(env.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    if not data_home.is_absolute():
        raise ValueError("XDG_DATA_HOME must be an absolute path")
    return data_home / "applications"


def desktop_escape(value):
    return (str(value).replace("\\", "\\\\").replace("\n", "\\n")
            .replace("\r", "\\r").replace("\t", "\\t"))


def desktop_exec_quote(value):
    """Quote one Exec token according to the Desktop Entry string rules."""
    value = str(value).replace("%", "%%")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') \
        .replace("`", "\\`").replace("$", "\\$") + '"'


def launcher_path(package, env=None):
    validate_package(package)
    return applications_dir(env) / f"aaas-{package}.desktop"


def catalog_paths(env=None):
    env = os.environ if env is None else env
    data_home = Path(env.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    if not data_home.is_absolute():
        raise ValueError("XDG_DATA_HOME must be an absolute path")
    root = data_home / "aaas"
    return root, root / "catalog.json", root / "launcher-manifest.json"


def catalog_launcher_path(package, env=None):
    validate_package(package)
    return applications_dir(env) / f"aaas-catalog-{package}.desktop"


def _decode_catalog_field(value, field):
    try:
        return base64.b64decode(value.encode("ascii"), validate=True).decode("utf-8")
    except (UnicodeError, ValueError) as error:
        raise ValueError(f"invalid PackageManager catalog {field}") from error


def parse_package_catalog(path, request_id, *, max_bytes=16 * 1024 * 1024):
    if not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise ValueError("invalid PackageManager catalog request identity")
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise ValueError("PackageManager catalog exceeds size limit")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise ValueError("PackageManager catalog is not UTF-8") from error
    if not lines:
        raise ValueError("PackageManager catalog is empty")
    header = lines[0].split("\t")
    if len(header) != 4 or header[:3] != ["AAAS-CATALOG", "1", request_id] \
            or header[3] not in ("0", "1"):
        raise ValueError("PackageManager catalog header does not match request")
    applications = []
    seen = set()
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != 7:
            raise ValueError("PackageManager catalog row has the wrong field count")
        package = _decode_catalog_field(fields[0], "package")
        validate_package(package)
        activity = _decode_catalog_field(fields[1], "activity")
        if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]*", activity):
            raise ValueError(f"invalid launcher activity for {package}")
        label = _decode_catalog_field(fields[2], "label")
        if not label or any((ord(char) < 32 and char != "\t") or ord(char) == 127
                            for char in label):
            raise ValueError(f"invalid application label for {package}")
        if not re.fullmatch(r"[0-9]+", fields[3]):
            raise ValueError(f"invalid version code for {package}")
        try:
            version_code = int(fields[3])
        except ValueError as error:
            raise ValueError(f"invalid version code for {package}") from error
        if version_code < 0 or fields[5] != "1":
            raise ValueError(f"disabled or invalid application record for {package}")
        version_name = _decode_catalog_field(fields[4], "version name")
        icon = b""
        if fields[6]:
            try:
                icon = base64.b64decode(fields[6].encode("ascii"), validate=True)
            except (UnicodeError, ValueError) as error:
                raise ValueError(f"invalid icon data for {package}") from error
            if len(icon) > 1024 * 1024 or len(icon) < 24 or icon[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError(f"invalid PNG icon for {package}")
            width, height = struct.unpack(">II", icon[16:24])
            if not (1 <= width <= 512 and 1 <= height <= 512):
                raise ValueError(f"out-of-bounds icon dimensions for {package}")
        if package in seen:
            continue
        seen.add(package)
        applications.append({
            "package": package, "activity": activity, "label": label,
            "version_code": version_code, "version_name": version_name,
            "enabled": True, "icon_png": icon,
        })
    applications.sort(key=lambda app: (app["label"].casefold(), app["package"]))
    return {"request_id": request_id, "truncated": header[3] == "1",
            "applications": applications}


def _atomic_write(path, payload, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                          dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_owned_manifest(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": 1, "entries": {}}
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"AaaS launcher ownership manifest is invalid: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != 1 \
            or not isinstance(value.get("entries"), dict):
        raise RuntimeError("AaaS launcher ownership manifest has an unsupported schema")
    for package, owned in value["entries"].items():
        validate_package(package)
        if not isinstance(owned, dict) or owned.get("desktop") != \
                f"aaas-catalog-{package}.desktop":
            raise RuntimeError("AaaS launcher ownership manifest contains an invalid path")
        icon_name = owned.get("icon")
        if icon_name is not None and icon_name != f"aaas-catalog-{package}.png":
            raise RuntimeError("AaaS launcher ownership manifest contains an invalid icon path")
    return value


def _catalog_entry_text(application, icon):
    package = validate_package(application["package"])
    name = application["label"]
    if not name or any((ord(char) < 32 and char != "\t") or ord(char) == 127
                       for char in name):
        raise ValueError("application name must be non-empty and single-line")
    script = str((ROOT / "scripts/aaas_desktop.py").resolve())
    icon_value = str(icon) if icon else "application-x-executable"
    fields = [
        "[Desktop Entry]", "Type=Application", f"Name={desktop_escape(name)}",
        f"Comment=Run {desktop_escape(name)} with AaaS", "Terminal=false",
        "Categories=Utility;", "StartupNotify=false",
        "X-AaaS-Package=" + package,
        "X-AaaS-VersionCode=" + str(application["version_code"]),
        "Exec=" + " ".join(desktop_exec_quote(token) for token in
                             (sys.executable, script, "launch", "--package", package)),
        "Icon=" + desktop_escape(icon_value),
    ]
    return "\n".join(fields) + "\n"


def sync_package_catalog(applications, *, env=None, truncated=False):
    env = os.environ if env is None else env
    data_dir, catalog_path, manifest_path = catalog_paths(env)
    app_dir = applications_dir(env)
    data_dir.mkdir(parents=True, exist_ok=True)
    app_dir.mkdir(parents=True, exist_ok=True)
    old = _read_owned_manifest(manifest_path)
    old_entries = old["entries"]
    current = {}
    collisions = []
    normalized = []
    for app in applications:
        package = validate_package(app.get("package"))
        if package in current:
            continue
        desktop_name = f"aaas-catalog-{package}.desktop"
        desktop = app_dir / desktop_name
        was_owned = package in old_entries
        if desktop.exists() and not was_owned and not desktop.is_symlink():
            collisions.append(package)
            continue
        if desktop.is_symlink():
            collisions.append(package)
            continue
        icon_data = app.get("icon_png", b"")
        icon_name = None
        icon_path = None
        if icon_data:
            icon_name = f"aaas-catalog-{package}.png"
            icon_path = data_dir / "icons" / icon_name
            was_icon_owned = was_owned and old_entries[package].get("icon") == icon_name
            if icon_path.exists() and not was_icon_owned and not icon_path.is_symlink():
                icon_name = None
                icon_path = None
        if icon_path is not None:
            _atomic_write(icon_path, icon_data)
        contents = _catalog_entry_text(app, icon_path)
        _atomic_write(desktop, contents.encode("utf-8"), 0o644)
        current[package] = {"desktop": desktop_name, "icon": icon_name}
        normalized.append({key: value for key, value in app.items() if key != "icon_png"}
                          | {"icon": icon_name,
                             "icon_fallback": icon_name is None})

    # A truncated PackageManager response cannot prove that omitted packages
    # were uninstalled, so preserve their managed entries until a complete scan.
    if truncated:
        for package, owned in old_entries.items():
            current.setdefault(package, owned)
    else:
        # Only paths named by the prior ownership manifest are eligible for deletion.
        for package, owned in old_entries.items():
            if package in current:
                continue
            desktop = app_dir / owned["desktop"]
            if desktop.parent == app_dir and desktop.is_file() and not desktop.is_symlink():
                desktop.unlink()
            if owned.get("icon"):
                icon = data_dir / "icons" / owned["icon"]
                if icon.parent == data_dir / "icons" and icon.is_file() and not icon.is_symlink():
                    icon.unlink()

    manifest = {"schema": 1, "entries": current}
    catalog = {"schema": 1, "updated_at": int(time.time()),
               "truncated": bool(truncated), "applications": normalized,
               "collisions": collisions}
    _atomic_write(manifest_path, (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode())
    _atomic_write(catalog_path, (json.dumps(catalog, sort_keys=True, indent=2) + "\n").encode())
    return {"catalog": str(catalog_path), "count": len(current),
            "collisions": collisions, "truncated": bool(truncated)}


def request_package_catalog(timeout=30):
    endpoint, result = _control_request({"op": "package_catalog"}, timeout=timeout)
    if not result.get("ok"):
        raise RuntimeError(f"Android PackageManager catalog query failed: {result}")
    request_id = result.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise RuntimeError("AaaS session returned an invalid catalog request identity")
    output = Path(result.get("catalog_path", ""))
    ipc = endpoint.parent
    expected = ipc / f"catalog-{request_id}.tsv"
    try:
        if output.resolve(strict=True) != expected.resolve(strict=False):
            raise RuntimeError("AaaS session returned an unexpected catalog path")
        parsed = parse_package_catalog(output, request_id)
    finally:
        try:
            if output.parent == ipc and output.name == expected.name and not output.is_symlink():
                output.unlink(missing_ok=True)
        except OSError:
            pass
    return parsed


def _active_session():
    try:
        endpoint, status = _control_request({"op": "list"}, timeout=2)
    except RuntimeError:
        return None, None
    return status, endpoint


def refresh_package_catalog(*, env=None):
    status, endpoint = _active_session()
    started_session = status is None or status.get("state") not in ("STARTING", "RUNNING")
    session_dir = None
    if started_session:
        launch_application("com.android.settings")
        status, endpoint = _active_session()
        if status is None:
            raise RuntimeError("AaaS did not publish a control endpoint after startup")
        session_dir = endpoint.parent.parent
    try:
        snapshot = request_package_catalog()
        synchronized = sync_package_catalog(
            snapshot["applications"], env=env, truncated=snapshot["truncated"])
        return {**synchronized, "request_id": snapshot["request_id"],
                "started_temporary_runtime": started_session}
    finally:
        if started_session:
            try:
                _control_request({"op": "stop"}, timeout=3)
            except RuntimeError:
                pass
            if session_dir is not None:
                deadline = time.monotonic() + 35
                status_file = session_dir / "status"
                while time.monotonic() < deadline:
                    try:
                        if status_file.read_text().strip() == "STOPPED":
                            break
                    except OSError:
                        break
                    time.sleep(.25)


def validate_package(package):
    if not isinstance(package, str) or not PACKAGE.fullmatch(package):
        raise ValueError("package must be a dotted Android application ID")
    return package


def render_launcher(package, name, icon=None):
    validate_package(package)
    if not name or any((ord(char) < 32 and char != "\t") or ord(char) == 127
                       for char in name):
        raise ValueError("application name must be non-empty and single-line")
    script = str((ROOT / "scripts/aaas_desktop.py").resolve())
    fields = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={desktop_escape(name)}",
        f"Comment=Run {desktop_escape(name)} with AaaS",
        "Terminal=false",
        "Categories=Utility;",
        "StartupNotify=false",
        "Exec=" + " ".join(desktop_exec_quote(token) for token in
                             (sys.executable, script, "launch", "--package", package)),
    ]
    if icon:
        icon_path = Path(icon)
        if not icon_path.is_absolute() or not icon_path.is_file():
            raise ValueError("icon must name an existing absolute file")
        fields.append(f"Icon={desktop_escape(icon_path)}")
    return "\n".join(fields) + "\n"


def install_launcher(package, name=None, icon=None, env=None):
    path = launcher_path(package, env)
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = render_launcher(package, name or package, icon)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(contents, encoding="utf-8")
    temporary.chmod(0o644)
    os.replace(temporary, path)
    return path


def _control_request(request, timeout=5):
    candidates = sorted(WORKSPACE_TMP.glob("m1b84_session_*/ipc/aaas-control.sock"),
                        key=lambda item: item.stat().st_mtime, reverse=True)
    last_error = None
    for path in candidates:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(timeout)
                connection.connect(str(path))
                connection.sendall(json.dumps(request, separators=(",", ":")).encode() + b"\n")
                response = bytearray()
                while b"\n" not in response and len(response) <= 4096:
                    data = connection.recv(min(1024, 4097 - len(response)))
                    if not data:
                        break
                    response.extend(data)
                if len(response) > 4096:
                    raise RuntimeError("AaaS session returned an oversized response")
                return path, json.loads(bytes(response).split(b"\n", 1)[0])
        except (OSError, ValueError, RuntimeError) as error:
            last_error = error
    if last_error:
        raise RuntimeError(f"no active AaaS control endpoint: {last_error}")
    raise RuntimeError("no active AaaS control endpoint")


def _choose_anchor(package):
    for candidate in ANCHORS:
        if candidate != package:
            return candidate
    raise RuntimeError("no distinct bootstrap application is available")


def _newest_session_after(started_at):
    sessions = []
    for candidate in WORKSPACE_TMP.glob("m1b84_session_*"):
        if not candidate.is_dir() or not (candidate / "status").is_file():
            continue
        try:
            if candidate.stat().st_mtime >= started_at - 2:
                sessions.append(candidate)
        except OSError:
            continue
    return max(sessions, key=lambda item: item.stat().st_mtime, default=None)


def launch_application(package, native_bridge_bundle=None, timeout=240):
    validate_package(package)
    WORKSPACE_TMP.mkdir(parents=True, exist_ok=True)
    lock_path = WORKSPACE_TMP / ".aaas-desktop-launch.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            _, status = _control_request({"op": "list"})
        except RuntimeError:
            status = None
        if status is not None and status.get("state") in ("STARTING", "RUNNING"):
            _, result = _control_request({"op": "launch", "package": package}, timeout=90)
            if not result.get("ok"):
                raise RuntimeError(f"active AaaS session could not launch app: {result}")
            return {"mode": "reused", **result}
        if status is not None and status.get("state") in ("STOPPING", "STOPPED", "FAILED"):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    _, current = _control_request({"op": "list"}, timeout=1)
                    if current.get("state") in ("STARTING", "RUNNING"):
                        _, result = _control_request({"op": "launch", "package": package}, timeout=90)
                        if not result.get("ok"):
                            raise RuntimeError(f"AaaS shutdown/start race: {result}")
                        return {"mode": "reused", **result}
                except RuntimeError:
                    break
                time.sleep(.25)

        anchor = _choose_anchor(package)
        command = [sys.executable, str(RUNNER), "--experimental-virtual-display",
                   "--app", package, "--app2", anchor]
        if native_bridge_bundle:
            command.extend(["--diagnostic-native-bridge-overlay", native_bridge_bundle])
        log_path = WORKSPACE_TMP / "aaas-desktop-launch.log"
        started_at = time.time()
        with log_path.open("ab") as log:
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True,
                                       env=os.environ.copy())
        deadline = time.monotonic() + timeout
        last_state = None
        # The runtime publishes its session status before creating the control
        # listener. Waiting on that readiness sentinel avoids queuing requests
        # on the listener while Android is still booting.
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"AaaS startup exited {process.returncode}; see {log_path}")
            session = _newest_session_after(started_at)
            if session is None:
                time.sleep(.25)
                continue
            try:
                last_state = (session / "status").read_text().strip()
            except OSError:
                time.sleep(.25)
                continue
            if last_state in ("FAILED", "STOPPED"):
                raise RuntimeError(f"AaaS startup reached {last_state}; see {log_path}")
            if last_state != "RUNNING":
                time.sleep(.25)
                continue
            try:
                _endpoint, snapshot = _control_request({"op": "list"}, timeout=3)
                last_state = snapshot.get("state")
                windows = snapshot.get("windows", [])
                target = next((window for window in windows
                               if window.get("package") == package
                               and window.get("state") == "RUNNING"), None)
                helper = next((window for window in windows
                               if window.get("package") == anchor
                               and window.get("state") == "RUNNING"), None)
                if target and helper:
                    _path, stopped = _control_request(
                        {"op": "stop_app", "slot": helper["slot"]}, timeout=20)
                    if not stopped.get("ok"):
                        raise RuntimeError(f"bootstrap app shutdown failed: {stopped}")
                    release_deadline = time.monotonic() + 12
                    while time.monotonic() < release_deadline:
                        _path, snapshot = _control_request({"op": "list"}, timeout=3)
                        helper_state = next((window for window in snapshot.get("windows", [])
                                             if window.get("slot") == helper["slot"]), {})
                        if (helper_state.get("state") == "CLOSED" and
                                helper_state.get("presenter_pid") is None):
                            break
                        time.sleep(.25)
                    else:
                        raise RuntimeError("bootstrap app window was not released")
                    return {"mode": "cold-start", "package": package,
                            "slot": target["slot"], "session_log": str(log_path),
                            "bootstrap_window_closed": True}
            except RuntimeError:
                pass
            time.sleep(.5)
        raise RuntimeError(f"AaaS did not become ready within {timeout}s (state={last_state}); "
                           f"see {log_path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install-launcher")
    install.add_argument("--package", required=True)
    install.add_argument("--name")
    install.add_argument("--icon")
    remove = commands.add_parser("remove-launcher")
    remove.add_argument("--package", required=True)
    launch = commands.add_parser("launch")
    launch.add_argument("--package", required=True)
    launch.add_argument("--native-bridge-bundle")
    catalog = commands.add_parser("catalog", help="inspect or refresh installed Android apps")
    catalog_sub = catalog.add_subparsers(dest="catalog_operation", required=True)
    catalog_sub.add_parser("refresh", help="query PackageManager and reconcile XDG entries")
    catalog_sub.add_parser("list", help="show the persistent host catalog")
    args = parser.parse_args(argv)
    try:
        if args.command == "install-launcher":
            result = {"launcher": str(install_launcher(args.package, args.name, args.icon))}
        elif args.command == "remove-launcher":
            path = launcher_path(args.package)
            path.unlink(missing_ok=True)
            result = {"removed": str(path)}
        elif args.command == "catalog" and args.catalog_operation == "refresh":
            result = refresh_package_catalog()
        elif args.command == "catalog":
            _data, catalog_path, _manifest = catalog_paths()
            result = json.loads(catalog_path.read_text(encoding="utf-8"))
        else:
            try:
                result = launch_application(args.package, args.native_bridge_bundle)
            except RuntimeError:
                try:
                    refresh_package_catalog()
                except (OSError, RuntimeError, ValueError):
                    pass
                raise
            try:
                result["catalog_refresh"] = refresh_package_catalog()
            except (OSError, RuntimeError, ValueError) as refresh_error:
                # Launch remains successful if metadata refresh is temporarily
                # unavailable; the explicit catalog refresh command can retry.
                result["catalog_refresh_error"] = str(refresh_error)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"aaas-desktop: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
