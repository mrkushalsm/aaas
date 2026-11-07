#!/usr/bin/env python3
"""Bound Android experiments to a verified removable workspace.

No cleanup is performed. A lost mount or exhausted budget terminates a managed
process group and leaves its source and logs in place for inspection.
"""
import argparse
import json
import os
from pathlib import Path
import re
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
HEALTH_POLICY = Path(__file__).resolve().parents[1] / 'manifests' / 'workspace-health.json'
HEALTH_STATES = {
    'HEALTHY_FOR_CONTROLLED_TESTING', 'HEALTH_UNKNOWN', 'INTEGRITY_WARNING',
    'REPAIR_REQUIRED', 'DEVICE_FAILURE_SUSPECTED',
}
HEALTH_BLOCKING_STATES = {
    'HEALTH_UNKNOWN', 'INTEGRITY_WARNING', 'REPAIR_REQUIRED',
    'DEVICE_FAILURE_SUSPECTED',
}
_HEALTH_CACHE = {}


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


def _read_health_policy(path=HEALTH_POLICY):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'schema': 1, 'volumes': {}}
    except (OSError, json.JSONDecodeError) as error:
        raise WorkspaceError(f'workspace health policy unavailable or malformed: {error}') from error
    if (not isinstance(value, dict) or value.get('schema') != 1
            or not isinstance(value.get('volumes'), dict)):
        raise WorkspaceError('workspace health policy has an invalid schema')
    return value


def _valid_recovery_attestation(entry):
    """Require explicit offline and post-recovery evidence to lift a pause."""
    recovery = entry.get('recovery')
    if not isinstance(recovery, dict):
        return False
    offline = recovery.get('offline_check')
    post = recovery.get('post_check')
    device = recovery.get('device_health')
    return (
        isinstance(offline, dict)
        and offline.get('result') == 'clean'
        and bool(offline.get('tool'))
        and bool(offline.get('completed_at'))
        and bool(offline.get('evidence_ref'))
        and isinstance(post, dict)
        and bool(post.get('checked_at'))
        and bool(post.get('boot_id'))
        and post.get('uuid') == entry.get('uuid')
        and post.get('ntfs3_errors') == 0
        and post.get('metadata_probes') == 'pass'
        and isinstance(device, dict)
        and device.get('status') == 'healthy'
        and bool(device.get('evidence_ref'))
    )


def policy_health(identity, policy_path=HEALTH_POLICY):
    """Return tracked health state for this UUID without touching the volume."""
    policy = _read_health_policy(policy_path)
    entry = policy['volumes'].get(identity.get('uuid'))
    if entry is None:
        return None
    if not isinstance(entry, dict) or entry.get('uuid') != identity.get('uuid'):
        return {'state': 'HEALTH_UNKNOWN', 'reason': 'invalid health-pause record'}
    state = entry.get('state')
    if not isinstance(state, str) or state not in HEALTH_STATES:
        return {'state': 'HEALTH_UNKNOWN', 'reason': 'unknown health-pause state'}
    if state == 'HEALTHY_FOR_CONTROLLED_TESTING' and not _valid_recovery_attestation(entry):
        return {'state': 'HEALTH_UNKNOWN', 'reason': 'recovery attestation is incomplete'}
    return {'state': state, 'reason': entry.get('reason', ''),
            'incident_id': entry.get('incident_id')}


def _journal_ntfs_events(source, timeout=3):
    """Read a bounded current-boot kernel journal slice; never changes state."""
    device = Path(source).name
    result = subprocess.run(
        ['journalctl', '-k', '-b', '--no-pager', '--output=json',
         '--grep=ntfs3\\(', '--lines=200'],
        capture_output=True, text=True, check=True, timeout=timeout,
    )
    events = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = str(item.get('MESSAGE', ''))
        match = re.search(r'ntfs3\(([^)]+)\):', message)
        if match and match.group(1) == device:
            try:
                priority = int(item.get('PRIORITY', 7))
            except (TypeError, ValueError):
                priority = 7
            if priority <= 4:
                events.append({
                    'message': message,
                    'priority': priority,
                    'boot_id': item.get('_BOOT_ID'),
                    'realtime_usec': item.get('__REALTIME_TIMESTAMP'),
                    'monotonic_usec': item.get('__MONOTONIC_TIMESTAMP'),
                })
    return events


def assess_workspace_health(identity, policy_path=HEALTH_POLICY, now=None):
    """Classify filesystem health without implying a full consistency check."""
    tracked = policy_health(identity, policy_path)
    if tracked:
        return tracked
    filesystem = identity.get('filesystem')
    if filesystem != 'ntfs3':
        return {'state': 'HEALTH_UNKNOWN',
                'reason': 'no filesystem-specific integrity attestation'}
    key = (identity.get('uuid'), identity.get('source'))
    now = time.monotonic() if now is None else now
    cached = _HEALTH_CACHE.get(key)
    if cached and now - cached[0] < 30:
        return cached[1]
    try:
        events = _journal_ntfs_events(identity['source'])
    except (OSError, subprocess.SubprocessError, WorkspaceError) as error:
        result = {'state': 'HEALTH_UNKNOWN',
                  'reason': f'current-boot NTFS3 journal evidence unavailable: {error}'}
    else:
        if events:
            result = {'state': 'INTEGRITY_WARNING',
                      'reason': f'{len(events)} device-matched NTFS3 kernel error(s)',
                      'events': events}
        else:
            result = {'state': 'HEALTH_UNKNOWN',
                      'reason': 'no matching current-boot kernel errors; offline consistency and device health are unverified'}
    _HEALTH_CACHE[key] = (now, result)
    return result


def _require_workspace_health(identity):
    health = assess_workspace_health(identity)
    should_block = health['state'] in HEALTH_BLOCKING_STATES
    # NTFS3 is the only filesystem currently used by the persistent Android
    # workspace. Its unknown integrity state cannot be resolved by mount/space
    # checks, so fail closed. Other supported filesystems retain the prior
    # mount/capacity contract while reporting that integrity was not attested.
    should_block = should_block and (
        identity.get('filesystem') == 'ntfs3'
        or health['state'] != 'HEALTH_UNKNOWN'
    )
    if should_block:
        raise WorkspaceError(
            f"workspace health {health['state']}: {health.get('reason', 'assessment required')}"
        )
    return health


def diagnose_workspace(workspace, policy_path=HEALTH_POLICY, smartctl='smartctl'):
    """Collect bounded, read-only workspace/device diagnostics."""
    workspace = Path(workspace).absolute()
    marker_path = workspace / MARKER
    if marker_path.is_symlink() or not marker_path.is_file():
        raise WorkspaceError(f'missing or unsafe workspace marker: {marker_path}')
    try:
        marker = json.loads(marker_path.read_text(encoding='utf-8'))
        if (marker.get('schema') != 1 or not marker.get('workspace_id')
                or not marker.get('mount_target')):
            raise ValueError('invalid workspace marker')
        target = Path(marker['mount_target']).absolute()
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise WorkspaceError(f'cannot read valid workspace marker: {error}') from error
    identity = mount_identity(target)
    if (identity.get('target') != str(target)
            or identity.get('uuid') != marker.get('mount_uuid')
            or identity.get('filesystem') != marker.get('filesystem')):
        raise WorkspaceError('workspace mount identity does not match its marker')
    policy = policy_health(identity, policy_path)
    try:
        events = _journal_ntfs_events(identity['source'])
        journal = {'available': True, 'current_boot_device_errors': events}
    except (OSError, subprocess.SubprocessError) as error:
        journal = {'available': False, 'error': str(error)}
    smart = {'attempted': False, 'available': False,
             'note': 'passive SMART/NVMe query only; no test or scan is run'}
    if Path(smartctl).is_file() or smartctl == 'smartctl':
        smart['attempted'] = True
        try:
            device = identity['source']
            try:
                parent = subprocess.run(
                    ['lsblk', '-ndo', 'PKNAME', device], capture_output=True,
                    text=True, check=True, timeout=3,
                ).stdout.strip()
                if parent:
                    device = str(Path('/dev') / parent)
            except (OSError, subprocess.SubprocessError):
                pass
            result = subprocess.run(
                [smartctl, '-x', '-n', 'standby', device],
                capture_output=True, text=True, timeout=5,
            )
            smart['returncode'] = result.returncode
            smart['available'] = result.returncode == 0
            smart['output'] = (result.stdout + result.stderr)[-4000:]
        except (OSError, subprocess.SubprocessError) as error:
            smart['error'] = str(error)
    health = policy or assess_workspace_health(identity, policy_path)
    return {'workspace': str(workspace), 'mount': identity, 'health': health,
            'journal': journal, 'smart': smart,
            'read_only': True,
            'scope_note': 'no full filesystem consistency check is performed'}


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
    health = _require_workspace_health(actual)
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
    return {'mount': actual, 'free_bytes': free, 'workspace': str(workspace),
            'health': health}


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
    _require_workspace_health(identity)
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
    health = _require_workspace_health(actual)
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
                ceiling_bytes=ceiling, reserve_bytes=reserve,
                health=health)


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
    parser.add_argument('action', choices=('init', 'check', 'health', 'run'))
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
        if args.action == 'health':
            report = diagnose_workspace(args.workspace)
            print(json.dumps(report, indent=2))
            return 0 if report['health']['state'] == 'HEALTHY_FOR_CONTROLLED_TESTING' else 2
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        return run_guarded(args.workspace, predicted, args.interval, command, args.log)
    except (WorkspaceError, OSError, subprocess.CalledProcessError) as exc:
        print(f'workspace guard: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
