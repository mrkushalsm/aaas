#!/usr/bin/env python3
"""Prepare the persistent private Android /data backing directory."""

import json
import os
from pathlib import Path
import signal
import shlex
import subprocess
import tempfile
import time


SCHEMA = 1
DIRECTORY_NAME = 'android-userdata'
DATA_NAME = 'data'
MANIFEST_NAME = '.aaas-userdata.json'


class UserdataError(RuntimeError):
    """Persistent userdata is missing, unsafe, or not recognized by AaaS."""


def prepare_userdata_directory(workspace):
    """Return an initialized persistent ``/data`` directory without migration.

    The caller must first verify the workspace mount identity and its budget.
    Existing unmarked data is never adopted or changed: it may contain user
    files from another runtime or an interrupted/manual migration.
    """
    workspace = Path(workspace).resolve(strict=True)
    if not workspace.is_dir() or workspace.is_symlink():
        raise UserdataError('AaaS workspace must be a real directory')

    root = workspace / DIRECTORY_NAME
    if root.is_symlink():
        raise UserdataError(f'refusing symlinked userdata root: {root}')
    if root.exists() and not root.is_dir():
        raise UserdataError(f'user data root is not a directory: {root}')
    root.mkdir(mode=0o700, exist_ok=True)
    root_stat = root.stat()
    if root_stat.st_uid != os.getuid() or root_stat.st_mode & 0o077:
        raise UserdataError('userdata control directory must remain host-user-only')

    data = root / DATA_NAME
    manifest = root / MANIFEST_NAME
    if data.is_symlink():
        raise UserdataError(f'refusing symlinked userdata backing: {data}')
    if data.exists() and not data.is_dir():
        raise UserdataError(f'user data backing is not a directory: {data}')
    if data.is_mount():
        raise UserdataError('userdata backing must not be an independently mounted filesystem')
    if manifest.is_symlink():
        raise UserdataError(f'refusing symlinked userdata manifest: {manifest}')

    if manifest.exists():
        try:
            record = json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as error:
            raise UserdataError(f'cannot read userdata manifest: {error}') from error
        if (record.get('schema') != SCHEMA
                or record.get('workspace') != str(workspace)
                or record.get('backing') != DATA_NAME
                or not data.is_dir()):
            raise UserdataError('userdata manifest does not match the backing directory')
    else:
        if data.exists() and next(data.iterdir(), None) is not None:
            raise UserdataError(
                f'unrecognized nonempty userdata directory; preserved at {data}')
        data.mkdir(mode=0o700, exist_ok=True)
        record = {
            'schema': SCHEMA,
            'workspace': str(workspace),
            'backing': DATA_NAME,
            'filesystem': 'host directory; filesystem inherited from workspace',
            'migration': 'none; AaaS runtime previously used ephemeral /data',
        }
        fd, temporary_name = tempfile.mkstemp(prefix='.aaas-userdata.', dir=root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(record, stream, indent=2, sort_keys=True)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, manifest)
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    data_stat = data.stat()
    workspace_stat = workspace.stat()
    if data_stat.st_dev != workspace_stat.st_dev:
        raise UserdataError('userdata backing must remain on the verified workspace filesystem')
    return data


def backing_status(path):
    """Return bounded host-side capacity and allocation information."""
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise UserdataError('userdata backing is unavailable')
    usage = allocated_bytes_rootless(path)
    fs = os.statvfs(path)
    return {
        'path': str(path),
        'backing': 'directory',
        'logical_limit': None,
        'allocated_bytes': usage,
        'filesystem_available_bytes': fs.f_bavail * fs.f_frsize,
        'filesystem_total_bytes': fs.f_blocks * fs.f_frsize,
    }


def allocated_bytes_rootless(path):
    """Measure private Android data using a short-lived mapped namespace.

    Android UID ownership intentionally prevents the host's normal directory
    walker from entering private app data. This one-shot read-only helper maps
    the existing subordinate UID/GID range, scans blocks without following
    symlinks, and exits before AaaS starts. It does not change ownership or
    permissions.
    """
    path = Path(path).resolve(strict=True)
    program = '''import os, sys
root = sys.argv[1]
total = 0
seen = set()
def fail(error):
    raise error
for base, dirs, files in os.walk(root, followlinks=False, onerror=fail):
    for name in dirs + files:
        item = os.path.join(base, name)
        info = os.lstat(item)
        identity = (info.st_dev, info.st_ino)
        if identity not in seen:
            seen.add(identity)
            total += info.st_blocks * 512
print(total)
'''
    command = (
        'read ready; '
        'setpriv --reuid=0 --regid=0 --clear-groups python3 -c '
        + shlex.quote(program) + ' "$1"'
    )
    process = subprocess.Popen(
        ['unshare', '-U', '-m', '/bin/sh', '-c', command,
         'aaas-userdata-accounting', str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        parent_userns = os.stat('/proc/self/ns/user').st_ino
        process_start = _proc_start_time(process.pid)
        deadline = time.monotonic() + 3
        child_userns = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise UserdataError('rootless userdata accounting helper exited early')
            try:
                proc = Path(f'/proc/{process.pid}')
                if _proc_start_time(process.pid) != process_start:
                    raise UserdataError(
                        'rootless userdata accounting helper PID identity changed')
                namespace = os.stat(proc / 'ns/user').st_ino
            except FileNotFoundError:
                namespace = parent_userns
            if namespace != parent_userns:
                child_userns = namespace
                break
            time.sleep(.01)
        else:
            raise TimeoutError(
                'rootless userdata accounting user namespace did not initialize')

        def map_identity(helper, *ranges):
            if process.poll() is not None:
                raise UserdataError(
                    f'rootless userdata accounting helper exited before {helper}')
            proc = Path(f'/proc/{process.pid}')
            if (_proc_start_time(process.pid) != process_start
                    or os.stat(proc / 'ns/user').st_ino != child_userns):
                raise UserdataError(
                    f'rootless userdata accounting helper identity changed before {helper}')
            completed = subprocess.run(
                [helper, str(process.pid), *ranges],
                check=False, capture_output=True, text=True,
            )
            if completed.returncode:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise UserdataError(
                    f'{helper} failed for userdata accounting PID {process.pid} '
                    f'(userns {child_userns}): {detail or completed.returncode}')
            if (_proc_start_time(process.pid) != process_start
                    or os.stat(proc / 'ns/user').st_ino != child_userns):
                raise UserdataError(
                    f'rootless userdata accounting helper identity changed after {helper}')

        map_identity('newuidmap', '0', str(os.getuid()), '1',
                     '1', '100000', '65535')
        expected_uid_map = f'0 {os.getuid()} 1\n1 100000 65535'
        actual_uid_map = Path(f'/proc/{process.pid}/uid_map').read_text().strip()
        if ' '.join(actual_uid_map.split()) != ' '.join(expected_uid_map.split()):
            raise UserdataError(
                f'rootless userdata accounting UID map is unexpected: {actual_uid_map}')
        map_identity('newgidmap', '0', str(os.getgid()), '1',
                     '1', '100000', '65535')
        expected_gid_map = f'0 {os.getgid()} 1\n1 100000 65535'
        actual_gid_map = Path(f'/proc/{process.pid}/gid_map').read_text().strip()
        if ' '.join(actual_gid_map.split()) != ' '.join(expected_gid_map.split()):
            raise UserdataError(
                f'rootless userdata accounting GID map is unexpected: {actual_gid_map}')
        process.stdin.write('ready\n')
        process.stdin.flush()
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode:
            raise UserdataError(f'rootless userdata accounting failed: {stderr.strip()}')
        return int(stdout.strip())
    except Exception:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        raise


def _proc_start_time(pid):
    """Return Linux process start ticks without splitting a spaced comm field."""
    record = Path(f'/proc/{pid}/stat').read_text()
    fields_after_comm = record[record.rfind(')') + 1:].split()
    # stat field 22 (starttime); the tail starts at field 3.
    return fields_after_comm[19]
