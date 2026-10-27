"""Guard the diagnostic session's generated runner and mount isolation."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_aaas.py'
SPEC = importlib.util.spec_from_file_location('run_aaas', SCRIPT)
SESSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SESSION)


class ForegroundRunnerTests(unittest.TestCase):
    def test_runner_copy_keeps_inherited_source_and_isolates_ipc(self):
        original_hash = SESSION.sha256(SESSION.RUNNER)
        with tempfile.TemporaryDirectory() as directory:
            generated = SESSION.make_session_runner(Path(directory)).read_text()
        self.assertEqual(SESSION.sha256(SESSION.RUNNER), original_hash)
        self.assertIn('ipc_dir = Path(os.environ["AAAS_SESSION_IPC"])', generated)
        self.assertIn('ipc_dir.chmod(0o711)', generated)
        self.assertIn('lmkd_bind', generated)
        self.assertIn('/aaas_session_logcat', generated)
        self.assertIn('echo RUNNING > /aaas_session_status', generated)
        self.assertIn('p.communicate(timeout=None)', generated)
        self.assertIn('start_new_session=False', generated)

    def test_runner_hash_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            alternate = Path(directory) / 'runner.py'
            alternate.write_text('changed')
            with patch.object(SESSION, 'RUNNER', alternate):
                with self.assertRaisesRegex(RuntimeError, 'runner changed'):
                    SESSION.make_session_runner(Path(directory))

    def test_runner_binds_adapter_and_starts_private_input_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = root / 'aaas-input-adapter'
            adapter.write_text('adapter')
            adapter.chmod(0o755)
            adapter_log = root / 'input-adapter.log'
            adapter_log.touch()
            with patch.dict('os.environ', {
                    'AAAS_INPUT_ADAPTER': str(adapter),
                    'AAAS_INPUT_ADAPTER_LOG': str(adapter_log),
            }):
                generated = SESSION.make_session_runner(root).read_text()
        self.assertIn('--ro-bind "{input_adapter}" /system/bin/aaas-input-adapter',
                      generated)
        self.assertIn('--bind "{input_adapter_log}" /aaas_input_adapter.log',
                      generated)
        self.assertIn('/system/bin/aaas-input-adapter --socket /dev/aaas/input.sock',
                      generated)
        self.assertIn('--session-file /dev/aaas/input_session', generated)
        self.assertIn('--log /aaas_input_adapter.log', generated)
        self.assertIn('/dev/aaas/input.sock', generated)

    def test_single_instance_lock_rejection(self):
        import fcntl
        import os
        import subprocess
        import sys
        lock_path = SESSION.TMP / '.aaas_session.lock'
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            res = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 2)
            self.assertIn('another foreground session is already running', res.stderr)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def test_invalid_startup_timeout_rejected(self):
        import subprocess
        import sys
        res = subprocess.run([sys.executable, str(SCRIPT), '--startup-timeout', '0'],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn('startup timeout must be positive', res.stderr)


if __name__ == '__main__':
    unittest.main()
