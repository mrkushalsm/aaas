#!/usr/bin/env python3
"""Probe Linux oom_score_adj write permissions with disposable processes.

The probe never targets an existing process. Each case forks a short-lived
child owned by the caller, attempts one write, reads the resulting value, and
terminates the child. Run it on the host and inside the AaaS bubblewrap user
namespace to compare capability and namespace effects.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ADJ = Path('/proc/self/oom_score_adj')
STATUS = Path('/proc/self/status')

# Android priority landmarks. Negative values require CAP_SYS_RESOURCE when
# they decrease the current value; positive values only make a task more
# killable and are always permitted to the owner.
CASES = (
    ('foreground', 0),
    ('visible', 100),
    ('cached', 900),
    ('max', 1000),
    ('decrease_one', -1),
    ('system', -900),
    ('native', -1000),
)


def read_adj(pid):
    return int(Path(f'/proc/{pid}/oom_score_adj').read_text())


def read_status(pid=os.getpid()):
    fields = {}
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        key, _, value = line.partition(':')
        fields[key] = value.strip()
    return fields


def userns_inode(pid=os.getpid()):
    return os.stat(f'/proc/{pid}/ns/user').st_ino


def capability_names(mask):
    names = []
    for number in range(64):
        if mask & (1 << number):
            names.append(f'CAP{number}')
    return names


def run_case(pid, value):
    path = Path(f'/proc/{pid}/oom_score_adj')
    before = read_adj(pid)
    try:
        path.write_text(f'{value}\n')
        error = None
    except OSError as exc:
        error = {'errno': exc.errno, 'strerror': exc.strerror}
    after = read_adj(pid)
    return {
        'requested': value,
        'before': before,
        'after': after,
        'errno': error['errno'] if error else 0,
        'error': error['strerror'] if error else None,
        'succeeded': error is None and after == value,
    }


def spawn_target():
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                               start_new_session=True)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            read_adj(process.pid)
            return process
        except FileNotFoundError:
            time.sleep(0.01)
    process.kill()
    process.wait()
    raise RuntimeError('target process did not become observable')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    status = read_status()
    effective = int(status.get('CapEff', '0'), 16)
    permitted = int(status.get('CapPrm', '0'), 16)
    report = {
        'uid': os.getuid(),
        'gid': os.getgid(),
        'pid': os.getpid(),
        'user_namespace_inode': userns_inode(),
        'supplementary_groups': os.getgroups(),
        'cap_effective_hex': f'{effective:016x}',
        'cap_permitted_hex': f'{permitted:016x}',
        'cap_effective_names': capability_names(effective),
        'has_cap_sys_resource': bool(effective & (1 << 24)),
        'host_kernel': os.uname().release,
        'proc_self_oom_score_adj': read_adj(os.getpid()),
        'cases': [],
    }
    for name, value in CASES:
        target = spawn_target()
        try:
            result = run_case(target.pid, value)
            result['name'] = name
            result['target_uid'] = os.stat(f'/proc/{target.pid}').st_uid
            result['same_user_namespace'] = userns_inode(target.pid) == report[
                'user_namespace_inode']
            report['cases'].append(result)
        finally:
            try:
                os.kill(target.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            target.wait(timeout=3)

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
