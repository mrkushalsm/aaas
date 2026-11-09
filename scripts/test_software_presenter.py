#!/usr/bin/env python3
"""Exercise the AaaS presenter through wl_shm and CPU-only headless Weston.

This test validates Wayland surface/buffer lifecycle only. It deliberately does
not test linux-dmabuf, GBM allocation, DRM synchronization, or Android output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_UUID = "094120c3-e1f8-4a61-a95a-c347ecb711d1"
WESTON_REVISION = "de09947fc128d4c7af3d8e292a1044a812aee954"


class TestFailure(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def disable_core_dumps() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def terminate_owned(process: subprocess.Popen[bytes] | None, timeout: float = 3.0) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def wait_socket(path: Path, process: subprocess.Popen[bytes], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise TestFailure(f"Weston exited before creating its socket ({process.returncode})")
        if path.exists() and stat_socket(path):
            return
        time.sleep(0.05)
    raise TestFailure(f"isolated Weston socket was not created: {path}")


def stat_socket(path: Path) -> bool:
    try:
        return path.is_socket()
    except OSError:
        return False


def read_json_events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("role") == "presenter":
            events.append(value)
    return events


def run_session(*, index: int, frames: int, presenter: Path, producer: Path,
                socket_name: str, run_dir: Path,
                display_name: str, bwrap: str, inside_root: str) -> dict:
    ipc = run_dir / f"presenter-{index}.sock"
    presenter_log = run_dir / f"presenter-{index}.jsonl"
    producer_log = run_dir / f"producer-{index}.log"
    with presenter_log.open("wb") as p_log, producer_log.open("wb") as c_log:
        env = {
            "PATH": os.defpath,
            "HOME": f"{inside_root}/home",
            "XDG_RUNTIME_DIR": f"{inside_root}/runtime",
            "WAYLAND_DISPLAY": socket_name,
            "XDG_CONFIG_HOME": f"{inside_root}/config",
            "XDG_DATA_HOME": f"{inside_root}/data",
            "XDG_CACHE_HOME": f"{inside_root}/cache",
            "XDG_STATE_HOME": f"{inside_root}/state",
            "LC_ALL": "C.UTF-8",
        }
        command = [
            bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
            "--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", "/dev/dri",
            "--proc", "/proc", "--tmpfs", "/home", "--tmpfs", "/tmp",
            "--tmpfs", "/run/user/1000", "--tmpfs", "/opt",
            "--ro-bind", str(presenter), "/opt/aaas-presenter",
            "--dir", inside_root, "--bind", str(run_dir), inside_root,
        ]
        for key, value in env.items():
            command += ["--setenv", key, value]
        for key in ("WAYLAND_SOCKET", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
                    "QT_PLUGIN_PATH", "LD_PRELOAD"):
            command += ["--unsetenv", key]
        command += [
            "/bin/sh", "-c",
            "test ! -d /dev/dri || test -z \"$(ls -A /dev/dri)\" "
            "|| { echo HOST_DRM_VISIBLE; exit 90; }; "
            "test ! -S /run/user/1000/wayland-0 "
            "|| { echo KDE_SOCKET_VISIBLE; exit 90; }; exec \"$@\"",
            "isolated-presenter", "/opt/aaas-presenter", "--socket",
            f"{inside_root}/{ipc.name}", "--software-shm-test",
            "--exit-on-close", "--width", "320", "--height", "568",
            "--display-width", "320", "--display-height", "568",
            "--app-id", f"org.aaas.softwaretest.{display_name}",
            "--trace-buffer-identities",
        ]
        presenter_proc = subprocess.Popen(
            command, stdout=p_log, stderr=subprocess.STDOUT,
            preexec_fn=disable_core_dumps)
        producer_proc = None
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and not ipc.exists():
                if presenter_proc.poll() is not None:
                    raise TestFailure(
                        f"presenter {index} exited before listening: {presenter_proc.returncode}")
                time.sleep(0.02)
            if not ipc.exists():
                raise TestFailure(f"presenter {index} IPC socket not created")

            producer_env = {
                "PATH": os.defpath,
                "HOME": str(run_dir / "home"),
                "LC_ALL": "C.UTF-8",
            }
            producer_proc = subprocess.Popen(
                [str(producer), str(ipc), str(frames)],
                stdout=c_log, stderr=subprocess.STDOUT,
                preexec_fn=disable_core_dumps, env=producer_env)
            deadline = time.monotonic() + 90
            saw_presenter = False
            while time.monotonic() < deadline:
                if presenter_proc.poll() is None:
                    saw_presenter = True
                if producer_proc.poll() is not None and presenter_proc.poll() is not None:
                    break
                time.sleep(0.02)
            if producer_proc.poll() is None:
                raise TestFailure(f"producer {index} exceeded the 90 second bound")
            if presenter_proc.poll() is None:
                raise TestFailure(f"presenter {index} exceeded the 90 second bound")
            if producer_proc.returncode != 0:
                raise TestFailure(
                    f"producer {index} failed ({producer_proc.returncode}); see {producer_log}")
            if presenter_proc.returncode != 0:
                raise TestFailure(
                    f"presenter {index} failed ({presenter_proc.returncode}); see {presenter_log}")
            if not saw_presenter:
                raise TestFailure(f"presenter {index} lifetime was not observed")

        finally:
            terminate_owned(producer_proc)
            terminate_owned(presenter_proc)

    events = read_json_events(presenter_log)
    summaries = [event for event in events if event.get("event") == "summary"]
    imports = [event for event in events if event.get("event") == "wayland_buffer_imported"]
    if len(summaries) != 1:
        raise TestFailure(f"presenter {index} did not emit exactly one summary")
    summary = summaries[0]
    producer_text = producer_log.read_text(encoding="utf-8", errors="replace")
    producer_summary = re.search(
        r"frames_sent=(\d+) actual_wayland_releases=(\d+) outstanding=(\d+) "
        r"max_in_flight=(\d+) peer_closed=(true|false)", producer_text)
    if not producer_summary:
        raise TestFailure(f"producer {index} omitted ownership accounting")
    sent, producer_releases, producer_outstanding, peak, peer_closed = producer_summary.groups()
    if (int(sent) != frames or int(producer_releases) != summary.get("releases") or
            int(producer_outstanding) != summary.get("teardown_invalidated") or
            int(peak) > 2 or (int(producer_outstanding) and peer_closed != "true")):
        raise TestFailure(f"producer {index} ownership contract mismatch: {producer_text}")
    if summary.get("imports") != frames or summary.get("submissions") != frames:
        raise TestFailure(f"presenter {index} submitted/imported count mismatch: {summary}")
    if (summary.get("releases", 0) + summary.get("teardown_invalidated", 0) != frames or
            summary.get("outstanding") != 0):
        raise TestFailure(f"presenter {index} ownership accounting mismatch: {summary}")
    if summary.get("teardown_invalidated", 0) > 1:
        raise TestFailure(f"presenter {index} invalidated more than its final attached buffer")
    if summary.get("rejected") != 0:
        raise TestFailure(f"presenter {index} rejected or invalidated buffers: {summary}")
    if len(imports) != frames:
        raise TestFailure(f"presenter {index} import trace count mismatch: {len(imports)}")
    return {
        "session_index": index,
        "frames": frames,
        "summary": summary,
        "producer_peak_in_flight": int(peak),
        "presenter_namespace_dev_dri_exposed": False,
        "import_events": len(imports),
        "presenter_log": str(presenter_log),
        "presenter_log_sha256": sha256(presenter_log),
        "producer_log": str(producer_log),
        "producer_log_sha256": sha256(producer_log),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--presenter", type=Path, required=True)
    parser.add_argument("--producer", type=Path, required=True)
    parser.add_argument("--weston-prefix", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=256)
    parser.add_argument("--sessions", type=int, choices=(1, 2), default=1,
                        help="independent sequential presenter sessions")
    args = parser.parse_args()

    workspace = args.workspace.resolve(strict=True)
    presenter = args.presenter.resolve(strict=True)
    producer = args.producer.resolve(strict=True)
    prefix = args.weston_prefix.resolve(strict=True)
    if args.frames < 2 or args.frames > 4096:
        parser.error("--frames must be between 2 and 4096")
    if not os.access(presenter, os.X_OK) or not os.access(producer, os.X_OK):
        parser.error("presenter and producer must be executable")
    guard = subprocess.run(
        [sys.executable, str(ROOT / "scripts/android_workspace.py"),
         "--workspace", str(workspace), "check"],
        check=True, text=True, capture_output=True)
    guard_report = json.loads(guard.stdout)
    mount = guard_report.get("mount", {})
    if (mount.get("uuid") != WORKSPACE_UUID or
            guard_report.get("health", {}).get("state") != "HEALTHY_FOR_CONTROLLED_TESTING"):
        raise TestFailure("workspace identity or health guard failed")

    weston_src = workspace / "tmp/m4-isolated-weston/src"
    revision = subprocess.run(
        ["git", "-C", str(weston_src), "rev-parse", "HEAD"],
        check=True, text=True, capture_output=True).stdout.strip()
    if revision != WESTON_REVISION:
        raise TestFailure(f"Weston source revision mismatch: {revision}")
    weston = prefix / "bin/weston"
    if not weston.is_file():
        raise TestFailure(f"missing Weston binary: {weston}")
    bwrap = subprocess.run(["sh", "-c", "command -v bwrap"],
                           text=True, capture_output=True, check=True).stdout.strip()
    if not bwrap:
        raise TestFailure("bubblewrap is unavailable")

    root = Path(__import__("tempfile").mkdtemp(prefix="m4gfx-", dir=workspace / "tmp"))
    for name in ("home", "runtime", "config", "data", "cache", "state"):
        path = root / name
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    (root / "runtime").chmod(0o700)
    run_id = root.name
    socket_name = "aaas-pixman"
    weston_log = root / "weston.log"
    weston_stdout = root / "weston.stdout.log"
    weston_inside = "/run/user/1000/aaas"
    runtime_inside = f"{weston_inside}/runtime"
    xdg = {
        "HOME": f"{weston_inside}/home",
        "XDG_RUNTIME_DIR": runtime_inside,
        "XDG_CONFIG_HOME": f"{weston_inside}/config",
        "XDG_DATA_HOME": f"{weston_inside}/data",
        "XDG_CACHE_HOME": f"{weston_inside}/cache",
        "XDG_STATE_HOME": f"{weston_inside}/state",
        "XDG_SESSION_TYPE": "wayland",
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "LD_LIBRARY_PATH": "/opt/weston/lib:/opt/weston/lib/x86_64-linux-gnu",
        "PATH": "/opt/weston/bin:/usr/bin:/bin",
        "LC_ALL": "C.UTF-8",
    }
    weston_cmd = [
        bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
        "--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", "/dev/dri",
        "--proc", "/proc",
        "--tmpfs", "/home", "--tmpfs", "/tmp", "--tmpfs", "/run/user/1000",
        "--tmpfs", "/opt",
        "--dir", weston_inside, "--bind", str(root), weston_inside,
        "--ro-bind", str(prefix), "/opt/weston",
    ]
    for key, value in xdg.items():
        weston_cmd += ["--setenv", key, value]
    for key in ("WAYLAND_DISPLAY", "WAYLAND_SOCKET", "DISPLAY",
                "DBUS_SESSION_BUS_ADDRESS", "QT_PLUGIN_PATH", "LD_PRELOAD"):
        weston_cmd += ["--unsetenv", key]
    weston_cmd += [
        "/bin/sh", "-c",
        "test ! -d /dev/dri || test -z \"$(ls -A /dev/dri)\" "
        "|| { echo HOST_DRM_VISIBLE; exit 90; }; "
        "test ! -S /run/user/1000/wayland-0 || { echo KDE_SOCKET_VISIBLE; exit 90; }; "
        "exec /opt/weston/bin/weston \"$@\"",
        "isolated-weston", "--backend=headless", "--renderer=pixman",
        f"--socket={socket_name}", "--width=720", "--height=1280",
        "--no-config", f"--log={weston_inside}/weston.log",
    ]

    weston_proc = None
    sessions = []
    try:
        with weston_stdout.open("wb") as output:
            weston_proc = subprocess.Popen(weston_cmd, stdout=output,
                                           stderr=subprocess.STDOUT,
                                           preexec_fn=disable_core_dumps)
        wayland_socket = root / "runtime" / socket_name
        wait_socket(wayland_socket, weston_proc)
        for index in range(args.sessions):
            sessions.append(run_session(
                index=index + 1, frames=args.frames,
                presenter=presenter, producer=producer,
                socket_name=socket_name,
                run_dir=root, display_name=f"window{index + 1}",
                bwrap=bwrap, inside_root=weston_inside))
    finally:
        terminate_owned(weston_proc)

    report = {
        "schema_version": 1,
        "classification": "SOFTWARE_WAYLAND_PROTOCOL_TEST",
        "workspace_uuid": mount.get("uuid"),
        "run_id": run_id,
        "weston_revision": revision,
        "weston_renderer": "pixman (CPU software renderer)",
        "weston_backend": "headless",
        "isolated_compositor_namespaces": ["user", "mount", "pid", "network", "ipc", "uts", "cgroup"],
        "active_kde_socket_passed": False,
        "isolated_dev_dri": False,
        "presenter_sha256": sha256(presenter),
        "producer_sha256": sha256(producer),
        "presenter_backend": "wl_shm_test; memfd-only; no DRM/GBM allocation",
        "independent_sequential_sessions": sessions,
        "weston_log": str(weston_log),
        "weston_log_sha256": sha256(weston_log),
        "weston_stdout": str(weston_stdout),
        "weston_stdout_sha256": sha256(weston_stdout),
        "limitations": [
            "Does not validate linux-dmabuf import or GPU synchronization.",
            "Does not boot Android or exercise Composer3.",
            "Headless output has no human-visible display or physical scanout.",
            "Repeated sessions are sequential, not simultaneous multi-window presentation.",
        ],
    }
    report_path = root / "acceptance.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"evidence={report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, TestFailure, json.JSONDecodeError) as exc:
        print(f"software presenter test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
