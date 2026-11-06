"""Bounded UTF-8 clipboard frames for an active AaaS session."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

MAGIC = b'AASCLIP1\n'
MAX_TEXT_BYTES = 64 * 1024
SUBID_BASE = 100000


def encode_frame(text: str | None) -> bytes:
    if text is None or text == '':
        return MAGIC + b'C\n'
    if not isinstance(text, str):
        raise TypeError('clipboard content must be text or None')
    encoded = text.encode('utf-8', errors='strict')
    if len(encoded) > MAX_TEXT_BYTES or b'\0' in encoded:
        raise ValueError('clipboard text exceeds supported bounds')
    return MAGIC + b'T\n' + encoded


def decode_frame(frame: bytes) -> str | None:
    if not isinstance(frame, bytes) or len(frame) < len(MAGIC) + 2:
        raise ValueError('clipboard frame is truncated')
    if not frame.startswith(MAGIC):
        raise ValueError('clipboard frame magic is invalid')
    kind = frame[len(MAGIC):len(MAGIC) + 1]
    if frame[len(MAGIC) + 1:len(MAGIC) + 2] != b'\n':
        raise ValueError('clipboard frame header is invalid')
    payload = frame[len(MAGIC) + 2:]
    if kind == b'C':
        if payload:
            raise ValueError('clear frame must not contain data')
        return None
    if kind != b'T' or not payload or len(payload) > MAX_TEXT_BYTES or b'\0' in payload:
        raise ValueError('clipboard text frame is invalid')
    try:
        return payload.decode('utf-8', errors='strict')
    except UnicodeDecodeError as error:
        raise ValueError('clipboard text is not valid UTF-8') from error


def atomic_write(path: Path, frame: bytes, *, mode: int = 0o600) -> None:
    """Replace one session IPC frame without exposing a partial write."""
    path = Path(path)
    if path.is_symlink() or not path.parent.is_dir():
        raise ValueError('clipboard IPC path is unsafe')
    decode_frame(frame)
    fd, raw_temporary = tempfile.mkstemp(prefix=f'.{path.name}.',
                                         suffix='.tmp', dir=path.parent)
    temporary = Path(raw_temporary)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as output:
            output.write(frame)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_ipc_directory(ipc_dir: Path) -> Path:
    """Create the non-listable sticky area in which the selected IME writes frames."""
    ipc_dir = Path(ipc_dir)
    if ipc_dir.is_symlink() or not ipc_dir.is_dir():
        raise ValueError('clipboard IPC root must be a real directory')
    target = ipc_dir / 'clipboard'
    if target.is_symlink():
        raise ValueError('clipboard IPC directory must not be a symlink')
    target.mkdir(mode=0o1733, exist_ok=True)
    if target.stat().st_uid != os.getuid() or target.stat().st_dev != ipc_dir.stat().st_dev:
        raise ValueError('clipboard IPC directory has an unexpected owner or filesystem')
    os.chmod(target, 0o1733)
    return target


def cleanup_session_ipc(ipc_dir: Path) -> bool:
    """Remove only clipboard-owned session IPC objects, never follow links."""
    ipc_dir = Path(ipc_dir)
    for name in ('clipboard_host_request', 'clipboard_state',
                 'clipboard_settings_request', 'clipboard_ime_previous',
                 'clipboard_ime_ack', 'clipboard_probe_request',
                 'clipboard_probe_ack',
                 '.clipboard_state.tmp'):
        path = ipc_dir / name
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
    directory = ipc_dir / 'clipboard'
    if directory.is_symlink() or not directory.is_dir():
        return not directory.exists() and not directory.is_symlink()
    for path in directory.iterdir():
        if (path.name == 'clipboard_host_to_android' or
                (path.name.startswith('android-') and path.name.endswith('.frame')) or
                (path.name.startswith('.android-') and path.name.endswith('.tmp'))):
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
    try:
        directory.rmdir()
    except OSError:
        return False
    return True


def clear_session_payloads(ipc_dir: Path) -> bool:
    """Drop clipboard bytes promptly while retaining the empty session directory."""
    ipc_dir = Path(ipc_dir)
    ok = True
    request = ipc_dir / 'clipboard_host_request'
    if request.is_symlink() or request.is_file():
        request.unlink(missing_ok=True)
    directory = ipc_dir / 'clipboard'
    if directory.is_symlink() or not directory.is_dir():
        return not directory.exists() and not directory.is_symlink()
    for path in directory.iterdir():
        if (path.name == 'clipboard_host_to_android' or
                (path.name.startswith('android-') and path.name.endswith('.frame')) or
                (path.name.startswith('.android-') and path.name.endswith('.tmp'))):
            try:
                if path.is_symlink() or path.is_file():
                    path.unlink(missing_ok=True)
                else:
                    ok = False
            except OSError:
                ok = False
    return ok


def app_uid_to_host_uid(android_uid: int) -> int:
    """Translate Android user-0 app UID through the runtime's subordinate map."""
    if isinstance(android_uid, bool) or not isinstance(android_uid, int) or not 10000 <= android_uid <= 65535:
        raise ValueError('Android application UID is outside the mapped app range')
    return SUBID_BASE + android_uid - 1


def parse_runtime_state(value: str) -> tuple[int, bool] | None:
    """Parse the payload-free ``<app uid> <selected>`` runtime state file."""
    fields = value.split()
    if len(fields) != 2 or fields[1] not in ('0', '1'):
        return None
    try:
        uid = int(fields[0], 10)
        app_uid_to_host_uid(uid)
    except ValueError:
        return None
    return uid, fields[1] == '1'


def _proc_start_time(pid: int) -> str:
    record = Path(f'/proc/{pid}/stat').read_text()
    return record[record.rfind(')') + 1:].split()[19]


def start_mapped_bridge(command: list[str], *, stdout, env=None):
    """Start the host Wayland client with rootless access to mapped Android files.

    UID 0 maps to the current host user; Android application UIDs map through
    the established subordinate range. This allows exact UID validation and
    per-package ACLs without making clipboard files world-readable.
    """
    process = subprocess.Popen(
        ['unshare', '-U', '-m', '/bin/sh', '-c',
         'read ready; exec setpriv --reuid=0 --regid=0 --clear-groups "$@"',
         'aaas-clipboard-bridge', *command],
        stdin=subprocess.PIPE, stdout=stdout, stderr=subprocess.STDOUT,
        env=env, start_new_session=True,
    )
    try:
        parent_namespace = os.stat('/proc/self/ns/user').st_ino
        start_identity = _proc_start_time(process.pid)
        deadline = time.monotonic() + 3
        namespace = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('clipboard bridge exited before UID mapping')
            proc = Path(f'/proc/{process.pid}')
            if _proc_start_time(process.pid) != start_identity:
                raise RuntimeError('clipboard bridge PID identity changed')
            candidate = os.stat(proc / 'ns/user').st_ino
            if candidate != parent_namespace:
                namespace = candidate
                break
            time.sleep(.01)
        if namespace is None:
            raise TimeoutError('clipboard bridge user namespace did not initialize')

        def map_identity(helper: str, args: tuple[str, ...]) -> None:
            proc = Path(f'/proc/{process.pid}')
            if (process.poll() is not None or _proc_start_time(process.pid) != start_identity
                    or os.stat(proc / 'ns/user').st_ino != namespace):
                raise RuntimeError(f'clipboard bridge identity changed before {helper}')
            result = subprocess.run([helper, str(process.pid), *args],
                                    check=False, capture_output=True, text=True)
            if result.returncode:
                detail = result.stderr.strip() or result.stdout.strip()
                raise RuntimeError(f'{helper} failed for clipboard bridge: '
                                   f'{detail or result.returncode}')
            if (_proc_start_time(process.pid) != start_identity or
                    os.stat(proc / 'ns/user').st_ino != namespace):
                raise RuntimeError(f'clipboard bridge identity changed after {helper}')

        host_uid = os.getuid()
        host_gid = os.getgid()
        map_identity('newuidmap', ('0', str(host_uid), '1',
                                   '1', str(SUBID_BASE), '65535'))
        expected_uid_map = f'0 {host_uid} 1\n1 {SUBID_BASE} 65535'
        actual_uid_map = Path(f'/proc/{process.pid}/uid_map').read_text().strip()
        if ' '.join(actual_uid_map.split()) != ' '.join(expected_uid_map.split()):
            raise RuntimeError('clipboard bridge UID mapping is unexpected')
        map_identity('newgidmap', ('0', str(host_gid), '1',
                                   '1', str(SUBID_BASE), '65535'))
        expected_gid_map = f'0 {host_gid} 1\n1 {SUBID_BASE} 65535'
        actual_gid_map = Path(f'/proc/{process.pid}/gid_map').read_text().strip()
        if ' '.join(actual_gid_map.split()) != ' '.join(expected_gid_map.split()):
            raise RuntimeError('clipboard bridge GID mapping is unexpected')
        process.stdin.write(b'ready\n')
        process.stdin.flush()
        process.stdin.close()
        return process
    except Exception:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        raise
