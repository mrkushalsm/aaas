#!/usr/bin/env python3
"""Exercise AaaS capture disconnect/recovery against private PipeWire services.

Run as ``dbus-run-session -- python3 scripts/test_aaas_audio_pipewire.py``.
Only child services in a temporary runtime directory are stopped or restarted.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import time
import wave

import aaas_audio


def wait_until(predicate, timeout, description):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.025)
    raise TimeoutError(f'timed out waiting for {description}')


class PrivatePipeWire:
    def __init__(self, runtime: Path, env: dict[str, str]):
        self.runtime = runtime
        self.env = env
        self.processes: dict[str, subprocess.Popen] = {}
        self.logs = {}
        self.pulse_server = f'unix:{runtime}/pulse/native'

    def start(self, name, command):
        log = (self.runtime / f'{name}.log').open('wb')
        self.logs[name] = log
        process = subprocess.Popen(command, env=self.env, stdout=log,
                                   stderr=subprocess.STDOUT)
        self.processes[name] = process
        return process

    def stop(self, name):
        process = self.processes.pop(name, None)
        if not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def ready(self):
        result = subprocess.run(['pactl', 'info'], env=self.env,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, check=False)
        return result.returncode == 0

    def load_sink(self):
        subprocess.run(['pactl', 'load-module', 'module-null-sink',
                        'sink_name=aaas_capture_fault'], env=self.env,
                       check=True, capture_output=True, text=True)

    def has_playback(self):
        result = subprocess.run(['pactl', 'list', 'short', 'sink-inputs'],
            env=self.env, capture_output=True, text=True, check=True)
        return bool(result.stdout.strip())

    def play_tone(self, wav_path):
        process = subprocess.Popen(['paplay', '--device=aaas_capture_fault',
                                    str(wav_path)], env=self.env,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        wait_until(lambda: self.has_playback() or process.poll() is not None,
                   3, 'controlled Pulse playback stream')
        if process.poll() is not None:
            raise RuntimeError('paplay fixture failed to start: ' +
                               process.stderr.read().decode('utf-8', 'replace'))
        return process

    def start_stack(self):
        self.start('pipewire', ['pipewire'])
        self.start('wireplumber', ['wireplumber'])
        self.start('pipewire-pulse', ['pipewire-pulse'])
        wait_until(self.ready, 5, 'private pipewire-pulse')
        self.load_sink()

    def restart_pulse(self):
        self.stop('pipewire-pulse')
        wait_until(lambda: not self.ready(), 2, 'private Pulse server shutdown')
        self.start('pipewire-pulse', ['pipewire-pulse'])
        wait_until(self.ready, 5, 'private pipewire-pulse restart')
        self.load_sink()

    def close(self):
        for name in ('pipewire-pulse', 'wireplumber', 'pipewire'):
            self.stop(name)
        for log in self.logs.values():
            log.close()


def connect_capture(path: Path) -> socket.socket:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(2)
    client.connect(str(path))
    client.sendall(aaas_audio.HELLO.pack(
        aaas_audio.MAGIC, aaas_audio.VERSION, aaas_audio.CAPTURE,
        48000, 1, aaas_audio.S16_LE))
    return client


def receive_exact(client: socket.socket, size: int):
    result = bytearray()
    while len(result) < size:
        data = client.recv(size - len(result))
        if not data:
            raise ConnectionError('audio bridge closed capture stream')
        result.extend(data)
    return bytes(result)


def drain_to_eof(client: socket.socket, timeout: float):
    client.settimeout(timeout)
    started = time.monotonic()
    while True:
        data = client.recv(4096)
        if not data:
            return time.monotonic() - started


def run():
    if not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
        raise SystemExit('run this test under dbus-run-session')
    for tool in ('pipewire', 'wireplumber', 'pipewire-pulse', 'pactl', 'paplay'):
        if not shutil.which(tool):
            raise SystemExit(f'required integration tool is unavailable: {tool}')
    with tempfile.TemporaryDirectory(prefix='aaas-m4-pipewire-') as directory:
        runtime = Path(directory)
        runtime.chmod(0o700)
        env = os.environ.copy()
        pipewire_runtime = runtime / 'pipewire'
        pulse_runtime = runtime / 'pulse'
        pipewire_runtime.mkdir(mode=0o700)
        pulse_runtime.mkdir(mode=0o700)
        env['PIPEWIRE_RUNTIME_DIR'] = str(pipewire_runtime)
        env['PULSE_RUNTIME_PATH'] = str(pulse_runtime)
        env['PULSE_SERVER'] = f'unix:{pulse_runtime}/native'
        stack = PrivatePipeWire(runtime, env)
        bridge_path = runtime / 'audio.sock'
        bridge_log_path = runtime / 'bridge.log'
        bridge_log = bridge_log_path.open('wb')
        bridge = None
        tone = None
        results = {'isolated': True, 'cycles': []}
        try:
            stack.start_stack()
            tone_path = runtime / 'controlled-440hz.wav'
            samples = b''.join(int(8000 * math.sin(2 * math.pi * 440 * i / 48000))
                               .to_bytes(2, 'little', signed=True)
                               for i in range(48000))
            with wave.open(str(tone_path), 'wb') as fixture:
                fixture.setnchannels(1)
                fixture.setsampwidth(2)
                fixture.setframerate(48000)
                fixture.writeframes(samples * 20)
            bridge = subprocess.Popen([
                os.sys.executable, str(Path(__file__).with_name('aaas_audio.py')),
                '--socket', str(bridge_path), '--android-host-uid', str(os.getuid()),
                '--capture-source', 'aaas_capture_fault.monitor'],
                env=env, stdout=bridge_log, stderr=subprocess.STDOUT)
            wait_until(lambda: bridge_path.exists() and bridge.poll() is None,
                       3, 'AaaS audio bridge socket')
            for cycle in range(2):
                if tone is None or tone.poll() is not None:
                    tone = stack.play_tone(tone_path)
                time.sleep(.15)
                active = connect_capture(bridge_path)
                first = receive_exact(active, 1920)
                if len(first) != 1920:
                    raise AssertionError('capture did not deliver one bounded PCM block')
                first_signal = aaas_audio.pcm16_summary(first)
                if first_signal['rms'] < 1000 or first_signal['zero_crossings'] < 5:
                    raise AssertionError(f'controlled 440 Hz source missing: {first_signal}')
                stack.stop('pipewire-pulse')
                failed_after = drain_to_eof(active, 5)
                active.close()
                if failed_after > 5:
                    raise AssertionError('capture disconnect exceeded five seconds')

                unavailable = connect_capture(bridge_path)
                unavailable_started = time.monotonic()
                unavailable_eof = drain_to_eof(unavailable, 4)
                unavailable.close()
                unavailable_elapsed = time.monotonic() - unavailable_started
                if unavailable_elapsed > 4:
                    raise AssertionError('unavailable server did not fail boundedly')

                stack.start('pipewire-pulse', ['pipewire-pulse'])
                wait_until(stack.ready, 5, 'private pipewire-pulse restart')
                stack.load_sink()
                if tone.poll() is None:
                    tone.terminate()
                    tone.wait(timeout=2)
                tone = stack.play_tone(tone_path)
                time.sleep(.15)
                recovered = connect_capture(bridge_path)
                second = receive_exact(recovered, 1920)
                recovered_signal = aaas_audio.pcm16_summary(second)
                if recovered_signal['rms'] < 1000 or recovered_signal['zero_crossings'] < 5:
                    raise AssertionError(f'recovered 440 Hz source missing: {recovered_signal}')
                recovered.close()
                wait_until(lambda: b'audio stream closed direction=capture' in
                           bridge_log_path.read_bytes(), 2, 'capture worker release')
                results['cycles'].append({
                    'cycle': cycle + 1,
                    'first_block_bytes': len(first),
                    'first_signal': first_signal,
                    'outage_eof_seconds': round(failed_after, 4),
                    'unavailable_server_eof_seconds': round(unavailable_elapsed, 4),
                    'recovered_block_bytes': len(second),
                    'recovered_signal': recovered_signal,
                    'outcome': 'PASS',
                })

            peer = connect_capture(bridge_path)
            prior_peer_errors = bridge_log_path.read_bytes().count(
                b'audio client rejected (OSError)')
            peer.close()
            wait_until(lambda: bridge_log_path.read_bytes().count(
                b'audio client rejected (OSError)') > prior_peer_errors, 2,
                'capture peer disconnect cleanup')

            active = connect_capture(bridge_path)
            receive_exact(active, 1920)
            shutdown_started = time.monotonic()
            bridge.send_signal(signal.SIGTERM)
            bridge.wait(timeout=5)
            shutdown_elapsed = time.monotonic() - shutdown_started
            active.close()
            if shutdown_elapsed > 5 or bridge_path.exists():
                raise AssertionError('bridge shutdown did not clean up within five seconds')
            bridge = None
            results['shutdown_seconds'] = round(shutdown_elapsed, 4)
            results['bridge_exit'] = 0
            results['bridge_cleanup'] = 'socket removed; process exited; capture worker released'
            results['outcome'] = 'PASS'
        finally:
            if tone and tone.poll() is None:
                tone.terminate()
                tone.wait(timeout=3)
            if bridge and bridge.poll() is None:
                bridge.terminate()
                try:
                    bridge.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    bridge.kill()
                    bridge.wait(timeout=2)
            stack.close()
            bridge_log.close()
        print(json.dumps(results, indent=2))


if __name__ == '__main__':
    run()
