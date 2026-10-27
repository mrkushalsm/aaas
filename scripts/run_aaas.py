#!/usr/bin/env python3
"""Run the current Android 16 Settings diagnostic as a foreground session.

The M1B.8 framework runner has inherited, uncommitted experiments. This
launcher transforms a hash-checked copy rather than editing that runner.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = Path('/run/media/mrkus/Homework/aaas-workspace')
TMP = WORKSPACE / 'tmp'
RUNNER = ROOT / 'scripts/test_zygote_startup.py'
PRESENTER = ROOT / 'experiments/m1a/build/wayland-host-presenter'
RUNNER_SHA256 = 'd6361e97933ab2dfd18f544ac3ed00100b984e31cad24d2773ad9426c00621f7'
VULKAN_SHA256 = '1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181'
LMKD_DIAGNOSTIC_SHA256 = '9780759ba36e50d061064f05c77520809f3291edad6a43a1495e9d91f21d54bd'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError(f'runner anchor count {source.count(old)}: {old[:80]!r}')
    return source.replace(old, new, 1)


def make_session_runner(session):
    if sha256(RUNNER) != RUNNER_SHA256:
        raise RuntimeError('inherited runtime runner changed; review the session transformation')
    source = RUNNER.read_text()
    source = replace_once(source, '    ipc_dir = tmp_dir / "aaas_ipc"',
                          '    ipc_dir = Path(os.environ["AAAS_SESSION_IPC"])')
    source = replace_once(source, '    ipc_dir.chmod(0o777)', '    ipc_dir.chmod(0o711)')
    source = replace_once(
        source,
        '    overlay_libvulkan = tmp_dir / "libvulkan.so"',
        '    lmkd_overlay = Path(os.environ["AAAS_LMKD_OVERLAY"])\n'
        '    lmkd_bind = f\'  --ro-bind "{lmkd_overlay}" /system/bin/lmkd \\\\\\n\'\n'
        '    overlay_libvulkan = tmp_dir / "libvulkan.so"',
    )
    source = replace_once(
        source, '    overlay_angle = tmp_dir / "libGLESv2_angle.so"',
        '    session_status = Path(os.environ["AAAS_SESSION_STATUS"])\n'
        '    status_bind = f\'  --bind "{session_status}" /aaas_session_status \\\\\\n\'\n'
        '    session_logcat = Path(os.environ["AAAS_SESSION_LOGCAT"])\n'
        '    logcat_bind = f\'  --bind "{session_logcat}" /aaas_session_logcat \\\\\\n\'\n'
        '    overlay_angle = tmp_dir / "libGLESv2_angle.so"',
    )
    source = replace_once(source, '{mapper_bind}{allocator_bind}{composer_bind}{vulkan_bind}',
                          '{lmkd_bind}{status_bind}{logcat_bind}{mapper_bind}{allocator_bind}{composer_bind}{vulkan_bind}')
    source = replace_once(
        source,
        '    /system/bin/toybox ifconfig lo 127.0.0.1 up 2>/dev/null || true',
        '    /system/bin/logcat -b all -v threadtime > /aaas_session_logcat 2>&1 &\n'
        '    /system/bin/toybox ifconfig lo 127.0.0.1 up 2>/dev/null || true',
    )
    source = replace_once(
        source,
        '    /system/bin/toybox sleep 3\n    if [ "{settings_sigquit}"',
        '    /system/bin/toybox sleep 3\n'
        '    if [ "$(/system/bin/getprop sys.boot_completed)" != "1" ] || '
        '[ -z "$(/system/bin/toybox pidof com.android.settings)" ]; then\n'
        '      echo FAILED > /aaas_session_status\n'
        '      exit 1\n'
        '    fi\n'
        '    echo RUNNING > /aaas_session_status\n'
        '    while [ "$(/system/bin/getprop sys.boot_completed)" = "1" ] && '
        '[ -n "$(/system/bin/toybox pidof system_server)" ] && '
        '[ -n "$(/system/bin/toybox pidof com.android.settings)" ]; do\n'
        '      /system/bin/toybox sleep 2\n'
        '    done\n'
        '    echo FAILED > /aaas_session_status\n'
        '    exit 1\n'
        '    if [ "{settings_sigquit}"',
    )
    source = replace_once(source, '                         start_new_session=True)',
                          '                         start_new_session=False)')
    source = replace_once(source, 'p.communicate(timeout=140)', 'p.communicate(timeout=None)')
    output = session / 'runner.py'
    output.write_text(source)
    output.chmod(0o700)
    return output


def verify_requirements():
    check = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/android_workspace.py'),
         '--workspace', str(WORKSPACE), 'check'],
        capture_output=True, text=True,
    )
    if check.returncode:
        raise RuntimeError(check.stdout + check.stderr)
    mount = json.loads(check.stdout)['mount']
    if mount['source'] != '/dev/sda2' or mount['filesystem'] != 'ntfs3':
        raise RuntimeError(f'unexpected workspace mount: {mount}')
    if not PRESENTER.is_file():
        raise RuntimeError(f'build the presenter first: {PRESENTER}')
    required = {
        'AAAS_VULKAN_OVERLAY': ('m1b83_sampling_lock_vulkan.so', VULKAN_SHA256),
        'AAAS_LMKD_OVERLAY': ('m1b83_lmkd_vmstats_diagnostic', LMKD_DIAGNOSTIC_SHA256),
        'AAAS_RANGING_JAR_OVERLAY': ('m1b8_service-ranging.rebuilt2.jar', None),
        'AAAS_NETWORKSTATS_LIB_OVERLAY': ('m1b81_networkstats_uid_diagnostic.so', None),
        'AAAS_MEMINFO_LIB_OVERLAY': ('m1b81_meminfo_gpu_diagnostic.so', None),
        'AAAS_SERVICES_JAR_OVERLAY': ('m1b8_services_battery_mobile_diagnostic.jar', None),
        'AAAS_KEYSTORE_SID_PROBE': ('m1b81_libkeystore_sid_uid1000_rebuild.so', None),
        'AAAS_HWSM_SID_PROBE': ('m1b81_libhwsm_sid_probe_rebuilt.so', None),
    }
    paths = {}
    for key, (name, expected_hash) in required.items():
        path = TMP / name
        if not path.is_file():
            raise RuntimeError(f'missing required diagnostic overlay: {path}')
        if expected_hash and sha256(path) != expected_hash:
            raise RuntimeError(f'overlay checksum changed: {path}')
        paths[key] = str(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--startup-timeout', type=int, default=90)
    args = parser.parse_args()
    if args.startup_timeout < 1:
        parser.error('startup timeout must be positive')
    paths = verify_requirements()
    lock_fd = os.open(TMP / '.aaas_session.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        print('AaaS: another foreground session is already running', file=sys.stderr)
        return 2
    stop = False

    def request_stop(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    session = Path(tempfile.mkdtemp(prefix='m1b84_session_', dir=TMP))
    session.chmod(0o700)
    ipc = session / 'ipc'
    ipc.mkdir(mode=0o711)
    status = session / 'status'
    status.write_text('STARTING\n')
    status.chmod(0o666)
    logcat = session / 'logcat.log'
    logcat.touch()
    logcat.chmod(0o666)
    runner = make_session_runner(session)
    prefix = f'm1b84_session_{os.getpid()}_'
    env = os.environ.copy()
    env.update(paths)
    env.update(AAAS_LOG_PREFIX=prefix, AAAS_BOOTANIM='0',
               AAAS_BOOT_WAIT=str(args.startup_timeout),
               AAAS_SESSION_IPC=str(ipc), AAAS_SESSION_STATUS=str(status),
               AAAS_SESSION_LOGCAT=str(logcat))
    presenter = android = None
    state = 'CREATED'

    def transition(new_state):
        nonlocal state
        state = new_state
        print(f'AaaS: {new_state} ({session})', flush=True)
        with (session / 'state.jsonl').open('a') as stream:
            stream.write(json.dumps({'state': state, 'monotonic_ns': time.monotonic_ns()}) + '\n')

    try:
        transition('PREPARING')
        with (session / 'presenter.log').open('wb') as presenter_log, (session / 'android.log').open('wb') as android_log:
            transition('STARTING_PRESENTER')
            presenter = subprocess.Popen(
                [str(PRESENTER), '--socket', str(ipc / 'wayland.sock'), '--exit-on-close'],
                stdout=presenter_log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            deadline = time.monotonic() + 10
            while not (ipc / 'wayland.sock').exists():
                if presenter.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('presenter did not start')
                time.sleep(.1)
            transition('STARTING_ANDROID')
            android = subprocess.Popen([sys.executable, str(runner)], env=env,
                                       stdout=android_log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            transition('WAITING_FOR_FRAMEWORK')
            deadline = time.monotonic() + args.startup_timeout + 20
            while not stop:
                if presenter.poll() is not None:
                    raise RuntimeError('presenter exited before Settings became ready')
                if android.poll() is not None:
                    raise RuntimeError('Android exited before Settings became ready')
                if status.read_text().strip() == 'RUNNING':
                    transition('RUNNING')
                    print('Settings process started. Close its window or press Ctrl+C to stop.', flush=True)
                    break
                if status.read_text().strip() == 'FAILED' or time.monotonic() >= deadline:
                    raise RuntimeError('Android Settings did not become ready')
                time.sleep(.25)
            while not stop and state == 'RUNNING':
                if presenter.poll() is not None:
                    print('AaaS: presenter exited; stopping Android', flush=True)
                    break
                if android.poll() is not None or status.read_text().strip() == 'FAILED':
                    raise RuntimeError('Android runtime failed')
                time.sleep(.25)
        transition('STOPPING')
        return 0
    except Exception as error:
        print(f'AaaS: {error}', file=sys.stderr, flush=True)
        transition('FAILED')
        return 1
    finally:
        for process in (android, presenter):
            if process is None:
                continue
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=8)
        if state != 'FAILED':
            transition('STOPPED')
        print(f'AaaS logs: {session}', flush=True)
        os.close(lock_fd)


if __name__ == '__main__':
    sys.exit(main())
