#!/usr/bin/env python3
"""User-level desktop launchers and on-demand launch for AaaS applications."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts/run_aaas.py"
WORKSPACE_TMP = Path("/run/media/mrkus/Homework/aaas-workspace/tmp")
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")
ANCHORS = ("com.android.settings", "com.android.contacts")


def applications_dir(env=None):
    env = os.environ if env is None else env
    data_home = Path(env.get("XDG_DATA_HOME", Path.home() / ".local/share"))
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


def validate_package(package):
    if not isinstance(package, str) or not PACKAGE.fullmatch(package):
        raise ValueError("package must be a dotted Android application ID")
    return package


def render_launcher(package, name, icon=None):
    validate_package(package)
    if not name or "\n" in name or "\r" in name:
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
    args = parser.parse_args(argv)
    try:
        if args.command == "install-launcher":
            result = {"launcher": str(install_launcher(args.package, args.name, args.icon))}
        elif args.command == "remove-launcher":
            path = launcher_path(args.package)
            path.unlink(missing_ok=True)
            result = {"removed": str(path)}
        else:
            result = launch_application(args.package, args.native_bridge_bundle)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"aaas-desktop: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
