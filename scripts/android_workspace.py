#!/usr/bin/env python3
"""Bound Android experiments to a verified removable workspace.

No cleanup is performed. A lost mount or exhausted budget terminates a managed
process group and leaves its source and logs in place for inspection.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

try:
    from . import aaas_userdata
except ImportError:
    import aaas_userdata

GIB = 1 << 30
MARKER = '.aaas-workspace.json'
LAYOUT = ('images', 'sources', 'out', 'cache', 'logs', 'tmp', 'mnt')


class WorkspaceError(RuntimeError):
    pass


def mount_identity(target):
    result = subprocess.run(
        ['findmnt', '-T', str(target), '-n', '-o', 'TARGET,SOURCE,FSTYPE,UUID'],
        capture_output=True, text=True, check=True, timeout=3,
    )
    fields = result.stdout.strip().split()
    if len(fields) != 4:
        raise WorkspaceError(f'cannot identify mount for {target}')
    return dict(zip(('target', 'source', 'filesystem', 'uuid'), fields))


def validate_mounted_workspace(workspace, sentinels=()):
    """Cheaply verify the active mount and critical backing paths.

    This intentionally does not repeat allocated-byte accounting. Call
    ``check`` before starting work, then use this bounded identity/access probe
    from an existing foreground session loop to detect mount loss.
    """
    workspace = Path(workspace).absolute()
    marker_path = workspace / MARKER
    if workspace.is_symlink() or not workspace.is_dir():
        raise WorkspaceError(f'workspace backing is unavailable: {workspace}')
    if marker_path.is_symlink() or not marker_path.is_file():
        raise WorkspaceError(f'missing or unsafe workspace marker: {marker_path}')
    try:
        marker = json.loads(marker_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkspaceError(f'cannot read workspace marker: {error}') from error
    if marker.get('schema') != 1 or not marker.get('workspace_id'):
        raise WorkspaceError('invalid workspace marker')
    target = Path(marker.get('mount_target', '')).absolute()
    if not workspace.is_relative_to(target) or workspace == target:
        raise WorkspaceError('workspace is outside the recorded external mount')
    actual = mount_identity(target)
    if actual['target'] != str(target):
        raise WorkspaceError(f'external disk is not mounted at {target}')
    if actual['uuid'] != marker.get('mount_uuid') or actual['filesystem'] != marker.get('filesystem'):
        raise WorkspaceError('external disk identity changed')
    if not os.access(workspace, os.W_OK | os.X_OK):
        raise WorkspaceError('workspace is not writable')
    try:
        workspace_stat = workspace.stat()
        stat = os.statvfs(target)
    except OSError as error:
        raise WorkspaceError(f'workspace filesystem is unavailable: {error}') from error
    free = stat.f_bavail * stat.f_frsize
    reserve = int(marker.get('reserve_gib', 20)) * GIB
    if free < reserve:
        raise WorkspaceError(
            f'workspace free space below reserve: free={free} reserve={reserve}')
    for raw_path in sentinels:
        path = Path(raw_path)
        try:
            info = path.lstat()
        except OSError as error:
            raise WorkspaceError(f'workspace backing unavailable at {path}: {error}') from error
        if path.is_symlink() or info.st_dev != workspace_stat.st_dev:
            raise WorkspaceError(f'workspace backing changed or escaped at {path}')
    return {'mount': actual, 'free_bytes': free, 'workspace': str(workspace)}


def allocated_bytes(root):
    total = 0
    seen = set()
    private_userdata = Path(root) / aaas_userdata.DIRECTORY_NAME
    scan_private_userdata = private_userdata.is_dir() and not private_userdata.is_symlink()
    for base, dirs, files in os.walk(root, followlinks=False):
        if scan_private_userdata and Path(base) == Path(root):
            dirs[:] = [name for name in dirs if name != aaas_userdata.DIRECTORY_NAME]
        for name in dirs + files:
            path = os.path.join(base, name)
            st = os.lstat(path)
            key = (st.st_dev, st.st_ino)
            if key not in seen:
                seen.add(key)
                total += st.st_blocks * 512
    if scan_private_userdata:
        total += aaas_userdata.allocated_bytes_rootless(private_userdata)
    return total


def initialize(workspace, mount_target):
    workspace = Path(workspace).absolute()
    target = Path(mount_target).absolute()
    if workspace.parent != target or workspace.name in ('', '.', '..'):
        raise WorkspaceError('workspace must be a new direct child of the mount')
    identity = mount_identity(target)
    if identity['target'] != str(target):
        raise WorkspaceError(f'external disk is not mounted at {target}')
    if identity['filesystem'] not in ('ext4', 'xfs', 'btrfs', 'ntfs3'):
        raise WorkspaceError(f'unsupported filesystem: {identity["filesystem"]}')
    if workspace.exists():
        return check(workspace)
    if not os.access(target, os.W_OK | os.X_OK):
        raise WorkspaceError('mount is not writable')
    workspace.mkdir(mode=0o700)
    marker = dict(schema=1, workspace_id=str(uuid.uuid4()),
                  mount_target=str(target), mount_uuid=identity['uuid'],
                  filesystem=identity['filesystem'], budget_gib=100,
                  reserve_gib=20, working_ceiling_gib=80)
    (workspace / MARKER).write_text(json.dumps(marker, indent=2) + '\n')
    for name in LAYOUT:
        (workspace / name).mkdir()
    return check(workspace)


def check(workspace, predicted=0):
    workspace = Path(workspace).absolute()
    marker_path = workspace / MARKER
    if not marker_path.is_file():
        raise WorkspaceError(f'missing workspace marker: {marker_path}')
    marker = json.loads(marker_path.read_text())
    if marker.get('schema') != 1 or not marker.get('workspace_id'):
        raise WorkspaceError('invalid workspace marker')
    target = Path(marker['mount_target']).absolute()
    if not workspace.is_relative_to(target) or workspace == target:
        raise WorkspaceError('workspace is outside the recorded external mount')
    actual = mount_identity(target)
    if actual['target'] != str(target):
        raise WorkspaceError(f'external disk is not mounted at {target}')
    if actual['uuid'] != marker['mount_uuid'] or actual['filesystem'] != marker['filesystem']:
        raise WorkspaceError('external disk identity changed')
    if not workspace.is_dir() or not os.access(workspace, os.W_OK | os.X_OK):
        raise WorkspaceError('workspace is not writable')
    stat = os.statvfs(target)
    free = stat.f_bavail * stat.f_frsize
    used = allocated_bytes(workspace)
    ceiling = min(marker['budget_gib'] - marker['reserve_gib'],
                  marker['working_ceiling_gib']) * GIB
    reserve = marker['reserve_gib'] * GIB
    if predicted < 0 or used + predicted > ceiling or free - predicted < reserve:
        raise WorkspaceError(
            f'budget exceeded: used={used} predicted={predicted} '
            f'ceiling={ceiling} free={free} reserve={reserve}'
        )
    return dict(workspace=str(workspace), mount=actual, used_bytes=used,
                free_bytes=free, predicted_bytes=predicted,
                ceiling_bytes=ceiling, reserve_bytes=reserve)


def run_guarded(workspace, predicted, interval, command, log_path):
    first = check(workspace, predicted)
    if not command:
        raise WorkspaceError('missing command')
    process = subprocess.Popen(command, start_new_session=True)
    stream = open(log_path, 'a', encoding='utf-8') if log_path else None
    try:
        while True:
            event = dict(timestamp=time.time(), pid=process.pid)
            try:
                event.update(check(workspace))
                event['status'] = 'within_budget'
            except (WorkspaceError, OSError, subprocess.CalledProcessError) as exc:
                event['status'] = 'stopped'
                event['reason'] = str(exc)
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                print(json.dumps(event), file=stream or sys.stderr, flush=True)
                raise WorkspaceError(event['reason']) from exc
            print(json.dumps(event), file=stream or sys.stderr, flush=True)
            code = process.poll()
            if code is not None:
                return code
            time.sleep(interval)
    finally:
        if stream:
            stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', default=os.environ.get('AAAS_WORKSPACE'))
    parser.add_argument('--mount', help='mounted external volume for init')
    parser.add_argument('--predict-gib', type=float, default=0)
    parser.add_argument('--interval', type=float, default=2)
    parser.add_argument('--log', type=Path)
    parser.add_argument('action', choices=('init', 'check', 'run'))
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.workspace:
        parser.error('--workspace or AAAS_WORKSPACE is required')
    try:
        predicted = int(args.predict_gib * GIB)
        if args.action == 'init':
            if not args.mount:
                parser.error('--mount is required for init')
            print(json.dumps(initialize(args.workspace, args.mount), indent=2))
            return 0
        if args.action == 'check':
            print(json.dumps(check(args.workspace, predicted), indent=2))
            return 0
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        return run_guarded(args.workspace, predicted, args.interval, command, args.log)
    except (WorkspaceError, OSError, subprocess.CalledProcessError) as exc:
        print(f'workspace guard: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
