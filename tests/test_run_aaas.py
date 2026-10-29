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
    def test_process_group_cleanup_kills_namespace_pid1_survivors(self):
        import os
        import subprocess
        import sys
        import time

        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / 'child.pid'
            child_code = (
                'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                'time.sleep(60)'
            )
            parent_code = (
                'import pathlib,signal,subprocess,sys; '
                'child=subprocess.Popen([sys.executable,"-c",sys.argv[2]]); '
                'pathlib.Path(sys.argv[1]).write_text(str(child.pid)); signal.pause()'
            )
            process = subprocess.Popen(
                [sys.executable, '-c', parent_code, str(pid_path), child_code],
                start_new_session=True,
            )
            child_pid = None
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not pid_path.exists():
                    time.sleep(.02)
                self.assertTrue(pid_path.exists(), 'child did not start')
                child_pid = int(pid_path.read_text())
                SESSION.terminate_process_group(process, timeout=2)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and Path(f'/proc/{child_pid}').exists():
                    time.sleep(.02)
                self.assertFalse(Path(f'/proc/{child_pid}').exists(),
                                 'surviving process remained in session group')
            finally:
                if process.poll() is None:
                    SESSION.terminate_process_group(process, timeout=2)
                if child_pid and Path(f'/proc/{child_pid}').exists():
                    try:
                        os.kill(child_pid, 9)
                    except ProcessLookupError:
                        pass

    def test_runner_copy_keeps_inherited_source_and_isolates_ipc(self):
        import subprocess
        import sys

        original_hash = SESSION.sha256(SESSION.RUNNER)
        with tempfile.TemporaryDirectory() as directory:
            generated_path = SESSION.make_session_runner(Path(directory))
            generated = generated_path.read_text()
            compiled = subprocess.run(
                [sys.executable, '-m', 'py_compile', str(generated_path)],
                capture_output=True, text=True,
            )
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        self.assertEqual(SESSION.sha256(SESSION.RUNNER), original_hash)
        self.assertIn('ipc_dir = Path(os.environ["AAAS_SESSION_IPC"])', generated)
        self.assertIn('ipc_dir.chmod(0o711)', generated)
        self.assertIn('vdc_overlay = Path(os.environ["AAAS_VDC_OVERLAY"])', generated)
        self.assertIn('--ro-bind "{vdc_overlay}" /system/bin/vdc', generated)
        self.assertIn('{vdc_bind}{framework_ime_bind}{lmkd_bind}', generated)
        self.assertIn('lmkd_bind', generated)
        self.assertIn('/aaas_session_logcat', generated)
        self.assertIn('echo RUNNING > /aaas_session_status', generated)
        self.assertIn('p.communicate(timeout=None)', generated)
        self.assertNotIn('p.communicate(timeout=80)', generated)
        self.assertIn('start_new_session=False', generated)
        self.assertIn('    ) &\n    exec /system/bin/init second_stage', generated)
        self.assertNotIn('/system/bin/init second_stage &', generated)
        self.assertIn('    echo RUNNING > /aaas_session_status', generated)

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
        self.assertLess(generated.index('AAAS_INPUT_ADAPTER_STARTED'),
                        generated.index('=== RESOLVING AND LAUNCHING ANDROID APPLICATION ==='))

    def test_runner_resolves_the_requested_package_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = SESSION.make_session_runner(
                Path(directory), app_package='com.example.reader').read_text()
        self.assertIn('-p com.example.reader | /system/bin/toybox tail -n 1', generated)
        self.assertIn('pidof com.example.reader', generated)
        self.assertIn('No launchable activity for com.example.reader', generated)
        self.assertNotIn('start-activity -W -n com.android.settings/.Settings', generated)

    def test_app_package_validation_rejects_shell_syntax(self):
        for package in ('com.example;reboot', 'com.example/app', 'android', '', None):
            with self.subTest(package=package):
                with self.assertRaises(ValueError):
                    SESSION.validate_app_package(package)

    def test_runner_enables_desktop_ime_policy_and_binds_framework_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = SESSION.make_session_runner(Path(directory)).read_text()
        self.assertIn('framework_ime_overlay = Path(os.environ["AAAS_FRAMEWORK_JAR_OVERLAY"])',
                      generated)
        self.assertIn('--ro-bind "{framework_ime_overlay}" /system/framework/framework.jar',
                      generated)
        self.assertIn('settings put secure show_ime_with_hard_keyboard 0', generated)
        self.assertIn('settings put secure aaas_desktop_mode 1', generated)
        self.assertLess(generated.index('settings put secure aaas_desktop_mode 1'),
                        generated.index('=== RESOLVING AND LAUNCHING ANDROID APPLICATION ==='))

    def test_runner_exposes_mobile_ime_escape_hatch(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = SESSION.make_session_runner(Path(directory), desktop_ime=False).read_text()
        self.assertIn('settings put secure show_ime_with_hard_keyboard 1', generated)
        self.assertIn('settings delete secure aaas_desktop_mode', generated)

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
