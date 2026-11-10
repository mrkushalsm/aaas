from pathlib import Path
import os
import socket
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import aaas_runtime_service


class PersistentServiceCommandTests(unittest.TestCase):
    def test_socket_discovery_does_not_open_probe_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session_ipc = workspace / 'tmp/m1b84_session_test/ipc'
            session_ipc.mkdir(parents=True)
            path = Path(directory) / 'runtime.sock'
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(path))
                listener.listen(4)
                listener.setblocking(False)
                (session_ipc / 'aaas-control.path').write_text(str(path) + '\n')
                self.assertEqual(aaas_runtime_service._socket_for(workspace), path)
                with self.assertRaises(BlockingIOError):
                    listener.accept()

    def test_audio_feature_enables_runner_audio_hal(self):
        command = aaas_runtime_service._runner_command(
            Path('/opt/aaas/scripts/run_aaas.py'),
            SimpleNamespace(audio=True))
        self.assertIn('--audio', command)
        self.assertEqual(command.count('--audio'), 1)

    def test_audio_disabled_does_not_change_runner_mode(self):
        command = aaas_runtime_service._runner_command(
            Path('/opt/aaas/scripts/run_aaas.py'),
            SimpleNamespace(audio=False))
        self.assertNotIn('--audio', command)
        self.assertIn('--experimental-virtual-display', command)
        self.assertNotIn('--headless-storage', command)

    def test_verified_workspace_native_bridge_is_enabled_for_persistent_runtime(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'AAAS_NATIVE_BRIDGE_BUNDLE': ''}):
            workspace = Path(directory)
            bundle = workspace / 'tmp/m3_native_bridge/digitalis'
            bundle.mkdir(parents=True)
            (bundle / 'SHA256SUMS').write_text('verified bundle marker')
            command = aaas_runtime_service._runner_command(
                Path('/opt/aaas/scripts/run_aaas.py'),
                SimpleNamespace(audio=False, workspace=workspace))
        self.assertIn('--diagnostic-native-bridge-overlay', command)
        self.assertEqual(command[command.index('--diagnostic-native-bridge-overlay') + 1],
                         str(bundle))

    def test_native_bridge_can_be_configured_without_workspace_default(self):
        with patch.dict(os.environ, {'AAAS_NATIVE_BRIDGE_BUNDLE': '/opt/aaas/m3'}):
            command = aaas_runtime_service._runner_command(
                Path('/opt/aaas/scripts/run_aaas.py'),
                SimpleNamespace(audio=False))
        self.assertEqual(command[-2:], ['--diagnostic-native-bridge-overlay',
                                        '/opt/aaas/m3'])


if __name__ == '__main__':
    unittest.main()
