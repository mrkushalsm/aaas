#!/usr/bin/env python3
"""Exercise LMKD victim selection with bounded, cgroup-local PSI pressure.

This is an isolated test harness. It starts a second LMKD process with a
private control socket and a test-only property shim that enables the low-RAM
kill path. Three disposable processes are registered at different priorities,
then pressure is generated only inside a disposable child of the delegated
AaaS cgroup. The production Android session must not be running.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = Path('/run/media/mrkus/Aaas/aaas-workspace')
TMP = WORKSPACE / 'tmp'
SCOPE = Path('/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/aaas')
LMKD = TMP / 'm1b85_lmkd_source_built'
SHIM_SRC = ROOT / 'experiments/m1b85/lmkd_test_props.c'
TEST_DIR = TMP / 'm1b85_lmkd_selection'

LMK_PROCPRIO = 1
LMK_GETKILLCNT = 4
LMK_SUBSCRIBE = 5
LMK_PROCKILL = 6
LMK_ASYNC_EVENT_KILL = 0
PROC_TYPE_APP = 0

GENERATOR = '''\
import os, sys, time
end = time.time() + float(sys.argv[1])
path = sys.argv[2]
chunks = []
block = b"\\x01" * (1024 * 1024)
file = open(path, "wb", buffering=0)
while time.time() < end:
    # Anonymous churn raises the stall; page-cache churn moves global scan and
    # refault counters so real LMKD's reclaim gate is satisfied.
    chunk = bytearray(16 * 1024 * 1024)
    chunk[0::4096] = b"\\x01" * len(chunk[0::4096])
    chunks.append(chunk)
    if len(chunks) > 1:
        chunks.pop(0)
    file.seek(0)
    for _ in range(96):
        file.write(block)
    os.fsync(file.fileno())
    file.seek(0)
    while file.read(1024 * 1024):
        pass
file.close()
os.unlink(path)
'''


def shim_path():
    return TEST_DIR / 'libaaas_lmkd_test_props.so'


def build_shim():
    bionic = WORKSPACE / 'sources/bionic-android16'
    rootfs = WORKSPACE / 'rootfs_m1b1'
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        'clang', '-target', 'x86_64-linux-android', '-shared', '-fPIC',
        '-nostdlib', '-D__BIONIC__', '-D__ANDROID_API__=35',
        f'-isystem{bionic}/libc/include',
        f'-isystem{bionic}/libc/kernel/android/uapi',
        f'-isystem{bionic}/libc/kernel/uapi',
        f'-isystem{bionic}/libc/kernel/uapi/asm-x86',
        f'-L{rootfs}/system/lib64',
        f'-L{rootfs}/system/lib64/bootstrap',
        '-lc', '-o', str(shim_path()), str(SHIM_SRC),
    ]
    subprocess.run(command, check=True)
    return shim_path()


def start_lmkd(socket_path, log_path):
    rootfs = WORKSPACE / 'rootfs_m1b1'
    inside_dir = '/data/lmkd_probe'
    inside_socket = f'{inside_dir}/{socket_path.name}'
    command = [
        'bwrap',
        '--ro-bind', str(rootfs), '/',
        '--ro-bind', str(LMKD), '/system/bin/lmkd',
        '--tmpfs', '/data',
        '--bind', str(TEST_DIR), inside_dir,
        '--dev', '/dev',
        '--proc', '/proc',
        '--cap-add', 'CAP_SYS_RESOURCE',
        '--setenv', 'AAAS_TEST_LMKD_SOCKET', inside_socket,
        '--setenv', 'LD_PRELOAD', f'{inside_dir}/{shim_path().name}',
        '/system/bin/lmkd',
    ]
    log = log_path.open('wb')
    process = subprocess.Popen(command, stdout=log,
                               stderr=subprocess.STDOUT, start_new_session=True)
    return process, log


def send_int_packet(sock, values):
    import struct
    sock.send(struct.pack(f'!{len(values)}i', *values))


def recv_int_packet(sock, timeout):
    import struct
    sock.settimeout(timeout)
    data = sock.recv(4096)
    if len(data) % 4:
        raise RuntimeError(f'malformed LMKD reply: {data!r}')
    return list(struct.unpack(f'!{len(data) // 4}i', data))


def lmkd_pid():
    """Return the PID of the disposable LMKD process (argv[0] is the overlay)."""
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / 'cmdline').read_bytes().split(b'\0')
        except OSError:
            continue
        if command and command[0] == b'/system/bin/lmkd':
            return int(entry.name)
    return None


def process_credentials(pid):
    if pid is None:
        return None
    status = {}
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        key, _, value = line.partition(':')
        status[key] = value.strip()
    return {
        'pid': pid,
        'uid': os.stat(f'/proc/{pid}').st_uid,
        'cap_effective_hex': status.get('CapEff'),
        'cap_permitted_hex': status.get('CapPrm'),
        'has_cap_sys_resource': bool(
            int(status.get('CapEff', '0'), 16) & (1 << 24)),
        'oom_score_adj': int(Path(f'/proc/{pid}/oom_score_adj').read_text()),
    }


def register(sock, pid, uid, oomadj):
    send_int_packet(sock, [LMK_PROCPRIO, pid, uid, oomadj, PROC_TYPE_APP])
    time.sleep(0.1)


def subscribe(sock):
    send_int_packet(sock, [LMK_SUBSCRIBE, LMK_ASYNC_EVENT_KILL])
    time.sleep(0.1)


def kill_count(sock, low=-1000, high=1000):
    send_int_packet(sock, [LMK_GETKILLCNT, low, high])
    reply = recv_int_packet(sock, 3)
    if not reply or reply[0] != LMK_GETKILLCNT:
        raise RuntimeError(f'unexpected LMK_GETKILLCNT reply: {reply}')
    return reply[1]


def parse_events_text(text):
    values = {}
    for line in text.splitlines():
        key, _, value = line.partition(' ')
        values[key] = int(value)
    return values


def read_events(group):
    return parse_events_text((group / 'memory.events').read_text())


def parse_pressure_text(text):
    values = {}
    for line in text.splitlines():
        kind, _, fields = line.partition(' ')
        values[kind] = {}
        for field in fields.split():
            key, _, value = field.partition('=')
            values[kind][key] = float(value) if '.' in value else int(value)
    return values


def read_pressure():
    return parse_pressure_text(Path('/proc/pressure/memory').read_text())


def spawn_target(delay=0.0):
    process = subprocess.Popen(
        [sys.executable, '-c', 'import time; time.sleep(60)'],
        start_new_session=True,
    )
    if delay:
        time.sleep(delay)
    return process


def start_pressure(group, seconds=14):
    churn = Path('/var/tmp') / f'aaas-lmkd-selection-{os.getpid()}.bin'
    generator = subprocess.Popen(
        [sys.executable, '-c', GENERATOR, str(seconds), str(churn)],
        start_new_session=True)
    (group / 'cgroup.procs').write_text(f'{generator.pid}\n')
    return generator


def stop_process(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)


def run_round(sock, group, priorities, round_name):
    targets = []
    for name, oomadj in priorities:
        process = spawn_target()
        register(sock, process.pid, os.getuid(), oomadj)
        observed = int(Path(f'/proc/{process.pid}/oom_score_adj').read_text())
        targets.append({'name': name, 'pid': process.pid, 'requested': oomadj,
                        'observed': observed, 'process': process})

    before_pressure = read_pressure()
    before_events = read_events(group)
    kills_before = kill_count(sock)
    generator = start_pressure(group)
    killed = None
    deadline = time.monotonic() + 25
    try:
        while time.monotonic() < deadline:
            try:
                packet = recv_int_packet(sock, 0.5)
            except socket.timeout:
                if all(t['process'].poll() is not None for t in targets):
                    break
                continue
            if packet and packet[0] == LMK_PROCKILL:
                killed = {'pid': packet[1], 'uid': packet[2], 'rss_kb': packet[3]}
                break
    finally:
        stop_process(generator)
    after_pressure = read_pressure()
    after_events = read_events(group)
    kills_after = kill_count(sock)
    for target in targets:
        target['alive_after'] = target['process'].poll() is None
        if target['process'].poll() is None:
            stop_process(target['process'])
        else:
            target['process'].wait(timeout=5)

    expected = max(targets, key=lambda item: item['requested'])
    killed_pid = killed['pid'] if killed else None
    killed_target = next((t['name'] for t in targets if t['pid'] == killed_pid), None)
    checks = {
        'priorities_written': all(t['observed'] == t['requested'] for t in targets),
        'kill_notification_received': killed is not None,
        'highest_priority_killed': killed_pid == expected['pid'],
        'kernel_oom_absent': after_events['oom_kill'] == before_events['oom_kill']
                             and after_events['oom_group_kill'] == before_events['oom_group_kill'],
        'only_one_target_killed': sum(not t['alive_after'] for t in targets) == 1,
    }
    return {
        'round': round_name,
        'targets': [{key: value for key, value in target.items() if key != 'process'}
                    for target in targets],
        'expected_killed_pid': expected['pid'],
        'killed_name': killed_target,
        'killed_notification': killed,
        'kill_count_before': kills_before,
        'kill_count_after': kills_after,
        'pressure_total_before': {k: v['total'] for k, v in before_pressure.items()},
        'pressure_total_after': {k: v['total'] for k, v in after_pressure.items()},
        'memory_events_before': before_events,
        'memory_events_after': after_events,
        'checks': checks,
        'passed': all(checks.values()),
    }


def run_isolated_round(group, priorities, round_name, round_id):
    """Run one priority set against a fresh LMKD process.

    A fresh daemon keeps the PSI monitor state deterministic: the initial
    event is certain to pass LMKD's global reclaim gate, so the test measures
    victim ordering rather than stale daemon counters.
    """
    socket_path = TEST_DIR / f'lmkd-{os.getpid()}-{round_id}.sock'
    socket_path.unlink(missing_ok=True)
    lmkd_log = TEST_DIR / f'lmkd-{os.getpid()}-{round_id}.log'
    process = client = log = None
    try:
        process, log = start_lmkd(socket_path, lmkd_log)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                client.connect(str(socket_path))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if process.poll() is not None:
                    raise RuntimeError('isolated LMKD exited during startup')
                time.sleep(0.1)
        if client is None:
            raise RuntimeError('isolated LMKD did not accept the control socket')
        credentials = process_credentials(lmkd_pid())
        subscribe(client)
        result = run_round(client, group, priorities, round_name)
        result['lmkd_process'] = credentials
        result['lmkd_log_tail'] = lmkd_log.read_text(errors='replace').splitlines()[-40:]
        return result
    finally:
        if client is not None:
            client.close()
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        deadline = time.monotonic() + 3
        while lmkd_pid() is not None and time.monotonic() < deadline:
            time.sleep(0.1)
        if lmkd_pid() is not None:
            try:
                os.kill(lmkd_pid(), signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(0.2)
        socket_path.unlink(missing_ok=True)
        if log is not None:
            log.close()


def wait_for_pressure_to_subside(timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        sample = read_pressure()
        if sample['some']['avg10'] < 1.0 and sample['full']['avg10'] < 1.0:
            return True
        time.sleep(0.5)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'results/m1b85/lmkd_selection.json')
    parser.add_argument('--rebuild-shim', action='store_true')
    args = parser.parse_args()

    if not LMKD.is_file():
        parser.error(f'missing source-built LMKD: {LMKD}')
    if subprocess.run(['pgrep', '-x', 'lmkd'], capture_output=True).returncode == 0:
        parser.error('an lmkd process is already running; stop the AaaS session first')
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'systemd-oomd']).returncode == 0:
        parser.error('systemd-oomd is active; refusing to generate pressure')

    if args.rebuild_shim or not shim_path().is_file():
        build_shim()

    TEST_DIR.mkdir(parents=True, exist_ok=True)
    group = SCOPE / f'aaas-lmkd-selection-{os.getpid()}'
    group.mkdir()
    (group / 'memory.swap.max').write_text('0\n')
    (group / 'memory.high').write_text('8M\n')
    (group / 'memory.max').write_text('128M\n')
    (group / 'memory.oom.group').write_text('0\n')

    report = {
        'lmkd_binary': str(LMKD),
        'lmkd_sha256': subprocess.check_output(['sha256sum', str(LMKD)], text=True).split()[0],
        'shim': str(shim_path()),
        'shim_sha256': subprocess.check_output(['sha256sum', str(shim_path())], text=True).split()[0],
        'scope': str(SCOPE),
        'host_kernel': os.uname().release,
        'cgroup_limits': {
            'memory.swap.max': '0',
            'memory.high': '8M',
            'memory.max': '128M',
            'memory.oom.group': '0',
        },
        'test_only_knobs': {
            'ro.config.low_ram': 1,
            'ro.config.per_app_memcg': 0,
            'persist.device_config.lmkd_native.debug': 1,
            'ro.lmk.psi_complete_stall_ms': 20,
            'rationale': ('Real LMKD selection code runs unchanged; the complete '
                          'stall threshold is lowered so bounded cgroup PSI reaches '
                          'the kill decision without host-wide pressure.'),
        },
        'rounds': [],
        'checks': {},
    }
    try:
        report['rounds'].append(run_isolated_round(
            group, [('cached', 900), ('service', 500), ('visible', 100)],
            'highest_priority_value_is_killed_first', 'r1'))
        report['pressure_subsided_between_rounds'] = wait_for_pressure_to_subside()
        report['rounds'].append(run_isolated_round(
            group, [('background', 300), ('perceptible', 200),
                    ('foreground', 100)],
            'second_priority_set', 'r2'))
    finally:
        (group / 'cgroup.kill').write_text('1\n')
        for _ in range(50):
            if not (group / 'cgroup.procs').read_text().strip():
                break
            time.sleep(0.1)
        try:
            group.rmdir()
            report['probe_cgroup_removed'] = True
        except OSError as exc:
            report['probe_cgroup_removed'] = False
            report['probe_cgroup_error'] = str(exc)
        for leftover in Path('/var/tmp').glob('aaas-lmkd-selection-*.bin'):
            leftover.unlink(missing_ok=True)

    lmkd_processes = [r['lmkd_process'] for r in report['rounds']
                      if r.get('lmkd_process') is not None]
    rounds_passed = bool(report['rounds']) and all(r['passed'] for r in report['rounds'])
    report['checks'] = {
        'both_rounds_started_lmkd': len(lmkd_processes) == len(report['rounds']),
        'cap_sys_resource_effective': all(
            p['has_cap_sys_resource'] for p in lmkd_processes),
        'rounds_passed': rounds_passed,
        'probe_cgroup_removed': report.get('probe_cgroup_removed', False),
        'no_lmkd_left_running': subprocess.run(
            ['pgrep', '-x', 'lmkd'], capture_output=True).returncode != 0,
    }
    report['passed'] = all(report['checks'].values())
    text = json.dumps(report, indent=2, sort_keys=True) + '\n'
    print(text)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
