#!/usr/bin/env python3
"""Run an Android AudioRecord capture outage against private PipeWire.

Requires an active Linux Wayland session, the enrolled AaaS workspace, the
installed ``org.aaas.audiocaptureprobe``, and its previously granted Android
RECORD_AUDIO permission. Only temporary PipeWire children are terminated.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'org.aaas.audiocaptureprobe'
sys.path.insert(0, str(ROOT / 'scripts'))
from aaas_audio import PulseCapture, pcm16_summary
from run_aaas import WORKSPACE


def run_command(args, env=None, timeout=10):
    return subprocess.run(args, env=env, capture_output=True, text=True,
                          timeout=timeout, check=True)


def stop_process(process, timeout=3):
    if not process or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def wait_for(predicate, timeout, description):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise TimeoutError(f'timed out waiting for {description}')


def read(path):
    try:
        return path.read_text(errors='replace')
    except OSError:
        return ''


class ToneSource:
    """Play a bounded 440 Hz fixture into the isolated null sink."""
    def __init__(self, runtime: Path):
        self.path = runtime / 'controlled-440hz.wav'
        block = b''.join(int(8000 * math.sin(2 * math.pi * 440 * i / 48000))
                         .to_bytes(2, 'little', signed=True) for i in range(48000))
        with wave.open(str(self.path), 'wb') as fixture:
            fixture.setnchannels(1)
            fixture.setsampwidth(2)
            fixture.setframerate(48000)
            fixture.writeframes(block * 120)
        self.log = (runtime / 'tone-source.log').open('ab')
        self.process = subprocess.Popen(['paplay', '--device=aaas_android_fault',
                                         str(self.path)],
            env=os.environ.copy(), stdout=self.log, stderr=subprocess.STDOUT)
        time.sleep(.1)
        if self.process.poll() is not None:
            self.log.close()
            raise RuntimeError('isolated paplay fixture exited during startup')

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.log.close()


def run():
    for tool in ('pipewire', 'wireplumber', 'pipewire-pulse', 'pactl'):
        if not shutil.which(tool):
            raise SystemExit(f'required integration tool is unavailable: {tool}')
    if not os.environ.get('WAYLAND_DISPLAY') or not os.environ.get('XDG_RUNTIME_DIR'):
        raise SystemExit('an active Wayland desktop session is required')
    capture_apk = Path(os.environ.get('AAAS_AUDIO_CAPTURE_APK',
                                      '/tmp/AaasAudioCaptureProbe.apk'))
    if not capture_apk.is_file():
        raise SystemExit(f'capture probe APK does not exist: {capture_apk}')
    preflight = run_command([os.sys.executable, str(ROOT / 'scripts/android_workspace.py'),
        '--workspace', str(WORKSPACE), 'check'])
    preflight_data = json.loads(preflight.stdout)
    if preflight_data.get('health', {}).get('state') != 'HEALTHY_FOR_CONTROLLED_TESTING':
        raise SystemExit('workspace health guard did not authorize controlled testing')
    if preflight_data.get('mount', {}).get('uuid') != '094120c3-e1f8-4a61-a95a-c347ecb711d1':
        raise SystemExit('workspace UUID differs from enrolled ext4 UUID')
    current = subprocess.run([os.sys.executable, str(ROOT / 'scripts/aaasctl.py'),
        'list'], capture_output=True, text=True, timeout=5, check=False)
    if current.returncode == 0:
        raise SystemExit('an AaaS runtime is already active')
    if 'no active AaaS app session control socket' not in current.stderr:
        raise SystemExit('could not establish that AaaS is stopped')

    with tempfile.TemporaryDirectory(prefix='aaas-m4-android-pw-') as directory:
        runtime = Path(directory)
        (runtime / 'pipewire').mkdir(mode=0o700)
        (runtime / 'pulse').mkdir(mode=0o700)
        env = os.environ.copy()
        env['PIPEWIRE_RUNTIME_DIR'] = str(runtime / 'pipewire')
        env['PULSE_RUNTIME_PATH'] = str(runtime / 'pulse')
        env['PULSE_SERVER'] = f'unix:{runtime}/pulse/native'
        # libpulse resolves PULSE_SERVER from this process environment, whereas
        # pactl receives it explicitly. Keep all fixture clients on the private
        # server; the user's desktop audio server is never a test target.
        os.environ['PULSE_SERVER'] = env['PULSE_SERVER']
        logs = {name: (runtime / f'{name}.log').open('wb')
                for name in ('pipewire', 'wireplumber', 'pipewire-pulse', 'runner')}
        processes = {}
        tone = None
        result = {'workspace_preflight': preflight_data,
                  'pipewire_runtime_isolated': True, 'sessions': []}
        runner = None
        try:
            processes['pipewire'] = subprocess.Popen(['pipewire'], env=env,
                stdout=logs['pipewire'], stderr=subprocess.STDOUT)
            time.sleep(.3)
            processes['wireplumber'] = subprocess.Popen(['wireplumber'], env=env,
                stdout=logs['wireplumber'], stderr=subprocess.STDOUT)
            time.sleep(.3)
            processes['pipewire-pulse'] = subprocess.Popen(['pipewire-pulse'], env=env,
                stdout=logs['pipewire-pulse'], stderr=subprocess.STDOUT)
            wait_for(lambda: subprocess.run(['pactl', 'info'], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0,
                5, 'isolated pipewire-pulse')
            run_command(['pactl', 'load-module', 'module-null-sink',
                         'sink_name=aaas_android_fault'], env=env)
            run_command(['pactl', 'set-default-sink', 'aaas_android_fault'], env=env)
            tone = ToneSource(runtime)
            time.sleep(.25)
            monitor = PulseCapture(48000, 1, 'aaas_android_fault.monitor')
            signal = pcm16_summary(monitor.read(3840))
            monitor.close()
            if signal['rms'] < 100.0 or signal['zero_crossings'] < 20:
                raise RuntimeError(f'isolated source lacks expected tone: {signal}')
            session_rx = re.compile(r'AaaS: PREPARING \(([^)]+)\)')

            def start_session(package, install=False):
                nonlocal runner
                log = logs['runner']
                log.seek(0)
                log.truncate()
                command = [os.sys.executable, str(ROOT / 'scripts/run_aaas.py'),
                    '--experimental-virtual-display', '--audio',
                    '--audio-capture-source', 'aaas_android_fault.monitor',
                    '--app', package, '--idle-timeout-seconds', '300']
                if install:
                    command.extend(('--install-apk', str(capture_apk)))
                runner = subprocess.Popen(command, env=env, stdout=log,
                                          stderr=subprocess.STDOUT)
                wait_for(lambda: bool(session_rx.search(read(runtime / 'runner.log'))),
                         40, f'AaaS session creation for {package}')
                session_dir = Path(session_rx.search(read(runtime / 'runner.log')).group(1))
                wait_for(lambda: read(session_dir / 'status').strip() == 'RUNNING',
                         120, f'Android runtime readiness for {package}')
                if runner.poll() is not None:
                    raise RuntimeError(f'AaaS runner exited after readiness for {package}')
                result['sessions'].append(session_dir.name)
                return session_dir

            def stop_session(session_dir):
                nonlocal runner
                if runner and runner.poll() is None:
                    run_command([os.sys.executable, str(ROOT / 'scripts/aaasctl.py'),
                                 'stop'], timeout=12)
                    runner.wait(timeout=30)
                wait_for(lambda: read(session_dir / 'status').strip() == 'STOPPED',
                         20, f'session {session_dir.name} shutdown')

            # Install the updated ordinary package during a preparation session
            # that launches Settings, then verify capture in a clean session.
            install_dir = start_session('com.android.settings', install=True)
            wait_for(lambda: 'AAAS_USER_APK_INSTALL index=1 status=0 result=Success' in
                     read(install_dir / 'commands.log'), 30,
                     'ordinary capture probe installation')
            result['probe_apk_sha256'] = __import__('hashlib').sha256(
                capture_apk.read_bytes()).hexdigest()
            stop_session(install_dir)

            # Exercise Android AudioRecord while the private Pulse server is
            # interrupted. The long probe classifies only its final second.
            session_dir = start_session(PACKAGE)
            bridge_log = session_dir / 'audio-bridge.log'
            capture_deadline = time.monotonic() + 20
            while time.monotonic() < capture_deadline:
                bridge_text = read(bridge_log)
                if 'audio stream opened direction=capture' in bridge_text:
                    break
                if 'Pulse capture context connect failed' in bridge_text:
                    raise RuntimeError('bridge cannot reach isolated PipeWire server: '
                        + '\n'.join(bridge_text.splitlines()[-8:]))
                if runner.poll() is not None:
                    raise RuntimeError('AaaS runner exited before capture became active')
                time.sleep(0.05)
            else:
                raise TimeoutError('timed out waiting for Android AudioRecord capture; '
                    + '\n'.join(read(bridge_log).splitlines()[-8:]))
            result['initial_capture_opened'] = True

            outage_started = time.monotonic()
            stop_process(processes.pop('pipewire-pulse'))
            tone.close()
            tone = None
            wait_for(lambda: 'audio stream closed direction=capture' in read(bridge_log),
                     5, 'host capture stream closure')
            closure_seconds = time.monotonic() - outage_started
            wait_for(lambda: 'CAPTURE_FAILED' in read(session_dir / 'logcat.log'),
                     40, 'Android AudioRecord failure result')
            result['outage'] = {'host_stream_closed_seconds': round(closure_seconds, 4),
                                'android_capture_failed': True,
                                'bounded_target_seconds': 5}
            stop_session(session_dir)
            result['outage_session_state'] = read(session_dir / 'status').strip()

            processes['pipewire-pulse'] = subprocess.Popen(['pipewire-pulse'], env=env,
                stdout=logs['pipewire-pulse'], stderr=subprocess.STDOUT)
            wait_for(lambda: subprocess.run(['pactl', 'info'], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0,
                5, 'isolated pipewire-pulse recovery')
            run_command(['pactl', 'load-module', 'module-null-sink',
                         'sink_name=aaas_android_fault'], env=env)
            run_command(['pactl', 'set-default-sink', 'aaas_android_fault'], env=env)
            if tone:
                tone.close()
            tone = ToneSource(runtime)
            time.sleep(.25)
            monitor = PulseCapture(48000, 1, 'aaas_android_fault.monitor')
            recovered_signal = pcm16_summary(monitor.read(3840))
            monitor.close()
            if recovered_signal['rms'] < 100.0 or recovered_signal['zero_crossings'] < 20:
                raise RuntimeError(f'restarted source lacks 440 Hz PCM: {recovered_signal}')
            result['recovered_source_signal'] = recovered_signal

            session_dir = start_session(PACKAGE)
            bridge_log = session_dir / 'audio-bridge.log'
            wait_for(lambda: 'audio stream opened direction=capture' in read(bridge_log),
                     20, 'fresh Android capture stream after recovery')
            wait_for(lambda: ('CAPTURE_OK rate=48000 channels=1 frames=1440000' in
                               read(session_dir / 'logcat.log')),
                     40, 'fresh Android capture after PipeWire recovery')
            capture_line = next(line for line in read(session_dir / 'logcat.log').splitlines()
                if 'CAPTURE_OK rate=48000 channels=1 frames=1440000' in line)
            result['recovered_capture'] = capture_line.strip()
            result['recovery_session_id'] = session_dir.name
            stop_session(session_dir)
        finally:
            if runner and runner.poll() is None:
                try:
                    run_command([os.sys.executable, str(ROOT / 'scripts/aaasctl.py'),
                                 'stop'], timeout=8)
                    runner.wait(timeout=20)
                except (subprocess.SubprocessError, OSError):
                    stop_process(runner, 5)
            for process in list(processes.values()):
                stop_process(process)
            if tone:
                tone.close()
            for log in logs.values():
                log.close()

        if result['sessions']:
            final_dir = WORKSPACE / 'tmp' / result['sessions'][-1]
            result['final_session_state'] = read(final_dir / 'status').strip()
            result['final_logcat_sha256'] = __import__('hashlib').sha256(
                (final_dir / 'logcat.log').read_bytes()).hexdigest()
            result['final_audio_bridge_sha256'] = __import__('hashlib').sha256(
                (final_dir / 'audio-bridge.log').read_bytes()).hexdigest()
        result['outcome'] = ('PASS' if result.get('outage', {}).get(
            'android_capture_failed') and result.get('recovered_capture') and
            result.get('final_session_state') == 'STOPPED' else 'FAIL')
        print(json.dumps(result, indent=2))
        if result['outcome'] != 'PASS':
            raise SystemExit(1)


if __name__ == '__main__':
    run()
