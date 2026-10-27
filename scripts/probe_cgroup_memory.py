#!/usr/bin/env python3
"""Probe the delegated AaaS cgroup v2 memory controller with bounded pressure.

Only a disposable child cgroup created inside the already delegated AaaS scope
is used. The probe moves its own short-lived generator processes, never host
services, and removes the cgroup on every exit path.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

MEMBERS = ('memory.min', 'memory.low', 'memory.high', 'memory.max',
           'memory.oom.group', 'memory.reclaim')


def read(path):
    try:
        return path.read_text().strip()
    except OSError as exc:
        return f'error: {exc.errno}: {exc.strerror}'


def read_events(group):
    values = {}
    for line in (group / 'memory.events').read_text().splitlines():
        key, _, value = line.partition(' ')
        values[key] = int(value)
    return values


def pressure(group):
    values = {}
    for line in (group / 'memory.pressure').read_text().splitlines():
        kind, _, fields = line.partition(' ')
        values[kind] = dict(item.split('=') for item in fields.split())
    return values


def snapshot(group):
    return {
        'memory_current': read(group / 'memory.current'),
        'memory_peak': read(group / 'memory.peak'),
        'memory_events': read_events(group),
        'memory_pressure': pressure(group),
    }


GENERATOR = '''\
import sys, time
time.sleep(float(sys.argv[2]))
chunks = []
size = int(sys.argv[1]) * 1024 * 1024
block = 1024 * 1024
for _ in range(size // block):
    chunk = bytearray(block)
    chunk[0::4096] = b'\\x01' * len(chunk[0::4096])
    chunks.append(chunk)
print('allocated', len(chunks), 'MiB', flush=True)
time.sleep(60)
'''


def start_generator(group, mebibytes, delay):
    process = subprocess.Popen(
        [sys.executable, '-c', GENERATOR, str(mebibytes), str(delay)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        start_new_session=True,
    )
    (group / 'cgroup.procs').write_text(f'{process.pid}\n')
    observed = Path(f'/proc/{process.pid}/cgroup').read_text().strip()
    return process, observed


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    try:
        output = process.communicate(timeout=5)[0]
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        output = process.communicate(timeout=5)[0]
    return {'returncode': process.returncode, 'output': output.strip()[-400:]}


def wait_events(group, key, minimum, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if read_events(group).get(key, 0) >= minimum:
            return True
        time.sleep(0.1)
    return False


def run_probe(scope):
    report = {
        'scope': str(scope),
        'scope_controllers': read(scope / 'cgroup.controllers').split(),
        'scope_subtree_control': read(scope / 'cgroup.subtree_control').split(),
        'scope_uid': scope.stat().st_uid,
        'probe_uid': os.getuid(),
        'host_kernel': os.uname().release,
        'controllable': {},
        'tests': {},
    }
    group = scope / f'aaas-memory-probe-{os.getpid()}'
    if group.exists():
        raise RuntimeError(f'probe cgroup already exists: {group}')
    group.mkdir()
    try:
        for name in MEMBERS:
            path = group / name
            report['controllable'][name] = path.exists() and os.access(path, os.W_OK)

        # Capability writes with harmless values.
        (group / 'memory.min').write_text('0\n')
        (group / 'memory.low').write_text('0\n')
        (group / 'memory.high').write_text('max\n')
        (group / 'memory.max').write_text('max\n')
        (group / 'memory.swap.max').write_text('0\n')
        (group / 'memory.oom.group').write_text('0\n')
        report['tests']['control_files'] = {
            'writable': True,
            'values': {name: read(group / name) for name in
                       ('memory.min', 'memory.low', 'memory.high',
                        'memory.max', 'memory.swap.max', 'memory.oom.group')},
        }

        # Test 1: bounded high-pressure throttling without OOM kill.
        baseline = snapshot(group)
        (group / 'memory.high').write_text('32M\n')
        (group / 'memory.max').write_text('256M\n')
        generator, observed = start_generator(group, 96, 0.2)
        try:
            high_seen = wait_events(group, 'high', 1, 20)
            during = snapshot(group)
        finally:
            output = stop(generator)
        report['tests']['high_pressure'] = {
            'memory_high': '32M',
            'memory_max': '256M',
            'generator_allocated_mib': 96,
            'generator_cgroup': observed,
            'high_event_observed': high_seen,
            'oom_kill_observed': during['memory_events'].get('oom_kill', 0),
            'baseline': baseline,
            'during': during,
            'generator': output,
        }

        # Test 2: hard limit in a disposable cgroup. This is a kernel OOM
        # kill, explicitly not evidence of LMKD victim selection.
        before = snapshot(group)
        (group / 'memory.high').write_text('max\n')
        (group / 'memory.max').write_text('48M\n')
        generator, observed = start_generator(group, 160, 0.2)
        try:
            oom_seen = wait_events(group, 'oom_kill', 1, 25)
            after = snapshot(group)
        finally:
            output = stop(generator)
        report['tests']['hard_limit'] = {
            'memory_max': '48M',
            'generator_allocated_mib': 160,
            'generator_cgroup': observed,
            'oom_kill_event_observed': oom_seen,
            'baseline': before,
            'after': after,
            'generator': output,
        }

        # Test 3: memory.low/min and reclaim controls remain writable after
        # the pressure events. Do not force host-wide reclaim.
        (group / 'memory.max').write_text('max\n')
        (group / 'memory.low').write_text('4M\n')
        (group / 'memory.min').write_text('244K\n')
        try:
            (group / 'memory.reclaim').write_text('1M\n')
            reclaim_error = None
        except OSError as exc:
            reclaim_error = {'errno': exc.errno, 'strerror': exc.strerror}
        report['tests']['protection_controls'] = {
            'memory_low': read(group / 'memory.low'),
            'memory_min': read(group / 'memory.min'),
            'memory_reclaim_error': reclaim_error,
        }

        # Restore permissive limits before teardown.
        (group / 'memory.high').write_text('max\n')
        (group / 'memory.max').write_text('max\n')
        (group / 'memory.low').write_text('0\n')
        (group / 'memory.min').write_text('0\n')
    finally:
        # Only remove the probe's own cgroup and only once it is empty.
        (group / 'cgroup.kill').write_text('1\n')
        for _ in range(50):
            if not (group / 'cgroup.procs').read_text().strip():
                break
            time.sleep(0.1)
        try:
            group.rmdir()
            report['removed'] = True
        except OSError as exc:
            report['removed'] = False
            report['remove_error'] = {'errno': exc.errno, 'strerror': exc.strerror}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', type=Path,
                        default=Path('/sys/fs/cgroup/user.slice/user-1000.slice/'
                                     'user@1000.service/aaas'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not (args.scope / 'cgroup.controllers').is_file():
        parser.error(f'not a cgroup v2 directory: {args.scope}')
    report = run_probe(args.scope)
    text = json.dumps(report, indent=2, sort_keys=True) + '\n'
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
