"""Shared discovery for per-session AaaS control sockets."""

from pathlib import Path
import hashlib
import os


def session_socket_path(workspace, session_name, runtime_dir=None):
    runtime_root = Path(runtime_dir or os.environ.get(
        'XDG_RUNTIME_DIR', f'/tmp/aaas-{os.getuid()}')).expanduser()
    workspace_id = hashlib.sha256(str(Path(workspace)).encode()).hexdigest()[:10]
    candidate = runtime_root / 'aaas' / workspace_id / f'{session_name}.sock'
    if len(os.fsencode(candidate)) >= 108:
        runtime_root = Path(f'/tmp/aaas-{os.getuid()}')
        candidate = runtime_root / 'aaas' / workspace_id / f'{session_name}.sock'
    if len(os.fsencode(candidate)) >= 108:
        raise ValueError('cannot construct an AaaS control socket within the AF_UNIX path limit')
    return candidate


def socket_candidates(workspace_tmp):
    """Yield the advertised short socket path, with legacy-path fallback."""
    root = Path(workspace_tmp)
    sessions = sorted(root.glob('m1b84_session_*'),
                      key=lambda path: path.stat().st_mtime, reverse=True)
    seen = set()
    for session in sessions:
        ipc = session / 'ipc'
        pointer = ipc / 'aaas-control.path'
        try:
            value = pointer.read_text(encoding='utf-8').strip()
            candidate = Path(value)
            if candidate.is_absolute() and len(value.encode()) < 108 and value not in seen:
                seen.add(value)
                yield candidate
        except (OSError, UnicodeError):
            pass
        legacy = ipc / 'aaas-control.sock'
        if len(str(legacy).encode()) < 108 and str(legacy) not in seen:
            seen.add(str(legacy))
            yield legacy


def session_ipc_dir(workspace_tmp, socket_path):
    """Find the session IPC directory advertising a short control socket."""
    target = Path(socket_path)
    root = Path(workspace_tmp)
    for session in root.glob('m1b84_session_*'):
        if session.is_symlink() or not session.is_dir():
            continue
        ipc = session / 'ipc'
        try:
            advertised = (ipc / 'aaas-control.path').read_text(
                encoding='utf-8').strip()
        except (OSError, UnicodeError):
            continue
        if advertised == str(target):
            return ipc
    # Legacy sessions kept the control socket directly in their IPC directory.
    parent = target.parent
    if parent.name == 'ipc' and (parent.parent.parent == root
                                or root in parent.parents):
        return parent
    raise FileNotFoundError('control socket has no matching AaaS session')
