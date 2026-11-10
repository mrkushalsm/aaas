#!/usr/bin/env python3
"""systemd --user adapter for the persistent AaaS development runtime.

The current runtime requires a first Android task to establish its virtual
display control loop. The service uses Settings as a temporary bootstrap task,
then closes its window once Android and the app manager are ready. This leaves
the Android framework warm with no app presenter or app window.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import aaas_config
import aaas_control


def _socket_for(workspace: Path):
    for path in aaas_control.socket_candidates(workspace / 'tmp'):
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.settimeout(1)
            probe.connect(str(path))
            probe.close()
            return path
        except OSError:
            try:
                probe.close()
            except UnboundLocalError:
                pass
    return None


def _request(path: Path, op: str, slot: int | None = None):
    request = {'op': op}
    if slot is not None:
        request['slot'] = slot
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(30)
        client.connect(str(path))
        client.sendall(json.dumps(request, separators=(',', ':')).encode() + b'\n')
        response = bytearray()
        while b'\n' not in response and len(response) <= 4096:
            chunk = client.recv(1024)
            if not chunk:
                break
            response.extend(chunk)
    if len(response) > 4096:
        raise RuntimeError('AaaS control response exceeded its size bound')
    return json.loads(bytes(response).split(b'\n', 1)[0])


def _runner_command(runner: Path, config):
    """Build the persistent runner command from resolved user features."""
    command = [sys.executable, str(runner), '--experimental-virtual-display',
               '--app', 'com.android.settings', '--max-apps', '16',
               '--idle-timeout-seconds', '3600']
    if config.audio:
        command.append('--audio')
    # A package may have been installed with an ARM64 primary ABI during an
    # accepted M3 session.  Keep the Native Bridge enabled for the persistent
    # runtime whenever the configured workspace carries the verified M3
    # bundle; without it Android tries the absent secondary zygote and silently
    # closes those activities before they can produce a frame.
    bridge = os.environ.get('AAAS_NATIVE_BRIDGE_BUNDLE', '').strip()
    workspace = getattr(config, 'workspace', None)
    if not bridge and workspace is not None:
        candidate = Path(workspace) / 'tmp/m3_native_bridge/digitalis'
        if (candidate / 'SHA256SUMS').is_file():
            bridge = str(candidate)
    if bridge:
        command.extend(('--diagnostic-native-bridge-overlay', bridge))
    return command


def run():
    config = aaas_config.resolve_config(repository=ROOT)
    runtime = Path(os.environ.get('AAAS_RUNTIME_ROOT', ROOT)).resolve(strict=True)
    runner = runtime / 'scripts' / 'run_aaas.py'
    if not runner.is_file():
        raise RuntimeError(f'installed Android runner is missing: {runner}')
    environment = os.environ.copy()
    environment.update({
        'AAAS_WORKSPACE': str(config.workspace),
        'AAAS_ROOTFS': str(config.rootfs),
        'AAAS_RUNTIME_ROOT': str(runtime),
        'AAAS_PROFILE': config.profile,
        'AAAS_DEV_COMPAT': '1',
        'AAAS_IDLE_TIMEOUT_SECONDS': '3600',
        'AAAS_AUDIO': '1' if config.audio else '0',
        'PYTHONPATH': str(runtime / 'scripts') + os.pathsep +
                      environment.get('PYTHONPATH', ''),
    })
    command = _runner_command(runner, config)
    process = subprocess.Popen(command, env=environment, start_new_session=True)
    stopping = False

    def request_stop(_signum, _frame):
        nonlocal stopping
        stopping = True
        control = _socket_for(config.workspace)
        if control:
            try:
                _request(control, 'stop')
            except (OSError, RuntimeError, ValueError):
                pass

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    deadline = time.monotonic() + 240
    control = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return process.returncode or 1
        control = _socket_for(config.workspace)
        if control:
            try:
                result = _request(control, 'list')
                if result.get('state') == 'RUNNING':
                    break
            except (OSError, RuntimeError, ValueError):
                pass
        time.sleep(.25)
    else:
        process.terminate()
        process.wait(timeout=20)
        raise RuntimeError('Android runtime did not become ready within 240 seconds')

    # The bootstrap task establishes the existing run_aaas lifecycle. Close it
    # via the same application manager used by normal app windows.
    bootstrap = _request(control, 'list')
    initial = next((item for item in bootstrap.get('windows', [])
                    if item.get('package') == 'com.android.settings' and
                    item.get('state') == 'RUNNING'), None)
    if initial:
        closed = _request(control, 'close', int(initial['slot']))
        if not closed.get('ok'):
            _request(control, 'stop')
            process.wait(timeout=30)
            raise RuntimeError(f'could not close service bootstrap window: {closed}')
        close_deadline = time.monotonic() + 20
        while time.monotonic() < close_deadline:
            snapshot = _request(control, 'list')
            windows = snapshot.get('windows', [])
            if all(item.get('state') == 'CLOSED' and
                   item.get('presenter_pid') is None and
                   item.get('display_id') is None for item in windows):
                break
            time.sleep(.25)
        else:
            _request(control, 'stop')
            process.wait(timeout=30)
            raise RuntimeError('bootstrap presenter remained after its close request')
    print('AaaS persistent Android runtime ready with zero app windows', flush=True)

    while process.poll() is None:
        if stopping:
            break
        time.sleep(.5)
    if stopping and process.poll() is None:
        process.wait(timeout=35)
    return process.returncode or 0


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv != ['run']:
        print('usage: aaas_runtime_service.py run', file=sys.stderr)
        return 2
    try:
        return run()
    except Exception as error:
        print(f'AaaS runtime service: {type(error).__name__}: {error}',
              file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
