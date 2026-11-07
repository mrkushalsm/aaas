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


class FakePulse:
    instances = []

    def __init__(self, direction, rate, channels, device=None):
        self.direction = direction
        self.rate = rate
        self.channels = channels
        self.device = device
        self.writes = []
        self.read_data = bytes(range(16))
        self.closed = False
        self.drained = False
        self.instances.append(self)

    def write(self, data):
        self.writes.append(bytes(data))

    def read(self, size):
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

    def tearDown(self):
        self.server.stop_event.set()
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        self.server.server_close()
        self.thread.join(timeout=1)
        self.patch.stop()
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

    def test_invalid_header_does_not_create_audio_stream(self):
        client = self.connect(rate=192000)
        self.assertEqual(b'', client.recv(1))
        client.close()
        self.assertEqual([], FakePulse.instances)

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


if __name__ == '__main__':
    unittest.main()
