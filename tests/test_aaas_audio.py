import socket
import os
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import aaas_audio


def make_fake_capture(rate, channels, device=None, *, stop_event=None):
    return FakePulse(aaas_audio.CAPTURE, rate, channels, device,
                     stop_event=stop_event)


class FakePulse:
    instances = []
    fail_write = False
    fail_read = False

    def __init__(self, direction, rate, channels, device=None, *, stop_event=None):
        self.direction = direction
        self.rate = rate
        self.channels = channels
        self.device = device
        self.writes = []
        self.read_data = bytes(range(16))
        self.closed = False
        self.stop_event = stop_event
        self.drained = False
        self.instances.append(self)

    def write(self, data):
        if self.fail_write:
            raise RuntimeError('simulated PipeWire sink failure')
        self.writes.append(bytes(data))

    def read(self, size):
        if self.fail_read:
            raise RuntimeError('simulated PipeWire capture disconnect')
        return (self.read_data * ((size + len(self.read_data) - 1) // len(self.read_data)))[:size]

    def close(self):
        self.closed = True

    def drain(self):
        self.drained = True


class AudioBridgeTests(unittest.TestCase):
    def setUp(self):
        FakePulse.instances.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'audio.sock'
        self.server = aaas_audio.AudioServer(
            self.path, os.getuid(), playback_sink='aaas-test-sink',
            capture_source='aaas-test-source')
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()
        self.patch = patch.object(aaas_audio, 'PulseSimple', FakePulse)
        self.patch.start()
        self.capture_patch = patch.object(aaas_audio, 'PulseCapture', make_fake_capture)
        self.capture_patch.start()

    def tearDown(self):
        self.server.request_stop()
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        self.server.server_close()
        self.thread.join(timeout=1)
        self.patch.stop()
        self.capture_patch.stop()
        self.temp.cleanup()

    def connect(self, direction=aaas_audio.PLAYBACK, rate=48000, channels=2, fmt=aaas_audio.S16_LE):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(1)
        for _ in range(50):
            try:
                client.connect(str(self.path))
                break
            except FileNotFoundError:
                time.sleep(0.01)
        client.sendall(aaas_audio.HELLO.pack(aaas_audio.MAGIC, aaas_audio.VERSION,
                                             direction, rate, channels, fmt))
        return client

    def test_playback_forwards_pcm_and_closes_host_stream(self):
        client = self.connect()
        pcm = b'\x34\x12\x78\x56' * 256
        client.sendall(pcm)
        client.shutdown(socket.SHUT_WR)
        client.close()
        for _ in range(100):
            if FakePulse.instances and FakePulse.instances[0].closed:
                break
            time.sleep(0.01)
        self.assertEqual([pcm], FakePulse.instances[0].writes)
        self.assertEqual('aaas-test-sink', FakePulse.instances[0].device)
        self.assertTrue(FakePulse.instances[0].drained)
        self.assertTrue(FakePulse.instances[0].closed)

    def test_unaligned_pcm_tail_is_rejected_and_stream_is_closed(self):
        client = self.connect()
        client.sendall(b'\x01\x02\x03')
        client.shutdown(socket.SHUT_WR)
        client.close()
        for _ in range(100):
            if FakePulse.instances and FakePulse.instances[0].closed:
                break
            time.sleep(0.01)
        self.assertEqual([], FakePulse.instances[0].writes)
        self.assertFalse(FakePulse.instances[0].drained)
        self.assertTrue(FakePulse.instances[0].closed)

    def test_pipewire_write_failure_closes_stream_without_server_deadlock(self):
        FakePulse.fail_write = True
        try:
            client = self.connect()
            client.sendall(b'\x34\x12\x78\x56')
            self.assertEqual(b'', client.recv(1))
            client.close()
            for _ in range(100):
                if FakePulse.instances and FakePulse.instances[0].closed:
                    break
                time.sleep(0.01)
            self.assertTrue(FakePulse.instances[0].closed)
            self.assertFalse(self.server.stop_event.is_set())
        finally:
            FakePulse.fail_write = False

    def test_capture_peer_disconnect_closes_pipewire_source(self):
        client = self.connect(direction=aaas_audio.CAPTURE, rate=8000, channels=1)
        deadline = time.monotonic() + 1
        while not FakePulse.instances and time.monotonic() < deadline:
            time.sleep(0.005)
        client.close()
        deadline = time.monotonic() + 1
        while self.server.active_workers and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(0, self.server.active_workers)
        self.assertTrue(FakePulse.instances)
        self.assertTrue(FakePulse.instances[0].closed)

    def test_capture_returns_host_pcm_frames(self):
        client = self.connect(direction=aaas_audio.CAPTURE, rate=8000, channels=1)
        expected_size = 8000 // 50 * 2
        received = bytearray()
        while len(received) < expected_size:
            received.extend(client.recv(expected_size - len(received)))
        self.assertEqual(bytes(range(16)) * (expected_size // 16), bytes(received))
        self.assertEqual('aaas-test-source', FakePulse.instances[0].device)
        client.close()
        for _ in range(100):
            if FakePulse.instances and FakePulse.instances[0].closed:
                break
            time.sleep(0.01)
        self.assertTrue(FakePulse.instances[0].closed)

    def test_capture_transport_failure_closes_stream_and_releases_worker(self):
        FakePulse.fail_read = True
        client = self.connect(direction=aaas_audio.CAPTURE, rate=8000, channels=1)
        started = time.monotonic()
        try:
            self.assertEqual(b'', client.recv(1))
        finally:
            client.close()
            FakePulse.fail_read = False
        deadline = time.monotonic() + 1
        while self.server.active_workers and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(0, self.server.active_workers)
        self.assertTrue(FakePulse.instances[0].closed)

    def test_session_shutdown_cancels_active_capture_worker(self):
        client = self.connect(direction=aaas_audio.CAPTURE, rate=8000, channels=1)
        self.assertTrue(client.recv(320))
        started = time.monotonic()
        self.server.request_stop()
        deadline = time.monotonic() + 1
        while self.server.active_workers and time.monotonic() < deadline:
            time.sleep(0.005)
        client.close()
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(0, self.server.active_workers)
        self.assertTrue(FakePulse.instances[0].closed)

    def test_invalid_header_does_not_create_audio_stream(self):
        client = self.connect(rate=192000)
        self.assertEqual(b'', client.recv(1))
        client.close()
        self.assertEqual([], FakePulse.instances)

    def test_unauthenticated_connections_cannot_exhaust_unbounded_workers(self):
        clients = []
        try:
            for _ in range(aaas_audio.MAX_CLIENTS):
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.settimeout(2)
                client.connect(str(self.path))
                clients.append(client)
            time.sleep(0.1)

            excess = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            excess.settimeout(1)
            excess.connect(str(self.path))
            self.assertEqual(b'', excess.recv(1))
            excess.close()
            for client in clients:
                client.shutdown(socket.SHUT_WR)
            time.sleep(0.1)
        finally:
            for client in clients:
                client.close()

        recovered = self.connect()
        recovered.sendall(b'\x34\x12\x78\x56')
        recovered.shutdown(socket.SHUT_WR)
        recovered.close()
        deadline = time.monotonic() + 1
        while not FakePulse.instances and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(FakePulse.instances)

    def test_four_live_capture_clients_enforce_limit_and_release_capacity(self):
        clients = []
        excess = None
        recovered = None
        try:
            clients = [self.connect(direction=aaas_audio.CAPTURE, rate=8000, channels=1)
                       for _ in range(aaas_audio.MAX_CLIENTS)]
            deadline = time.monotonic() + 1
            while len(FakePulse.instances) < aaas_audio.MAX_CLIENTS and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(aaas_audio.MAX_CLIENTS, len(FakePulse.instances))
            self.assertEqual(aaas_audio.MAX_CLIENTS, self.server.active_workers)

            try:
                excess = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                excess.settimeout(1)
                excess.connect(str(self.path))
                excess.sendall(aaas_audio.HELLO.pack(
                    aaas_audio.MAGIC, aaas_audio.VERSION, aaas_audio.CAPTURE,
                    8000, 1, aaas_audio.S16_LE))
                rejected = excess.recv(1) == b''
            except (BrokenPipeError, ConnectionResetError):
                rejected = True
            self.assertTrue(rejected, 'fifth client must be closed by the bridge')
            excess.close()
            self.assertEqual(aaas_audio.MAX_CLIENTS, len(FakePulse.instances))

            for client in clients:
                client.close()
            deadline = time.monotonic() + 1
            while self.server.active_workers and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(0, self.server.active_workers)

            recovered = self.connect(direction=aaas_audio.CAPTURE, rate=8000, channels=1)
            self.assertTrue(recovered.recv(320))
            recovered.close()
            deadline = time.monotonic() + 1
            while self.server.active_workers and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(0, self.server.active_workers)
            self.assertEqual(aaas_audio.MAX_CLIENTS + 1, len(FakePulse.instances))
        finally:
            for client in clients:
                client.close()
            for client in (excess, recovered):
                if client is not None:
                    client.close()

    def test_pcm_summary_is_metadata_only_and_rejects_partial_samples(self):
        pcm = struct.pack('<hhhh', -100, 100, -100, 100)
        self.assertEqual({'frames': 4, 'nonzero': 4, 'peak': 100,
                          'rms': 100.0, 'zero_crossings': 3},
                         aaas_audio.pcm16_summary(pcm))
        with self.assertRaisesRegex(ValueError, 'unaligned'):
            aaas_audio.pcm16_summary(b'\x01')

    def test_rejects_non_socket_replacement_path(self):
        self.server.server_close()
        self.path.unlink()
        self.path.write_text('fixture')
        with self.assertRaises(RuntimeError):
            aaas_audio.main(['--socket', str(self.path), '--android-host-uid', '1'])

    def test_legacy_hal_exposes_callbacks_required_by_hidl_adapter(self):
        source = (Path(__file__).parents[1] / 'experiments/m4/audio/audio_hal.c').read_text()
        for callback in ('set_voice_volume', 'set_parameters', 'get_parameters'):
            self.assertIn(f'd->hw.{callback} = adev_{callback}', source)
        self.assertIn('transport_failed = true', source)
        self.assertIn('transport_failed = false', source)
        self.assertIn('return in_silence(i, buffer, bytes, fs)', source)
        host = (Path(__file__).parents[1] / 'scripts/aaas_audio.py').read_text()
        self.assertIn('pa_stream_set_read_callback', host)
        self.assertIn("os.environ.get('PULSE_SERVER')", host)
        probe = (Path(__file__).parents[1] / 'experiments/m4/audio/src-probe/'
                 'org/aaas/audioprobe/MainActivity.java').read_text()
        self.assertIn('CAPTURE_FAILED silent PCM', probe)

    def test_android_playback_probe_exercises_pause_resume_and_mute(self):
        root = Path(__file__).parents[1] / 'experiments/m4/audio'
        source = (root / 'src-probe/org/aaas/audioprobe/MainActivity.java').read_text()
        builder = (root / 'build_probe.py').read_text()
        for marker in ('track.pause();', 'track.play();', 'track.setVolume(0.0f)',
                       'track.setVolume(1.0f)', 'PLAYBACK_PAUSE_OK',
                       'PLAYBACK_RESUME_OK', 'pause_resume=ok mute=ok',
                       'awaitPlaybackHead(track, written / 2)',
                       'getPlaybackHeadPosition()', 'writeSegment(track, pcm'):
            self.assertIn(marker, source)
        for marker in ('MONO_PLAYBACK_OK rate=', 'rate = 44100',
                       'channels=1 frames=', 'frames = rate'):
            self.assertIn(marker, source)
        self.assertIn('CHANNEL_OUT_MONO=4', builder)
        self.assertIn('public void pause(){}', builder)
        self.assertIn('public int setVolume(float v)', builder)
        self.assertIn("parser.add_argument('--capture-duration-seconds'", builder)
        self.assertIn("1 <= args.capture_duration_seconds <= 60", builder)
        self.assertIn("'AaaS Audio Capture Probe' if args.capture", builder)
        self.assertIn("parser.add_argument('--package-name'", builder)
        self.assertIn("parser.add_argument('--playback-music-volume'", builder)
        self.assertIn('manager.setStreamVolume(AudioManager.STREAM_MUSIC, testMusicVolume, 0)', builder)
        self.assertIn('manager.setStreamVolume(AudioManager.STREAM_MUSIC, previousMusicVolume, 0)', builder)
        self.assertIn('TEST_MUSIC_VOLUME_RESTORED', builder)


if __name__ == '__main__':
    unittest.main()
