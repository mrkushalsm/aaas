#!/usr/bin/env python3
"""Check user-scoped cgroup v2 delegation without changing global controls."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def current_cgroup(contents):
    matches = [line[3:] for line in contents.splitlines() if line.startswith('0::/')]
    if len(matches) != 1 or '..' in Path(matches[0]).parts:
        raise ValueError('expected one absolute cgroup v2 path')
    return matches[0]


def probe_inside():
    group = current_cgroup(Path('/proc/self/cgroup').read_text())
    parent = Path('/sys/fs/cgroup') / group.lstrip('/')
    child = parent / f'aaas-delegation-probe-{os.getpid()}'
    controllers = sorted((parent / 'cgroup.controllers').read_text().split())
    child.mkdir()
    process = None
    try:
        process = subprocess.Popen(['/usr/bin/sleep', '10'])
        (child / 'cgroup.procs').write_text(f'{process.pid}\n')
        observed = current_cgroup(Path(f'/proc/{process.pid}/cgroup').read_text())
        moved = observed == f'{group}/{child.name}'
        print(json.dumps({'delegated_group': group, 'controllers': controllers,
                          'child_created': True, 'process_moved': moved}, sort_keys=True))
        return 0 if moved else 1
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=3)
        child.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside-scope', action='store_true')
    args = parser.parse_args()
    if args.inside_scope:
        return probe_inside()
    command = ['systemd-run', '--user', '--scope', '--quiet', '-p', 'Delegate=yes',
               sys.executable, str(Path(__file__).resolve()), '--inside-scope']
    return subprocess.run(command, check=False, timeout=15).returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f'cgroup delegation probe: {exc}', file=sys.stderr)
        sys.exit(2)
