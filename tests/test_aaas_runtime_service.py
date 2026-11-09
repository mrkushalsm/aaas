from pathlib import Path
import unittest
from types import SimpleNamespace

from scripts import aaas_runtime_service


class PersistentServiceCommandTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
