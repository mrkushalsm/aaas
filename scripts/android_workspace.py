#!/usr/bin/env python3
"""Bound Android experiments to a verified removable workspace.

No cleanup is performed. A lost mount or exhausted budget terminates a managed
process group and leaves its source and logs in place for inspection.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

try:
    from . import aaas_userdata
except ImportError:
    import aaas_userdata

GIB = 1 << 30
DEFAULT_WORKSPACE_FREE_RESERVE_GIB = 2
MIN_WORKSPACE_FREE_RESERVE_GIB = 1
MAX_WORKSPACE_FREE_RESERVE_GIB = 32
HOST_ROOT_FREE_RESERVE_BYTES = 20 * GIB
MARKER = '.aaas-workspace.json'
LAYOUT = ('images', 'sources', 'out', 'cache', 'logs', 'tmp', 'mnt')
HEALTH_POLICY = Path(__file__).resolve().parents[1] / 'manifests' / 'workspace-health.json'
REPOSITORY_ROOT = HEALTH_POLICY.parents[1]
STORAGE_JOURNAL_PATTERN = (
    r'(?i)(ntfs3\(|EXT4-fs\s+\(|JBD2:|I/O error|Buffer I/O error|'
    r'blk_update_request|uas.*(?:abort|reset)|'
    r'usb\s+\S+:.*(?:reset|disconnect|error))'
)
HEALTH_STATES = {
    'HEALTHY_FOR_CONTROLLED_TESTING', 'HEALTH_UNKNOWN', 'INTEGRITY_WARNING',
    'REPAIR_REQUIRED', 'DEVICE_FAILURE_SUSPECTED',
}
HEALTH_BLOCKING_STATES = {
    'HEALTH_UNKNOWN', 'INTEGRITY_WARNING', 'REPAIR_REQUIRED',
    'DEVICE_FAILURE_SUSPECTED',
}
_HEALTH_CACHE = {}
RECOVERY_POST_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
RECOVERY_OFFLINE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


class WorkspaceError(RuntimeError):
    pass


def _free_reserve_gib(marker):
    """Read the enrolled filesystem reserve, migrating legacy markers safely."""
    value = marker.get('workspace_free_reserve_gib',
                       DEFAULT_WORKSPACE_FREE_RESERVE_GIB)
    if (isinstance(value, bool) or not isinstance(value, int)
            or not MIN_WORKSPACE_FREE_RESERVE_GIB <= value <= MAX_WORKSPACE_FREE_RESERVE_GIB):
        raise WorkspaceError(
            f'workspace free-space reserve must be from '
            f'{MIN_WORKSPACE_FREE_RESERVE_GIB} to {MAX_WORKSPACE_FREE_RESERVE_GIB} GiB')
    return value


def _host_root_reserve_gib(marker):
    value = marker.get('host_root_free_reserve_gib', HOST_ROOT_FREE_RESERVE_BYTES // GIB)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 256:
        raise WorkspaceError('host root free-space reserve must be from 0 to 256 GiB')
    return value


def _capacity_snapshot(target, workspace_reserve_bytes, predicted=0,
                       root_reserve_bytes=HOST_ROOT_FREE_RESERVE_BYTES):
    """Check available blocks on both the workspace filesystem and host root."""
    if predicted < 0:
        raise WorkspaceError('predicted workspace growth must not be negative')
    try:
        workspace_stat = os.statvfs(target)
        root_stat = os.statvfs('/')
        same_filesystem = os.stat(target).st_dev == os.stat('/').st_dev
    except OSError as error:
        raise WorkspaceError(f'cannot inspect workspace filesystem capacity: {error}') from error
    workspace_block = workspace_stat.f_frsize or workspace_stat.f_bsize
    root_block = root_stat.f_frsize or root_stat.f_bsize
    workspace_available = workspace_stat.f_bavail * workspace_block
    root_available = root_stat.f_bavail * root_block
    workspace_after = workspace_available - predicted
    root_after = root_available - (predicted if same_filesystem else 0)
    if workspace_after < workspace_reserve_bytes:
        raise WorkspaceError(
            'workspace filesystem free space below configured reserve: '
            f'available={workspace_available} predicted={predicted} '
            f'reserve={workspace_reserve_bytes}')
    root_reserve_applies = same_filesystem
    if root_reserve_applies and root_after < root_reserve_bytes:
        raise WorkspaceError(
            'host root filesystem free space below reserve: '
            f'available={root_available} predicted={predicted if same_filesystem else 0} '
            f'reserve={root_reserve_bytes}')
    total_blocks = getattr(workspace_stat, 'f_blocks', 0)
    free_blocks = getattr(workspace_stat, 'f_bfree',
                          max(0, total_blocks - workspace_stat.f_bavail))
    total = total_blocks * workspace_block
    fs_used = max(0, total_blocks - free_blocks) * workspace_block
    return {
        'filesystem_total_bytes': total,
        'filesystem_used_bytes': fs_used,
        'filesystem_available_bytes': workspace_available,
        'workspace_free_reserve_bytes': workspace_reserve_bytes,
        'workspace_available_after_prediction_bytes': workspace_after,
        'host_root_available_bytes': root_available,
        'host_root_reserve_bytes': root_reserve_bytes,
        'host_root_available_after_prediction_bytes': root_after,
        'host_root_reserve_applies': root_reserve_applies,
        'predicted_bytes': predicted,
        'capacity_policy': 'filesystem_available_blocks',
    }


def mount_identity(target):
    result = subprocess.run(
        ['findmnt', '-T', str(target), '-n', '-o', 'TARGET,SOURCE,FSTYPE,UUID,ID,OPTIONS'],
        capture_output=True, text=True, check=True, timeout=3,
    )
    fields = result.stdout.strip().split()
    if len(fields) != 6:
        raise WorkspaceError(f'cannot identify mount for {target}')
    return dict(zip(('target', 'source', 'filesystem', 'uuid', 'mount_id', 'options'), fields))


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


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).timestamp()


def _current_boot_id():
    try:
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        return None


def _sha256_evidence(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _evidence_matches(record, repository_root=None):
    if not isinstance(record, dict) or not _sha256_evidence(record.get('evidence_sha256')):
        return False
    relative = record.get('evidence_path')
    evidence_relative = Path(relative) if isinstance(relative, str) else Path()
    if (not isinstance(relative, str) or not relative or evidence_relative.is_absolute()
            or '..' in evidence_relative.parts):
        return False
    root = Path(repository_root or REPOSITORY_ROOT).resolve()
    candidate = root / relative
    current = candidate
    while current != root:
        if current.is_symlink():
            return False
        current = current.parent
        if not current.is_relative_to(root):
            return False
    path = candidate.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return False
    try:
        if path.stat().st_size > 16 * 1024 * 1024:
            return False
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False
    return digest == record['evidence_sha256']


def _device_serial(source):
    try:
        parent = subprocess.run(
            ['lsblk', '-ndo', 'PKNAME', source], capture_output=True,
            text=True, check=True, timeout=3,
        ).stdout.strip()
        if not parent:
            return None
        result = subprocess.run(
            ['udevadm', 'info', '--query=property', '--name', str(Path('/dev') / parent)],
            capture_output=True, text=True, check=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        if line.startswith('ID_SERIAL='):
            return line.partition('=')[2]
    return None


def _valid_recovery_attestation(entry, identity=None, current_boot_id=None, now=None,
                                repository_root=None):
    """Require UUID/device-bound offline and post-recovery evidence."""
    recovery = entry.get('recovery')
    if not isinstance(recovery, dict):
        return False
    offline = recovery.get('offline_check')
    post = recovery.get('post_check')
    device = recovery.get('device_health')
    stable_device = entry.get('device')
    if not all(isinstance(value, dict) for value in (offline, post, device, stable_device)):
        return False
    now = time.time() if now is None else now
    current_boot_id = current_boot_id or _current_boot_id()
    # Some recovery evidence is reported after the command completed and its
    # shell output did not include a timestamp. recorded_at is the evidence
    # capture time; completed_at remains supported for existing records.
    offline_at = _timestamp(offline.get('completed_at') or offline.get('recorded_at'))
    device_at = _timestamp(device.get('checked_at'))
    post_at = _timestamp(post.get('checked_at'))
    if not all(value is not None for value in (offline_at, device_at, post_at)):
        return False
    filesystem = offline.get('filesystem') or entry.get('filesystem')
    stable_serial = stable_device.get('serial')
    stable_identity = stable_device.get('udev_id') or stable_serial
    fs_errors = post.get('filesystem_errors')
    if fs_errors is None:
        # Read old policy records written before the filesystem-neutral field.
        fs_errors = post.get('ntfs3_errors')
    device_status = device.get('status')
    return (
        offline.get('result') == 'clean'
        and offline.get('volume_uuid') == entry.get('uuid')
        and (not filesystem or filesystem == offline.get('filesystem'))
        and (filesystem != 'ext4' or
             ('e2fsck' in str(offline.get('tool', '')).lower()
              and offline.get('mode') == 'read-only'))
        and bool(offline.get('tool'))
        and _evidence_matches(offline, repository_root)
        and now - offline_at <= RECOVERY_OFFLINE_MAX_AGE_SECONDS
        # A SMART PASS with historical interface counters is enough for
        # controlled testing when the counters are recorded as a baseline.
        # It is not a claim that the transport can never fail again.
        and device_status in ('healthy', 'media_passed_transport_history')
        and device.get('serial') == stable_serial
        and bool(stable_device.get('path'))
        and _evidence_matches(device, repository_root)
        and offline_at <= post_at <= now
        and now - device_at <= RECOVERY_POST_MAX_AGE_SECONDS
        and device_at <= now
        and now - post_at <= RECOVERY_POST_MAX_AGE_SECONDS
        and post.get('uuid') == entry.get('uuid')
        and post.get('device_serial') == stable_identity
        and post.get('boot_id') == current_boot_id
        and (identity is None or identity.get('source') == post.get('source'))
        and (identity is None or str(identity.get('mount_id')) == str(post.get('mount_epoch')))
        and (identity is None or _device_serial(identity.get('source')) == stable_identity)
        and bool(post.get('mount_epoch'))
        and fs_errors == 0
        and post.get('transport_errors') == 0
        and post.get('metadata_probes') == 'pass'
        and post.get('workspace_manifest') == 'pass'
        and post.get('userdata_manifest') == 'pass'
        and _evidence_matches(post, repository_root)
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
    if entry.get('recovery') is not None:
        if not _valid_recovery_attestation(entry, identity=identity):
            return {'state': 'HEALTH_UNKNOWN', 'reason': 'recovery attestation is incomplete or stale'}
        if state != 'HEALTHY_FOR_CONTROLLED_TESTING':
            return {'state': 'HEALTHY_FOR_CONTROLLED_TESTING',
                    'reason': 'recovery evidence accepted; original incident retained',
                    'incident_id': entry.get('incident_id')}
    elif state == 'HEALTHY_FOR_CONTROLLED_TESTING':
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


def _classify_storage_event(message, priority, partition, disk, usb_path=None):
    match = re.search(r'ntfs3\(([^)]+)\):', message)
    if match and match.group(1) == partition and priority <= 4:
        return 'ntfs3_integrity'
    ext4 = re.search(rf'EXT4-fs\s+\({re.escape(partition)}\):', message)
    if ext4 and re.search(r'error|failed|shut down|abort', message, re.I):
        return 'ext4_integrity'
    if re.search(rf'(?:I/O error|Buffer I/O error|blk_update_request).*\bdev(?:ice)?\s+{re.escape(partition)}\b', message, re.I):
        return 'block_io'
    if re.search(rf'(?:I/O error|Buffer I/O error|blk_update_request).*\bdev(?:ice)?\s+{re.escape(disk)}\b', message, re.I):
        return 'block_io'
    if disk in message and re.search(r'JBD2:.*(?:I/O error|failed|abort)', message, re.I):
        return 'block_io'
    if disk in message and re.search(r'uas_eh|uas.*(?:abort|reset)', message, re.I):
        return 'uas_transport'
    if usb_path and re.search(
            rf'usb\s+{re.escape(usb_path)}:.*(?:reset|disconnect|error)', message,
            re.I):
        return 'usb_transport'
    return None


def _journal_workspace_storage_events(identity, timeout=3, limit=500):
    """Read a bounded current-boot journal for this partition and its device."""
    source = identity['source']
    partition = Path(source).name
    try:
        parent_name = subprocess.run(
            ['lsblk', '-ndo', 'PKNAME', source], capture_output=True,
            text=True, check=True, timeout=3,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        parent_name = ''
    disk = parent_name or partition
    usb_path = None
    try:
        sysfs_path = str((Path('/sys/class/block') / disk / 'device').resolve(strict=True))
        usb_match = re.search(r'/([0-9]+-[0-9]+(?:\\.[0-9]+)*)/', sysfs_path)
        usb_path = usb_match.group(1) if usb_match else None
    except OSError:
        pass
    result = subprocess.run(
        ['journalctl', '-k', '-b', '--no-pager', '--output=json',
         f'--grep={STORAGE_JOURNAL_PATTERN}', f'--lines={limit}'], capture_output=True,
        text=True, check=False, timeout=timeout,
    )
    # journalctl uses status 1 for a successful query with no matching entries.
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode, result.args, output=result.stdout, stderr=result.stderr)
    lines = result.stdout.splitlines()
    events = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = str(item.get('MESSAGE', ''))
        try:
            priority = int(item.get('PRIORITY', 7))
        except (TypeError, ValueError):
            priority = 7
        kind = _classify_storage_event(message, priority, partition, disk, usb_path)
        if kind:
            events.append({
                'kind': kind, 'message': message, 'priority': priority,
                'boot_id': item.get('_BOOT_ID'),
                'realtime_usec': item.get('__REALTIME_TIMESTAMP'),
                'monotonic_usec': item.get('__MONOTONIC_TIMESTAMP'),
            })
    return {'events': events, 'bounded_lines': len(lines),
            'truncated': len(lines) >= limit}


def _journal_post_recovery_events(identity, entry, timeout=3):
    """Find device-correlated NTFS/transport errors after recovery evidence."""
    recovery = entry['recovery']
    post = recovery['post_check']
    stable = entry['device']
    partition = Path(identity['source']).name
    disk = Path(stable['path']).name
    command = [
        'journalctl', '-k', '-b', '--no-pager', '--output=json',
        f"--since={post['checked_at']}",
        f'--grep={STORAGE_JOURNAL_PATTERN}', '--lines=500',
    ]
    result = subprocess.run(command, capture_output=True, text=True,
                            check=False, timeout=timeout)
    if getattr(result, 'returncode', 0) not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode, command, output=result.stdout, stderr=result.stderr)
    lines = result.stdout.splitlines()
    if len(lines) >= 500:
        raise WorkspaceError('post-recovery journal window exceeded its 500-entry bound')
    usb_path = stable.get('usb_path')
    events = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = str(item.get('MESSAGE', ''))
        try:
            priority = int(item.get('PRIORITY', 7))
        except (TypeError, ValueError):
            priority = 7
        kind = _classify_storage_event(message, priority, partition, disk,
                                       usb_path)
        if kind:
            events.append({
                'kind': kind, 'message': message, 'priority': priority,
                'boot_id': item.get('_BOOT_ID'),
                'realtime_usec': item.get('__REALTIME_TIMESTAMP'),
                'monotonic_usec': item.get('__MONOTONIC_TIMESTAMP'),
            })
    return events


def assess_workspace_health(identity, policy_path=HEALTH_POLICY, now=None):
    """Classify filesystem health without implying a full consistency check."""
    tracked = policy_health(identity, policy_path)
    if tracked:
        if tracked['state'] == 'HEALTHY_FOR_CONTROLLED_TESTING':
            policy = _read_health_policy(policy_path)
            entry = policy['volumes'][identity.get('uuid')]
            post = entry['recovery']['post_check']
            key = (identity.get('uuid'), identity.get('source'), post['checked_at'])
            now_mono = time.monotonic() if now is None else now
            cached = _HEALTH_CACHE.get(key)
            if cached and now_mono - cached[0] < 5:
                return cached[1]
            try:
                events = _journal_post_recovery_events(identity, entry)
            except (OSError, subprocess.SubprocessError, WorkspaceError) as error:
                result = {'state': 'HEALTH_UNKNOWN',
                          'reason': f'post-recovery storage journal unavailable: {error}'}
            else:
                if events:
                    transport = any(item['kind'] not in (
                        'ntfs3_integrity', 'ext4_integrity') for item in events)
                    result = {
                        'state': 'DEVICE_FAILURE_SUSPECTED' if transport else 'INTEGRITY_WARNING',
                        'reason': f'{len(events)} post-recovery device-correlated storage error(s)',
                        'events': events,
                    }
                else:
                    result = tracked
            _HEALTH_CACHE[key] = (now_mono, result)
            return result
        return tracked
    filesystem = identity.get('filesystem')
    if filesystem in ('ext4', 'xfs', 'btrfs'):
        key = (identity.get('uuid'), identity.get('source'))
        now_mono = time.monotonic() if now is None else now
        cached = _HEALTH_CACHE.get(key)
        if cached and now_mono - cached[0] < 30:
            return cached[1]
        try:
            report = _journal_workspace_storage_events(identity)
        except (OSError, subprocess.SubprocessError, WorkspaceError) as error:
            result = {'state': 'HEALTH_UNKNOWN',
                      'reason': f'current-boot storage journal unavailable: {error}'}
        else:
            events = report['events']
            if events:
                transport = any(item['kind'] in ('block_io', 'uas_transport',
                                                  'usb_transport') for item in events)
                result = {
                    'state': 'DEVICE_FAILURE_SUSPECTED' if transport else 'INTEGRITY_WARNING',
                    'reason': f'{len(events)} device-correlated storage error(s) this boot',
                    'events': events,
                }
            else:
                result = {
                    'state': 'HEALTHY_FOR_CONTROLLED_TESTING',
                    'reason': ('no recorded incident and no device-correlated storage errors '
                               'observed in the current boot; hardware health is not certified'),
                    'observation': 'current-boot journal only',
                }
        _HEALTH_CACHE[key] = (now_mono, result)
        return result
    if filesystem != 'ntfs3':
        return {'state': 'HEALTH_UNKNOWN',
                'reason': 'filesystem has no supported health observation policy'}
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
    # Resolve the module-level policy at call time so applications/tests that
    # provide a policy path do not accidentally use the import-time default.
    health = assess_workspace_health(identity, policy_path=HEALTH_POLICY)
    should_block = health['state'] in HEALTH_BLOCKING_STATES
    # NTFS3 with unknown integrity remains fail-closed. Explicitly quarantined
    # volumes on any supported filesystem also fail closed; an accepted,
    # evidence-backed recovery attestation can permit controlled testing.
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
        journal_result = _journal_workspace_storage_events(identity)
        journal = {'available': not journal_result['truncated'],
                   'current_boot_device_errors': journal_result['events'],
                   'bounded_lines': journal_result['bounded_lines'],
                   'truncated': journal_result['truncated']}
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
    health = assess_workspace_health(identity, policy_path)
    return {'workspace': str(workspace), 'mount': identity, 'health': health,
            'journal': journal, 'smart': smart,
            'read_only': True,
            'scope_note': 'no full filesystem consistency check is performed'}


def _flatten_lsblk(nodes):
    for node in nodes:
        yield node
        yield from _flatten_lsblk(node.get('children') or [])


def diagnose_device(device_path, policy_path=HEALTH_POLICY, smartctl='smartctl'):
    """Inspect block-device metadata without mounting or writing the volume."""
    requested = str(device_path)
    if not requested.startswith('/dev/') or '\x00' in requested:
        raise WorkspaceError('device path must name a block device under /dev')
    try:
        result = subprocess.run(
            ['lsblk', '--json', '-o',
             'NAME,PATH,TYPE,FSTYPE,UUID,MOUNTPOINTS,MODEL,SERIAL,TRAN,ROTA,RO,SIZE',
             requested], capture_output=True, text=True, check=True, timeout=3,
        )
        tree = json.loads(result.stdout).get('blockdevices', [])
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, AttributeError) as error:
        raise WorkspaceError(f'cannot inspect block device {requested}: {error}') from error
    nodes = list(_flatten_lsblk(tree))
    selected = next((item for item in nodes if item.get('path') == requested), None)
    if selected is None:
        raise WorkspaceError(f'block device not present in lsblk output: {requested}')
    if selected.get('type') == 'part':
        partition = selected
        parent = next((item for item in tree if item.get('name') == selected.get('pkname')), None)
        if parent is None:
            try:
                parent_name = subprocess.run(
                    ['lsblk', '-ndo', 'PKNAME', requested], capture_output=True,
                    text=True, check=True, timeout=3,
                ).stdout.strip()
                parent_path = str(Path('/dev') / parent_name) if parent_name else requested
            except (OSError, subprocess.SubprocessError):
                parent_path = requested
        else:
            parent_path = parent.get('path', requested)
    else:
        parent = selected
        partition = next((item for item in nodes
                          if item.get('type') == 'part' and item.get('uuid')),
                         selected)
        parent_path = selected.get('path', requested)
    identity = {'source': partition.get('path', requested),
                'filesystem': partition.get('fstype'),
                'uuid': partition.get('uuid')}
    if not identity['uuid']:
        raise WorkspaceError('selected filesystem partition has no readable UUID')
    try:
        udev_result = subprocess.run(
            ['udevadm', 'info', '--query=property', '--name', parent_path],
            capture_output=True, text=True, check=True, timeout=3,
        )
        properties = dict(line.split('=', 1) for line in udev_result.stdout.splitlines()
                          if '=' in line)
    except (OSError, subprocess.SubprocessError) as error:
        properties = {'_error': str(error)}
    disk_name = Path(parent_path).name
    partition_name = Path(identity['source']).name
    sysfs_device = Path('/sys/class/block') / disk_name / 'device'
    try:
        sysfs_path = str(sysfs_device.resolve(strict=True))
    except OSError:
        sysfs_path = ''
    usb_match = re.search(r'/(\d+-\d+(?:\.\d+)*)/', sysfs_path)
    usb_path = usb_match.group(1) if usb_match else None
    try:
        journal_result = subprocess.run(
            ['journalctl', '-k', '-b', '--no-pager', '--output=json', '--lines=500'],
            capture_output=True, text=True, check=True, timeout=3,
        )
        journal_lines = journal_result.stdout.splitlines()
        events = []
        for line in journal_lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = str(item.get('MESSAGE', ''))
            priority = int(item.get('PRIORITY', 7)) if str(item.get('PRIORITY', '7')).isdigit() else 7
            kind = _classify_storage_event(message, priority, partition_name,
                                           disk_name, usb_path)
            if kind:
                events.append({'kind': kind, 'message': message,
                               'priority': priority, 'boot_id': item.get('_BOOT_ID'),
                               'realtime_usec': item.get('__REALTIME_TIMESTAMP'),
                               'monotonic_usec': item.get('__MONOTONIC_TIMESTAMP')})
        truncated = len(journal_lines) >= 500
        journal = {'available': not truncated, 'boot_id': _current_boot_id(),
                   'storage_errors': events, 'bounded_lines': len(journal_lines),
                   'truncated': truncated}
    except (OSError, subprocess.SubprocessError) as error:
        journal = {'available': False, 'error': str(error)}
    tracked = policy_health(identity, policy_path)
    if tracked and not (tracked['state'] == 'HEALTHY_FOR_CONTROLLED_TESTING'
                        and journal.get('truncated')):
        health = tracked
    elif tracked:
        health = {'state': 'HEALTH_UNKNOWN',
                  'reason': 'current-boot storage journal exceeded diagnostic bound'}
    elif journal.get('storage_errors'):
        errors = journal['storage_errors']
        transport = any(item['kind'] != 'ntfs3_integrity' for item in errors)
        health = {'state': 'DEVICE_FAILURE_SUSPECTED' if transport else 'INTEGRITY_WARNING',
                  'reason': f'{len(errors)} current-boot device-correlated storage error(s)'}
    else:
        health = {'state': 'HEALTH_UNKNOWN',
                  'reason': 'offline filesystem check and device-health evidence are unverified'}
    smart = {'attempted': False, 'available': False}
    try:
        smart_result = subprocess.run(
            [smartctl, '-x', '-n', 'standby', parent_path],
            capture_output=True, text=True, timeout=5,
        )
        smart.update(attempted=True, available=smart_result.returncode == 0,
                     returncode=smart_result.returncode,
                     output=(smart_result.stdout + smart_result.stderr)[-4000:])
    except (OSError, subprocess.SubprocessError) as error:
        smart.update(attempted=True, error=str(error))
    return {'device': selected, 'partition': partition, 'parent_path': parent_path,
            'udev': properties, 'usb_sysfs_path': sysfs_path,
            'mounted': bool(selected.get('mountpoints') or partition.get('mountpoints')),
            'health': health, 'journal': journal, 'smart': smart,
            'read_only': True,
            'scope_note': 'no mount, full filesystem check, repair, test, or scan performed'}


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
    options = set(actual.get('options', '').split(','))
    if 'ro' in options:
        raise WorkspaceError('workspace filesystem is mounted read-only')
    if 'noexec' in options:
        raise WorkspaceError('workspace filesystem is mounted noexec; Android binaries cannot run there')
    health = _require_workspace_health(actual)
    if not os.access(workspace, os.W_OK | os.X_OK):
        raise WorkspaceError('workspace is not writable')
    workspace_stat = workspace.stat()
    reserve = _free_reserve_gib(marker) * GIB
    capacity = _capacity_snapshot(
        target, reserve, root_reserve_bytes=_host_root_reserve_gib(marker) * GIB)
    for raw_path in sentinels:
        path = Path(raw_path)
        try:
            info = path.lstat()
        except OSError as error:
            raise WorkspaceError(f'workspace backing unavailable at {path}: {error}') from error
        if path.is_symlink() or info.st_dev != workspace_stat.st_dev:
            raise WorkspaceError(f'workspace backing changed or escaped at {path}')
    return {'mount': actual, 'free_bytes': capacity['filesystem_available_bytes'],
            'workspace': str(workspace), 'capacity': capacity, 'health': health}


def allocated_bytes(root):
    total = 0
    seen = set()
    root = Path(root)
    candidates = root / 'rootfs-candidates'
    candidate_bytes = _allocated_bytes_rootless(candidates) if (
        candidates.is_dir() and not candidates.is_symlink()) else 0
    private_userdata = Path(root) / aaas_userdata.DIRECTORY_NAME
    scan_private_userdata = private_userdata.is_dir() and not private_userdata.is_symlink()
    for base, dirs, files in os.walk(root, followlinks=False):
        if Path(base) == root:
            dirs[:] = [name for name in dirs if name != 'rootfs-candidates']
            if scan_private_userdata:
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
    return total + candidate_bytes


def _allocated_bytes_rootless(path):
    """Account Android-owned candidate trees through the runner's UID map."""
    # If the caller already runs in the same broad subordinate-ID namespace
    # used by the runner, a nested --map-auto namespace cannot be created on
    # several kernels. Account directly in that namespace instead; this keeps
    # the guard's full du accounting and does not bypass the workspace policy.
    uid_map = Path('/proc/self/uid_map')
    try:
        mapped_root = (os.geteuid() == 0 and any(
            int(parts[0]) == 1 and int(parts[2]) > 1
            for line in uid_map.read_text().splitlines()
            if len(parts := line.split()) == 3))
    except (OSError, ValueError):
        mapped_root = False
    if mapped_root:
        try:
            result = subprocess.run(['du', '-s', '--block-size=1', '--', str(path)],
                                    capture_output=True, text=True, check=True, timeout=60)
            return int(result.stdout.split()[0])
        except (OSError, subprocess.SubprocessError, IndexError, ValueError) as error:
            raise WorkspaceError(f'cannot account rootfs-candidates in the active UID map: {error}') from error
    try:
        result = subprocess.run(
            ['unshare', '--user', '--map-root-user', '--map-auto', 'du', '-s',
             '--block-size=1', '--', str(path)],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise WorkspaceError(f'cannot account rootfs-candidates in a mapped user namespace: {error}') from error
    try:
        return int(result.stdout.split()[0])
    except (IndexError, ValueError) as error:
        raise WorkspaceError('rootless du returned invalid candidate usage') from error


def _filesystem_mount_target(path):
    result = subprocess.run(
        ['findmnt', '-T', str(path), '-n', '-o', 'TARGET'],
        capture_output=True, text=True, check=True, timeout=3,
    )
    target = Path(result.stdout.strip())
    if not target.is_absolute():
        raise WorkspaceError(f'cannot identify filesystem mount for {path}')
    return target


def filesystem_capability_probe(workspace, *, require_acl=True):
    """Run bounded filesystem semantics probes in a private disposable dir."""
    workspace = Path(workspace).resolve(strict=True)
    if workspace.is_symlink() or not workspace.is_dir():
        raise WorkspaceError('workspace must be a real directory for capability checks')
    acl_tool = shutil.which('setfacl')
    if require_acl and not acl_tool:
        raise WorkspaceError('missing dependency setfacl; install the host ACL tools')
    report = {'filesystem': mount_identity(_filesystem_mount_target(workspace))['filesystem'],
              'ownership': False, 'mode': False, 'hard_links': False,
              'symlinks': False, 'atomic_rename': False, 'xattrs': False,
              'sqlite': False, 'acl': 'not_required'}
    with tempfile.TemporaryDirectory(prefix='.aaas-fs-probe-', dir=workspace) as temporary:
        root = Path(temporary)
        source = root / 'source'
        source.write_bytes(b'aaas filesystem probe')
        report['ownership'] = source.stat().st_uid == os.getuid()
        source.chmod(0o700)
        report['mode'] = os.access(source, os.R_OK | os.W_OK | os.X_OK)
        link = root / 'hardlink'
        os.link(source, link)
        report['hard_links'] = link.stat().st_ino == source.stat().st_ino
        symbolic = root / 'symlink'
        symbolic.symlink_to(source.name)
        report['symlinks'] = symbolic.is_symlink() and symbolic.read_bytes() == source.read_bytes()
        renamed = root / 'renamed'
        os.replace(source, renamed)
        report['atomic_rename'] = renamed.read_bytes() == b'aaas filesystem probe'
        os.setxattr(renamed, 'user.aaas_probe', b'1')
        report['xattrs'] = os.getxattr(renamed, 'user.aaas_probe') == b'1'
        db = sqlite3.connect(root / 'probe.sqlite')
        try:
            db.execute('create table probe (value integer)')
            db.execute('insert into probe values (1)')
            db.commit()
            report['sqlite'] = db.execute('select value from probe').fetchone() == (1,)
        finally:
            db.close()
        if require_acl:
            acl_path = root / 'acl-probe'
            acl_path.write_text('acl probe')
            # A named, unrelated UID exercises POSIX ACL support even when
            # the probing user owns the file and would only update user::.
            probe_uid = 65534 if os.getuid() != 65534 else 65533
            subprocess.run([acl_tool, '-m', f'u:{probe_uid}:rw', str(acl_path)],
                           capture_output=True, text=True, check=True, timeout=3)
            getfacl = shutil.which('getfacl')
            if not getfacl:
                raise WorkspaceError('missing dependency getfacl; install the host ACL tools')
            acl = subprocess.run([getfacl, '-ncp', str(acl_path)], capture_output=True,
                                 text=True, check=True, timeout=3).stdout
            report['acl'] = any(
                line.startswith(f'user:{probe_uid}:rw') for line in acl.splitlines())
    failed = [key for key in ('ownership', 'mode', 'hard_links', 'symlinks',
                              'atomic_rename', 'xattrs', 'sqlite', 'acl')
              if report[key] is not True]
    if failed:
        raise WorkspaceError('workspace filesystem lacks required semantics: '
                             + ', '.join(failed))
    return report


def initialize(workspace, mount_target=None, *, adopt=False,
               free_reserve_gib=DEFAULT_WORKSPACE_FREE_RESERVE_GIB,
               host_root_reserve_gib=HOST_ROOT_FREE_RESERVE_BYTES // GIB):
    workspace = Path(workspace).expanduser().absolute()
    current = workspace
    while current != current.parent:
        if current.is_symlink():
            raise WorkspaceError(f'workspace path contains a symlink: {current}')
        current = current.parent
    workspace = workspace.resolve(strict=False)
    target = Path(mount_target).absolute() if mount_target else _filesystem_mount_target(workspace.parent)
    if workspace == target or not workspace.is_relative_to(target):
        raise WorkspaceError('workspace must be inside, but not equal to, its backing mount')
    identity = mount_identity(target)
    target = Path(identity['target'])
    if workspace == target or not workspace.is_relative_to(target):
        raise WorkspaceError(f'external disk is not mounted at {target}')
    if identity['filesystem'] not in ('ext4', 'xfs', 'btrfs', 'ntfs3'):
        raise WorkspaceError(f'unsupported filesystem: {identity["filesystem"]}')
    if (isinstance(free_reserve_gib, bool) or not isinstance(free_reserve_gib, int)
            or not MIN_WORKSPACE_FREE_RESERVE_GIB <= free_reserve_gib
            <= MAX_WORKSPACE_FREE_RESERVE_GIB):
        raise WorkspaceError(
            f'workspace free-space reserve must be from '
            f'{MIN_WORKSPACE_FREE_RESERVE_GIB} to {MAX_WORKSPACE_FREE_RESERVE_GIB} GiB')
    if (isinstance(host_root_reserve_gib, bool)
            or not isinstance(host_root_reserve_gib, int)
            or not 0 <= host_root_reserve_gib <= 256):
        raise WorkspaceError('host root free-space reserve must be from 0 to 256 GiB')
    options = set(identity.get('options', '').split(','))
    if 'ro' in options:
        raise WorkspaceError('workspace filesystem is mounted read-only')
    if 'noexec' in options:
        raise WorkspaceError('workspace filesystem is mounted noexec; Android binaries cannot run there')
    _require_workspace_health(identity)
    _capacity_snapshot(target, free_reserve_gib * GIB,
                       root_reserve_bytes=host_root_reserve_gib * GIB)
    if workspace.exists():
        if workspace.is_symlink() or not workspace.is_dir():
            raise WorkspaceError('workspace path is not a real directory')
        if (workspace / MARKER).is_file():
            return check(workspace)
        if not adopt and next(workspace.iterdir(), None) is not None:
            raise WorkspaceError('missing workspace marker; existing data is unmarked; '
                                 'pass --adopt-existing only after reviewing its contents')
    else:
        creation_parent = workspace.parent
        while not creation_parent.exists() and creation_parent != target:
            creation_parent = creation_parent.parent
        if (not creation_parent.is_dir()
                or not os.access(creation_parent, os.W_OK | os.X_OK)):
            raise WorkspaceError(
                f'workspace parent is not writable: {creation_parent}')
        workspace.mkdir(mode=0o700, parents=True)
    marker = dict(schema=1, workspace_id=str(uuid.uuid4()),
                  mount_target=str(target), mount_uuid=identity['uuid'],
                  filesystem=identity['filesystem'], capacity_policy_version=2,
                  workspace_free_reserve_gib=free_reserve_gib,
                  host_root_free_reserve_gib=host_root_reserve_gib)
    # Probe required semantics before enrollment; use a private disposable
    # directory and never rewrite permissions on user data.
    capabilities = filesystem_capability_probe(workspace)
    marker['filesystem_capabilities'] = capabilities
    marker_tmp = workspace / f'.{MARKER}.{uuid.uuid4().hex}.tmp'
    marker_tmp.write_text(json.dumps(marker, indent=2) + '\n', encoding='utf-8')
    os.chmod(marker_tmp, 0o600)
    os.replace(marker_tmp, workspace / MARKER)
    for name in LAYOUT:
        path = workspace / name
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise WorkspaceError(f'workspace layout entry is not a real directory: {path}')
        path.mkdir(exist_ok=True)
    return check(workspace)


def check(workspace, predicted=0):
    workspace = Path(workspace).expanduser().absolute()
    current = workspace
    while current != current.parent:
        if current.is_symlink():
            raise WorkspaceError(f'workspace path contains a symlink: {current}')
        current = current.parent
    workspace = workspace.resolve(strict=False)
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
    options = set(actual.get('options', '').split(','))
    if 'ro' in options:
        raise WorkspaceError('workspace filesystem is mounted read-only')
    if 'noexec' in options:
        raise WorkspaceError('workspace filesystem is mounted noexec; Android binaries cannot run there')
    health = _require_workspace_health(actual)
    if not workspace.is_dir() or not os.access(workspace, os.W_OK | os.X_OK):
        raise WorkspaceError('workspace is not writable')
    reserve = _free_reserve_gib(marker) * GIB
    capacity = _capacity_snapshot(
        target, reserve, predicted,
        root_reserve_bytes=_host_root_reserve_gib(marker) * GIB)
    used = allocated_bytes(workspace)
    return dict(workspace=str(workspace), mount=actual, used_bytes=used,
                free_bytes=capacity['filesystem_available_bytes'],
                predicted_bytes=predicted, ceiling_bytes=None,
                reserve_bytes=reserve, capacity=capacity, health=health)


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
    parser.add_argument('--device', help='block device for read-only health diagnostics')
    parser.add_argument('--predict-gib', type=float, default=0)
    parser.add_argument('--free-reserve-gib', type=int,
                        default=DEFAULT_WORKSPACE_FREE_RESERVE_GIB,
                        help='free blocks to reserve on a newly enrolled workspace filesystem')
    parser.add_argument('--interval', type=float, default=2)
    parser.add_argument('--log', type=Path)
    parser.add_argument('action', choices=('init', 'check', 'health', 'run'))
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.workspace and not (args.action == 'health' and args.device):
        parser.error('--workspace or AAAS_WORKSPACE is required')
    try:
        predicted = int(args.predict_gib * GIB)
        if args.action == 'init':
            if not args.mount:
                parser.error('--mount is required for init')
            print(json.dumps(initialize(args.workspace, args.mount,
                                        free_reserve_gib=args.free_reserve_gib), indent=2))
            return 0
        if args.action == 'check':
            print(json.dumps(check(args.workspace, predicted), indent=2))
            return 0
        if args.action == 'health':
            report = (diagnose_device(args.device) if args.device
                      else diagnose_workspace(args.workspace))
            print(json.dumps(report, indent=2))
            return 0 if report['health']['state'] == 'HEALTHY_FOR_CONTROLLED_TESTING' else 2
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        return run_guarded(args.workspace, predicted, args.interval, command, args.log)
    except (WorkspaceError, OSError, subprocess.CalledProcessError) as exc:
        print(f'workspace guard: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
