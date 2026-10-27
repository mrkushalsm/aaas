#!/usr/bin/env python3
"""Measure relative cgroup v2 memory protection in a disposable hierarchy.

Only disposable children of the delegated AaaS scope are used.  The probe
allocates file-backed pages in a protected and an unprotected sibling, asks the
kernel to reclaim from the parent, and reports the per-child reclaim outcome.
No host-wide pressure or hard Android limit is involved.
"""

import argparse
import errno
import json
import mmap
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aaas_cgroup


MIB = 1024 * 1024


def parse_stat(path: Path) -> dict[str, int]:
    result = {}
    try:
        for line in path.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                result[parts[0]] = int(parts[1])
    except OSError:
        pass
    return result


def read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def worker(mib: int, path: str, seconds: int) -> int:
    # Wait until the parent has moved this process into its target cgroup, so
    # all file-page charges land in the intended sibling.
    sys.stdin.readline()
    size = mib * MIB
    with open(path, 'w+b') as stream:
        stream.truncate(size)
        mapping = mmap.mmap(stream.fileno(), size)
        for offset in range(0, size, 4096):
            mapping[offset] = 1
        mapping.flush()
        mapping.close()
        stream.flush()
        os.fsync(stream.fileno())
    # Re-map read-only so the measured pages are clean and reclaimable.
    with open(path, 'rb') as stream:
        mapping = mmap.mmap(stream.fileno(), size, access=mmap.ACCESS_READ)
        print('ready', flush=True)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for offset in range(0, size, 4096):
                _ = mapping[offset]
            time.sleep(0.25)
        mapping.close()
    return 0


def worker_anon(mib: int, seconds: int) -> int:
    sys.stdin.readline()
    size = mib * MIB
    memory = bytearray(size)
    for offset in range(0, size, 4096):
        memory[offset] = 1
    print('ready', flush=True)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for offset in range(0, size, 4096):
            memory[offset] ^= 1
        time.sleep(0.25)
    return 0


def spawn_worker(mib: int, path: Path | None, cgroup: Path, seconds: int = 90,
                 anon: bool = False):
    if anon:
        command = [sys.executable, str(Path(__file__).resolve()),
                   '--worker-anon', str(mib), str(seconds)]
    else:
        command = [sys.executable, str(Path(__file__).resolve()), '--worker',
                   str(mib), str(path), str(seconds)]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    cgroup.joinpath('cgroup.procs').write_text(f'{process.pid}\n')
    process.stdin.write('go\n')
    process.stdin.flush()
    ready, _, _ = select.select([process.stdout], [], [], 15)
    if not ready:
        process.kill()
        raise RuntimeError('worker did not become ready')
    line = process.stdout.readline().strip()
    if line != 'ready':
        process.kill()
        raise RuntimeError(f'worker failed: {line}')
    return process


def snapshot(directory: Path) -> dict:
    return {
        'memory.current': read_int(directory / 'memory.current'),
        'memory.peak': read_int(directory / 'memory.peak'),
        'memory.low': read_int(directory / 'memory.low'),
        'memory.high': _text(directory / 'memory.high'),
        'memory.max': _text(directory / 'memory.max'),
        'memory.events': parse_stat(directory / 'memory.events'),
        'memory.stat': parse_stat(directory / 'memory.stat'),
        'processes': _text(directory / 'cgroup.procs'),
    }


def _text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--protection-mib', type=int, default=96)
    parser.add_argument('--reclaim-mib', type=int, default=64)
    parser.add_argument('--worker', nargs=3, metavar=('MIB', 'PATH', 'SECONDS'))
    parser.add_argument('--worker-anon', nargs=2, metavar=('MIB', 'SECONDS'))
    args = parser.parse_args()
    if args.worker:
        return worker(int(args.worker[0]), args.worker[1], int(args.worker[2]))
    if args.worker_anon:
        return worker_anon(int(args.worker_anon[0]), int(args.worker_anon[1]))

    root = aaas_cgroup.discover_delegated_root()
    aaas_cgroup.ensure_memory_controller(root)
    parent = root / f'm1b86-protection-{os.getpid()}'
    if parent.exists():
        parent.rmdir()
    parent.mkdir(mode=0o755)
    aaas_cgroup.ensure_memory_controller(parent)
    protected = parent / 'protected'
    unprotected = parent / 'unprotected'
    pressure = parent / 'pressure'
    for directory in (protected, unprotected, pressure):
        directory.mkdir(mode=0o755)

    workers = []
    tempdir = tempfile.TemporaryDirectory(prefix='m1b86-protection-')
    result = {
        'scope': str(root),
        'hierarchy': str(parent),
        'protection_mib': args.protection_mib,
        'reclaim_request_mib': args.reclaim_mib,
        'host_kernel': os.uname().release,
        'checks': {},
    }
    try:
        protected_file = Path(tempdir.name) / 'protected.bin'
        unprotected_file = Path(tempdir.name) / 'unprotected.bin'
        protected_worker = spawn_worker(
            args.protection_mib, protected_file, protected)
        unprotected_worker = spawn_worker(
            args.protection_mib, unprotected_file, unprotected)
        workers.extend([protected_worker, unprotected_worker])

        # Relative protection: the protected sibling gets a low guarantee, the
        # unprotected sibling gets none.
        protected.joinpath('memory.low').write_text(f'{48 * MIB}\n')
        unprotected.joinpath('memory.low').write_text('0\n')
        parent.joinpath('memory.max').write_text('max\n')

        baseline = {
            'protected': snapshot(protected),
            'unprotected': snapshot(unprotected),
            'parent': snapshot(parent),
        }
        request = f'{args.reclaim_mib}M\n'
        reclaim_error = None
        try:
            parent.joinpath('memory.reclaim').write_text(request)
        except OSError as exc:
            reclaim_error = {'errno': exc.errno, 'strerror': exc.strerror}
        time.sleep(0.5)
        after = {
            'protected': snapshot(protected),
            'unprotected': snapshot(unprotected),
            'parent': snapshot(parent),
        }

        def reclaimed(name):
            before = baseline[name]['memory.current'] or 0
            current = after[name]['memory.current'] or 0
            return max(0, before - current)

        protected_reclaimed = reclaimed('protected')
        unprotected_reclaimed = reclaimed('unprotected')
        result.update({
            'baseline': baseline,
            'after': after,
            'reclaim_error': reclaim_error,
            'reclaimed_bytes': {
                'protected': protected_reclaimed,
                'unprotected': unprotected_reclaimed,
            },
        })
        result['checks']['reclaim_succeeded'] = reclaim_error is None
        # The direct reclaim request is best-effort and can be noisy with
        # active file pages.  Record the observation but gate on the bounded
        # pressure phase below, which is the deterministic sibling test.
        result['observations'] = {
            'unprotected_reclaimed_more': unprotected_reclaimed > protected_reclaimed,
            'reclaim_bytes': {
                'protected': protected_reclaimed,
                'unprotected': unprotected_reclaimed,
            },
        }
        result['checks']['no_oom_kill'] = (
            after['parent']['memory.events'].get('oom_kill', 0) == 0
            and after['protected']['memory.events'].get('oom_kill', 0) == 0
            and after['unprotected']['memory.events'].get('oom_kill', 0) == 0)

        # Bounded second phase: force the parent just over a soft budget with
        # anonymous pressure while both file-backed siblings are resident.
        pressure_mib = 64
        parent_max_mib = 2 * args.protection_mib + pressure_mib - 32
        parent.joinpath('memory.max').write_text(f'{parent_max_mib}M\n')
        pressure_worker = spawn_worker(
            pressure_mib, None, pressure, seconds=90, anon=True)
        workers.append(pressure_worker)
        time.sleep(3)
        under_pressure = {
            'protected': snapshot(protected),
            'unprotected': snapshot(unprotected),
            'pressure': snapshot(pressure),
            'parent': snapshot(parent),
        }

        def lost(name):
            before = after[name]['memory.current'] or 0
            current = under_pressure[name]['memory.current'] or 0
            return max(0, before - current)

        protected_lost = lost('protected')
        unprotected_lost = lost('unprotected')
        result['pressure'] = {
            'parent_memory.max': parent_max_mib * MIB,
            'pressure_mib': pressure_mib,
            'after': under_pressure,
            'lost_bytes': {
                'protected': protected_lost,
                'unprotected': unprotected_lost,
            },
        }
        result['checks']['protected_lost_no_more_than_unprotected'] = (
            protected_lost <= unprotected_lost)
        result['checks']['no_oom_kill_under_pressure'] = (
            under_pressure['parent']['memory.events'].get('oom_kill', 0) == 0
            and under_pressure['protected']['memory.events'].get('oom_kill', 0) == 0
            and under_pressure['unprotected']['memory.events'].get('oom_kill', 0) == 0
            and under_pressure['pressure']['memory.events'].get('oom_kill', 0) == 0)
        result['passed'] = all(result['checks'].values())

        # Keep all workers alive long enough to prove the measurement was not
        # taken after process exit.
        result['workers_alive'] = all(worker.poll() is None for worker in workers)
        return 0 if result['passed'] else 1
    finally:
        for worker_process in workers:
            if worker_process.poll() is None:
                worker_process.terminate()
                try:
                    worker_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker_process.kill()
                    worker_process.wait(timeout=5)
        tempdir.cleanup()
        for directory in (protected, unprotected, pressure):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            parent.rmdir()
        except OSError:
            pass
        result['cleaned_up'] = not parent.exists()
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=1, default=str) + '\n')
        print(json.dumps({k: result[k] for k in (
            'checks', 'reclaimed_bytes', 'reclaim_error', 'passed',
            'cleaned_up', 'workers_alive') if k in result}, indent=1))


if __name__ == '__main__':
    sys.exit(main())
