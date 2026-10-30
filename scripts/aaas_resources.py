"""Bounded, read-only host resource snapshots for AaaS test sessions."""

import json
import os
from pathlib import Path
import re
import tempfile
import time


CGROUP_ROOT = Path('/sys/fs/cgroup')
PROCESS_MARKERS = (
    'surfaceflinger', 'system_server', 'lmkd', 'zygote', 'composer',
    'aaas-input-adapter', 'wayland-host-presenter', 'aaas-display-broker',
)
MAX_PROCESS_ROWS = 128
MAX_PERIODIC_SAMPLES = 3600


def parse_meminfo(text):
    result = {}
    for line in text.splitlines():
        match = re.match(r'([^:]+):\s*(\d+)(?:\s+(\S+))?', line)
        if match:
            result[match.group(1)] = {
                'value': int(match.group(2)), 'unit': match.group(3) or None,
            }
    return result


def parse_psi(text):
    result = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        values = {}
        for field in parts[1:]:
            if '=' not in field:
                continue
            key, value = field.split('=', 1)
            try:
                values[key] = float(value) if key.startswith('avg') else int(value)
            except ValueError:
                values[key] = value
        result[parts[0]] = values
    return result


def _read(path):
    try:
        return Path(path).read_text()
    except OSError as error:
        return {'unavailable': error.errno}


def _cgroup_path(pid):
    content = _read(f'/proc/{pid}/cgroup')
    if not isinstance(content, str):
        return None
    for line in content.splitlines():
        if line.startswith('0::'):
            return line[3:]
    return None


def _cgroup_snapshot(path):
    if not path:
        return None
    requested = Path(path)
    if requested.is_absolute():
        try:
            relative = requested.relative_to(CGROUP_ROOT)
        except ValueError:
            # /proc/<pid>/cgroup uses hierarchy-relative paths such as
            # /user.slice/...; only absolute filesystem paths are rooted at
            # /sys/fs/cgroup.
            relative = Path(path.lstrip('/'))
        if '..' in relative.parts:
            return {'path': path, 'unavailable': 'invalid_cgroup_path'}
        directory = CGROUP_ROOT / relative
    else:
        directory = CGROUP_ROOT / path.lstrip('/')
    result = {'path': path}
    for name in ('memory.current', 'memory.peak', 'memory.low', 'memory.high',
                 'memory.max', 'memory.swap.current', 'memory.swap.max'):
        value = _read(directory / name)
        if isinstance(value, str):
            value = value.strip()
            if value != 'max':
                try:
                    value = int(value)
                except ValueError:
                    pass
        result[name] = value
    for name in ('memory.events', 'memory.swap.events'):
        value = _read(directory / name)
        if isinstance(value, str):
            parsed = {}
            for line in value.splitlines():
                fields = line.split()
                if len(fields) == 2:
                    try:
                        parsed[fields[0]] = int(fields[1])
                    except ValueError:
                        pass
            value = parsed
        result[name] = value
    pressure = _read(directory / 'memory.pressure')
    result['memory.pressure'] = parse_psi(pressure) if isinstance(pressure, str) else pressure
    return result


def _process_role(name, cmdline, tracked_packages=()):
    lower = name.lower()
    if b'run_aaas.py' in cmdline:
        return 'launcher'
    if b'bwrap --as-pid-1' in cmdline or name == 'bwrap':
        return 'container'
    role = next((marker for marker in PROCESS_MARKERS
                 if marker in lower or
                 (len(lower) >= 12 and marker.startswith(lower))), None)
    if role is not None:
        return role
    for package in tracked_packages:
        if package and package.encode().lower() in cmdline.lower():
            return f'android_app:{package}'
    return None


def _pss_kib(smaps_rollup):
    if not isinstance(smaps_rollup, str):
        return None
    match = re.search(r'^Pss:\s*(\d+)\s*kB$', smaps_rollup, re.MULTILINE)
    return int(match.group(1)) if match else None


def _processes(tracked_packages=()):
    rows = []
    truncated = False
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / 'status').read_text()
            name_match = re.search(r'^Name:\s*(.*)$', status, re.MULTILINE)
            if not name_match:
                continue
            name = name_match.group(1).strip()
            cmdline = (entry / 'cmdline').read_bytes()[:4096].replace(b'\0', b' ').lower()
            role = _process_role(name, cmdline, tracked_packages)
            if role is None:
                continue
            rss = re.search(r'^VmRSS:\s*(\d+)\s*kB$', status, re.MULTILINE)
            smaps_rollup = _read(entry / 'smaps_rollup')
            oom_text = _read(entry / 'oom_score_adj')
            oom = (re.search(r'^\s*(\d+)\s*$', oom_text, re.MULTILINE)
                   if isinstance(oom_text, str) else None)
            rows.append({
                'pid': int(entry.name), 'name': name, 'role': role,
                'rss_kb': int(rss.group(1)) if rss else None,
                'pss_kb': _pss_kib(smaps_rollup),
                'oom_score_adj': int(oom.group(1)) if oom else None,
                'cgroup': _cgroup_path(entry.name),
            })
        except (OSError, PermissionError, ProcessLookupError):
            continue
        if len(rows) >= MAX_PROCESS_ROWS:
            truncated = True
            break
    return {'items': rows, 'truncated': truncated, 'limit': MAX_PROCESS_ROWS}


def snapshot(workspace=None, policy_cgroup=None, tracked_packages=()):
    """Read host and cgroup counters without changing limits or policy."""
    meminfo = _read('/proc/meminfo')
    host_cgroup = _cgroup_path(os.getpid())
    result = {
        'schema': 1,
        'monotonic_ns': time.monotonic_ns(),
        'host': {
            'meminfo': parse_meminfo(meminfo) if isinstance(meminfo, str) else meminfo,
            'psi': {},
        },
        'cgroups': {
            'launcher': _cgroup_snapshot(host_cgroup),
            'aaas_parent': _cgroup_snapshot('/user.slice/user-1000.slice/user@1000.service/aaas'),
            'session_policy': _cgroup_snapshot(str(policy_cgroup)) if policy_cgroup else None,
        },
        'processes': _processes(tracked_packages),
        'workspace': None,
    }
    for kind in ('memory', 'io', 'cpu'):
        value = _read(f'/proc/pressure/{kind}')
        result['host']['psi'][kind] = parse_psi(value) if isinstance(value, str) else value
    if workspace:
        try:
            stats = os.statvfs(workspace)
            result['workspace'] = {
                'path': str(workspace),
                'available_bytes': stats.f_bavail * stats.f_frsize,
                'total_bytes': stats.f_blocks * stats.f_frsize,
            }
        except OSError as error:
            result['workspace'] = {'path': str(workspace), 'unavailable': error.errno}
    return result


def write_snapshot(path, workspace=None, policy_cgroup=None, tracked_packages=()):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    record = snapshot(workspace=workspace, policy_cgroup=policy_cgroup,
                      tracked_packages=tracked_packages)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return record


def append_sample(path, record):
    """Append one caller-scheduled sample; caller owns the interval/cap."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'a') as stream:
        json.dump(record, stream, separators=(',', ':'))
        stream.write('\n')
