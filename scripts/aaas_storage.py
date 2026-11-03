"""Persistent host backing directory for Android user 0 shared storage."""

import os
from pathlib import Path
import shlex
import signal
import shutil
import subprocess
import time


DEFAULT_WORKSPACE = Path('/run/media/mrkus/Homework/aaas-workspace')
STORAGE_RELATIVE_PATH = Path('shared-storage/android-user-0')
ANDROID_MEDIA_RELATIVE_PATH = Path('shared-storage/android-media')
ANDROID_MEDIA_RW_ID = 1023
SUBID_BASE = 100000
PUBLIC_STORAGE_DIRECTORIES = (
    'Alarms', 'Audiobooks', 'DCIM', 'Documents', 'Download', 'Movies',
    'Music', 'Notifications', 'Pictures', 'Podcasts', 'Ringtones',
)
ANDROID_STORAGE_DIRECTORIES = ('data', 'media', 'obb')


def backing_path(workspace=None):
    workspace = Path(workspace or DEFAULT_WORKSPACE).expanduser().resolve()
    return workspace / ANDROID_MEDIA_RELATIVE_PATH / '0'


def media_root_path(workspace=None):
    workspace = Path(workspace or DEFAULT_WORKSPACE).expanduser().resolve()
    return workspace / ANDROID_MEDIA_RELATIVE_PATH


def prepare_backing_directory(workspace=None):
    """Create the dedicated user-owned backing directory without migrating data."""
    workspace = Path(workspace or DEFAULT_WORKSPACE).expanduser().resolve()
    path = backing_path(workspace)
    media_root = media_root_path(workspace)
    parent = media_root.parent
    if parent.is_symlink() or media_root.is_symlink() or path.is_symlink():
        raise RuntimeError('shared storage path must not contain a symlink')
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.resolve() != workspace / 'shared-storage':
        raise RuntimeError('shared storage parent escaped the configured workspace')
    if media_root.exists() and not media_root.is_dir():
        raise RuntimeError('Android media root exists and is not a directory')
    media_root.mkdir(mode=0o755, exist_ok=True)
    if media_root.is_symlink() or os.path.ismount(media_root):
        raise RuntimeError('Android media root must be a normal directory')
    if path.exists() and not path.is_dir():
        raise RuntimeError('shared storage backing exists and is not a directory')
    created = not path.exists()
    path.mkdir(mode=0o755, exist_ok=True)
    if path.is_symlink() or os.path.ismount(path):
        raise RuntimeError('shared storage backing must be a normal directory')
    if created and path.stat().st_uid != os.getuid():
        raise RuntimeError('new shared storage backing is not owned by the current user')
    ensure_host_access(media_root)
    ensure_host_access(path)
    _ensure_android_storage_directories(path)
    _ensure_public_directory_acls(path)
    if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError('shared storage backing is not accessible to the current user')
    return path


def _ensure_android_storage_directories(path):
    """Prepare Android's expected shared-storage mountpoints as media_rw."""
    android_dir = path / 'Android'
    if android_dir.is_symlink() or (android_dir.exists() and not android_dir.is_dir()):
        raise RuntimeError('Android shared-storage directory is not a real directory')
    for name in ANDROID_STORAGE_DIRECTORIES:
        candidate = android_dir / name
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_dir()):
            raise RuntimeError(f'Android/{name} must be a real directory')

    if path.stat().st_uid not in (os.getuid(), SUBID_BASE + ANDROID_MEDIA_RW_ID - 1):
        raise RuntimeError('shared storage owner changed unexpectedly')
    setup_as_host_owner = path.stat().st_uid == os.getuid()
    prepare_script = (
        'read ready; cd -- "$1" || exit 20; '
        'if [ "$2" = host ]; then '
        'setfacl -m u:1023:rwx,d:u:1023:rwx . || exit 21; '
        'else '
        'setpriv --reuid=1023 --regid=1023 --clear-groups '
        'setfacl -m u:1023:rwx,d:u:1023:rwx . || exit 22; '
        'fi; '
        'setpriv --reuid=1023 --regid=1023 --clear-groups /bin/sh -c '
        "'mkdir -p -- Android/data Android/media Android/obb "
        + ' '.join(PUBLIC_STORAGE_DIRECTORIES)
        + " || exit; chmod 700 Android/data Android/obb; "
        "setfacl -b Android/data Android/obb'"
    )
    _run_mapped_storage_command(
        path, prepare_script, 'host' if setup_as_host_owner else 'media-rw')


def _run_mapped_storage_command(path, script, mode):
    process = subprocess.Popen(
        ['unshare', '-U', '-m', '-f', '/bin/sh', '-c', script,
         'aaas-storage-prepare', str(path), mode],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('rootless storage helper exited before UID mapping')
            try:
                if Path(f'/proc/{process.pid}/uid_map').read_text().strip():
                    break
            except FileNotFoundError:
                pass
            time.sleep(.01)
        else:
            raise TimeoutError('rootless storage helper UID mapping timed out')
        subprocess.run(
            ['newuidmap', str(process.pid), '0', str(os.getuid()), '1',
             '1', str(SUBID_BASE), '65535'], check=True,
        )
        subprocess.run(
            ['newgidmap', str(process.pid), '0', str(os.getgid()), '1',
             '1', str(SUBID_BASE), '65535'], check=True,
        )
        process.stdin.write('ready\n')
        process.stdin.flush()
        _stdout, stderr = process.communicate(timeout=10)
        if process.returncode:
            raise RuntimeError(f'rootless Android storage setup failed: {stderr.strip()}')
    except Exception:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        raise


def ensure_host_access(path):
    """Ensure the host user ACL survives Android's media_rw ownership model."""
    if not shutil.which('getfacl') or not shutil.which('setfacl'):
        raise RuntimeError(
            'shared storage requires the host acl utilities (getfacl and setfacl)')
    uid = os.getuid()
    query = _acl_entries(path)
    expected = {f'user:{uid}:rwx', f'default:user:{uid}:rwx'}
    if expected.issubset(set(query)):
        _ensure_public_directory_acls(path)
        return
    if path.stat().st_uid == uid:
        _apply_acl_as_host(path)
    elif path.stat().st_uid == SUBID_BASE + ANDROID_MEDIA_RW_ID - 1:
        _apply_acl_as_mapped_media_rw(path)
    else:
        raise RuntimeError(
            f'{path} is owned by uid {path.stat().st_uid} and lacks the host '
            'ACL; refusing to change Android storage ownership')
    verified = _acl_entries(path)
    if not expected.issubset(set(verified)):
        raise RuntimeError('host access ACL did not persist on shared storage')
    _ensure_public_directory_acls(path)


def _acl_entries(path):
    return subprocess.run(
        ['getfacl', '--omit-header', '--numeric', str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()


def _ensure_public_directory_acls(path):
    """Preserve media_rw access and host access on shared public storage only."""
    uid = os.getuid()
    present = [name for name in PUBLIC_STORAGE_DIRECTORIES
               if (path / name).is_dir() and not (path / name).is_symlink()]
    targets = [path, *(path / name for name in present)]
    expected = {
        f'user:{uid}:rwx', f'default:user:{uid}:rwx',
        'group::rwx', 'default:group::rwx',
    }
    if all(expected.issubset(set(_acl_entries(target))) for target in targets):
        return
    if path.stat().st_uid == uid:
        _apply_acl_as_host(path, present)
    elif path.stat().st_uid == SUBID_BASE + ANDROID_MEDIA_RW_ID - 1:
        _apply_acl_as_mapped_media_rw(path, present)
    else:
        raise RuntimeError('shared storage owner changed unexpectedly')


def _apply_acl_as_host(path, directories=()):
    _set_acl(path, uid=os.getuid(), directories=directories)


def _set_acl(path, uid, directories=()):
    targets = [path, *(path / name for name in directories)]
    for target in targets:
        subprocess.run(
            ['setfacl', '-m',
             f'u:{uid}:rwx,d:u:{uid}:rwx,g::rwx,d:g::rwx', str(target)],
            check=True, capture_output=True, text=True,
        )


def _apply_acl_as_mapped_media_rw(path, directories=()):
    """Use the existing rootless Android UID mapping to adjust only ACLs."""
    acl_script = (
        'setfacl -m u:0:rwx,d:u:0:rwx,g::rwx,d:g::rwx . || exit; '
        'for name in "$@"; do '
        '[ -d "$name" ] && [ ! -L "$name" ] || continue; '
        'setfacl -m u:0:rwx,d:u:0:rwx,g::rwx,d:g::rwx -- "$name" || exit; '
        'done'
    )
    command = (
        'read ready; cd -- "$1" || exit 20; '
        'setpriv --reuid=1023 --regid=1023 --clear-groups '
        f'/bin/sh -c {shlex.quote(acl_script)} aaas-acl'
        + ''.join(f' {shlex.quote(name)}' for name in directories)
    )
    process = subprocess.Popen(
        ['unshare', '-U', '-m', '-f', '/bin/sh', '-c', command,
         'aaas-storage-acl', str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('rootless ACL helper exited before UID mapping')
            try:
                if Path(f'/proc/{process.pid}/uid_map').read_text().strip():
                    break
            except FileNotFoundError:
                pass
            time.sleep(.01)
        else:
            raise TimeoutError('rootless ACL helper UID mapping timed out')
        subprocess.run(
            ['newuidmap', str(process.pid), '0', str(os.getuid()), '1',
             '1', str(SUBID_BASE), '65535'], check=True,
        )
        subprocess.run(
            ['newgidmap', str(process.pid), '0', str(os.getgid()), '1',
             '1', str(SUBID_BASE), '65535'], check=True,
        )
        process.stdin.write('ready\n')
        process.stdin.flush()
        _stdout, stderr = process.communicate(timeout=10)
        if process.returncode:
            raise RuntimeError(f'rootless ACL repair failed: {stderr.strip()}')
    except Exception:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        raise
