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
    def test_two_app_mode_builds_capacity_two_composer(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'composer-two-output'

            def create_output(command, check):
                self.assertTrue(check)
                output.write_bytes(b'test composer')

            with patch.object(SESSION, 'COMPOSER_MULTI_OUTPUT', output), \
                    patch.object(SESSION.subprocess, 'run', side_effect=create_output) as run:
                self.assertEqual(SESSION.build_multi_output_composer(), output)

            command = run.call_args.args[0]
            self.assertIn('AAAS_VIRTUAL_DISPLAY_CAPACITY=2', command)
            self.assertIn('AAAS_ENABLE_VIRTUAL_DISPLAY=1', command)
            self.assertIn(f'BIN={output}', command)

    def test_app_mode_hides_primary_diagnostic_unless_explicitly_requested(self):
        from types import SimpleNamespace
        self.assertFalse(SESSION.show_primary_diagnostic(SimpleNamespace(
            experimental_virtual_display=True, app='com.android.settings',
            show_primary_diagnostic=False)))
        self.assertTrue(SESSION.show_primary_diagnostic(SimpleNamespace(
            experimental_virtual_display=True, app='com.android.settings',
            show_primary_diagnostic=True)))
        self.assertTrue(SESSION.show_primary_diagnostic(SimpleNamespace(
            experimental_virtual_display=False, app='com.android.settings',
            show_primary_diagnostic=False)))

    def test_status_sentinel_recovers_stale_state_without_replacing_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status'
            status.write_text('RUNNING\n')
            original_inode = status.stat().st_ino
            SESSION.write_status_sentinel(status, 'STARTING')
            self.assertEqual(status.read_text(), 'STARTING\n')
            self.assertEqual(status.stat().st_ino, original_inode,
                             'the Android bind mount must keep observing this inode')

    def test_status_sentinel_finalizes_success_and_failure_after_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status'
            SESSION.write_status_sentinel(status, 'RUNNING')
            self.assertEqual(SESSION.finalize_status_sentinel(status, failed=False), 'STOPPED')
            self.assertEqual(status.read_text(), 'STOPPED\n')
            SESSION.write_status_sentinel(status, 'STOPPING')
            self.assertEqual(SESSION.finalize_status_sentinel(status, failed=True), 'FAILED')
            self.assertEqual(status.read_text(), 'FAILED\n')

    def test_terminal_state_journal_and_android_sentinel_match(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            status = session / 'status'
            status.write_text('RUNNING\n')
            SESSION.write_session_state(session, status, 'STOPPING')
            SESSION.write_session_state(session, status, 'STOPPED')
            states = [json.loads(line)['state'] for line in
                      (session / 'state.jsonl').read_text().splitlines()]
            self.assertEqual(states, ['STOPPING', 'STOPPED'])
            self.assertEqual(status.read_text(), states[-1] + '\n')

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
        self.assertIn('-p com.example.reader', generated)
        self.assertIn('/system/bin/toybox tail -n 1', generated)
        self.assertIn('APP_PACKAGE=com.example.reader', generated)
        self.assertIn('aaas_app_task_alive()', generated)
        self.assertIn('grep -F "u0 $APP_PACKAGE/"', generated)
        self.assertNotIn('pidof com.example.reader', generated)
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

    def test_virtual_display_runner_enables_hwc_path_before_surfaceflinger(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = SESSION.make_session_runner(
                Path(directory), experimental_virtual_display=True).read_text()
        property_line = 'setprop debug.sf.enable_hwc_vds 1'
        self.assertIn(property_line, generated)
        self.assertLess(generated.index(property_line),
                        generated.index('/system/bin/surfaceflinger &'))
        content_mode_property = (
            'setprop debug.aaas.display_content_mode_management 1')
        self.assertIn(content_mode_property, generated)
        self.assertLess(generated.index(content_mode_property),
                        generated.index('exec /system/bin/init second_stage'))
        self.assertNotIn('/metadata/aconfig', generated)
        self.assertIn('aflags list', generated)
        self.assertIn('debug.aaas.display_content_mode_management 1', generated)
        self.assertNotIn('aflags enable', generated)
        self.assertLess(generated.index('AAAS_DISPLAY_CONTENT_FLAG_UNAVAILABLE'),
                        generated.index('exec /system/bin/init second_stage'))

    def test_default_runner_does_not_enable_hwc_virtual_displays(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = SESSION.make_session_runner(Path(directory)).read_text()
        self.assertNotIn('debug.sf.enable_hwc_vds', generated)

    def test_virtual_display_has_private_input_route_to_android_display(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = SESSION.make_session_runner(
                Path(directory), experimental_virtual_display=True).read_text()
        launcher = SCRIPT.read_text()
        self.assertIn('input-vdisplay.sock', generated)
        self.assertIn('--socket /dev/aaas/input-vdisplay.sock', generated)
        self.assertIn('--display "$VD_ID"', generated)
        self.assertIn('grep -Fq hello', generated)
        self.assertIn('AAAS_VDISPLAY_INPUT_ADAPTER_NOT_READY', generated)
        self.assertIn('dumpsys activity activities', generated)
        self.assertIn('dumpsys window displays', generated)
        self.assertIn('dumpsys input', generated)
        self.assertIn('debuggerd -b "$BROKER_PID"', generated)
        self.assertIn('display_broker_shutdown', generated)
        self.assertIn('echo stop > /dev/aaas/display_broker_shutdown', generated)
        self.assertIn('AAAS_DISPLAY_BROKER_STOP_FAILED', generated)
        self.assertIn('!= released', generated)
        self.assertIn('!= "STOPPING"', generated)
        self.assertIn("'--input-display-id-file', str(ipc / 'vdisplay_id')", launcher)
        self.assertIn("'--input-socket', str(ipc / 'input-vdisplay.sock')", launcher)
        self.assertIn("write_status_sentinel(status, 'STOPPING')", launcher)

    def test_virtual_display_keyboard_focus_activates_its_android_task(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = SESSION.make_session_runner(
                Path(directory), experimental_virtual_display=True,
                app_package='com.android.settings', app_package2='com.android.deskclock'
            ).read_text()
        self.assertIn('--focus-request /dev/aaas/vdisplay_focus_1', generated)
        self.assertIn('--focus-ack /dev/aaas/vdisplay_focus_ack_1', generated)
        self.assertIn('--focus-request /dev/aaas/vdisplay_focus_2', generated)
        self.assertIn('--focus-ack /dev/aaas/vdisplay_focus_ack_2', generated)
        self.assertIn("f'vdisplay_focus_{index}'", SCRIPT.read_text())
        broker = (SCRIPT.parents[1] /
                  'experiments/m1e/display_broker/AaasDisplayBroker.java').read_text()
        self.assertIn('focusDisplayTask(handle)', broker)
        self.assertIn('"setFocusedTask"', broker)

    def test_virtual_display_broker_releases_owned_display_before_ack(self):
        broker = (SCRIPT.parents[1] / 'experiments/m1e/display_broker/AaasDisplayBroker.java').read_text()
        service = (SCRIPT.parents[1] / 'experiments/m1e/display_broker/aaas-display-broker.rc').read_text()
        self.assertIn('call(handle.virtualDisplay, "release"', broker)
        self.assertIn('call(handle.reader, "close"', broker)
        self.assertLess(broker.index('call(handle.virtualDisplay, "release"'),
                        broker.index('output.write((success ? "released'))
        self.assertIn('new FileOutputStream(handle.idPath, false)', broker)
        self.assertIn('createSecondDisplay', broker)
        self.assertIn('vdisplay2_id', service)
        self.assertIn('oneshot', service)

    def test_two_app_runner_creates_two_displays_and_task_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = SESSION.make_session_runner(
                Path(directory), experimental_virtual_display=True,
                app_package='com.android.settings', app_package2='com.android.deskclock'
            ).read_text()
        self.assertIn('vdisplay2_id', generated)
        self.assertIn('--socket /dev/aaas/input-vdisplay-2.sock', generated)
        self.assertIn('--log /aaas_vdisplay2_input_adapter.log', generated)
        self.assertIn('--bind "{vdisplay2_input_adapter_log}" '
                      '/aaas_vdisplay2_input_adapter.log', generated)
        self.assertIn('APP_COMPONENT2=', generated)
        self.assertIn('-p com.android.deskclock', generated)
        self.assertIn('start-activity -W --display "$VD_ID2"', generated)
        self.assertIn('aaas_app2_task_alive', generated)
        self.assertLess(
            generated.index('AAAS_ACTIVITY2_LAUNCH_OK'),
            generated.index('ADAPTER2_WAIT=0'),
            'the second display producer must start before its presenter can send HELLO',
        )

    def test_two_app_watch_keeps_shared_runtime_when_one_task_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = SESSION.make_session_runner(
                Path(directory), experimental_virtual_display=True,
                app_package='com.android.settings', app_package2='com.android.deskclock'
            ).read_text()
        self.assertIn('(aaas_app_task_alive || aaas_app2_task_alive)', generated)
        self.assertIn('echo CLOSED > /dev/aaas/app1_state', generated)
        self.assertIn('echo CLOSED > /dev/aaas/app2_state', generated)
        self.assertIn('! aaas_app_task_alive && ! aaas_app2_task_alive', generated)

    def test_two_output_session_handles_bounded_dynamic_relaunch_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = SESSION.make_session_runner(
                Path(directory), experimental_virtual_display=True,
                app_package='com.android.settings', app_package2='com.android.deskclock'
            ).read_text()
        self.assertIn('app1_launch_request', generated)
        self.assertIn('app2_launch_request', generated)
        self.assertIn('app1_launch_ack', generated)
        self.assertIn('app2_launch_ack', generated)
        self.assertIn('start-activity -W --display "$REQ_DISPLAY"', generated)
        self.assertIn('APP_PACKAGE2="$REQ_PACKAGE"', generated)
        self.assertIn('vdisplay_create_',
                      (SCRIPT.parents[1] /
                       'experiments/m1e/display_broker/AaasDisplayBroker.java').read_text())
        self.assertIn('created_after_release',
                      (SCRIPT.parents[1] /
                       'experiments/m1e/display_broker/AaasDisplayBroker.java').read_text())

    def test_dynamic_manager_has_bounded_control_operations(self):
        launcher = SCRIPT.read_text()
        control = (SCRIPT.parent / 'aaasctl.py').read_text()
        self.assertIn("control_server.bind(str(control_path))", launcher)
        self.assertIn("'capacity_exhausted'", launcher)
        self.assertIn("'capacity_requires_two_output_session'", launcher)
        for command in ('list', 'launch', 'close', 'stop'):
            self.assertIn(f"add_parser('{command}'", control)

    def test_resize_and_close_are_scoped_per_virtual_output(self):
        launcher = SCRIPT.read_text()
        broker = (SCRIPT.parents[1] / 'experiments/m1e/display_broker/AaasDisplayBroker.java').read_text()
        presenter = (SCRIPT.parents[1] / 'experiments/m1a/src/gpu_presenter.c').read_text()
        composer = (SCRIPT.parents[1] / 'experiments/m1b/composer_aaas/composer_service.cpp').read_text()
        self.assertIn("'--resize-request', str(ipc / 'vdisplay_resize_1')", launcher)
        self.assertIn("'--resize-request', str(ipc / 'vdisplay_resize_2')", launcher)
        self.assertIn('vdisplay_close_', broker)
        self.assertIn('call(handle.virtualDisplay, "resize"', broker)
        self.assertIn('call(handle.virtualDisplay, "setSurface"', broker)
        self.assertIn('oldWidth, oldHeight, handle.density', broker)
        self.assertIn('resize_rollback_failed', broker)
        self.assertIn('reportResizedMetrics', broker)
        self.assertIn('invoke(handle.handler, reportResizedMetrics, 500L)', broker)
        self.assertIn('requested=" + handle.width + "x"', broker)
        self.assertIn('a->pending_w = (uint32_t)w', presenter)
        self.assertIn('write_android_resize_request(a, w, h)', presenter)
        self.assertIn('virtual display resize observed', composer)

    def test_presenter_exposes_per_window_wayland_app_identity(self):
        host = (SCRIPT.parents[1] / 'experiments/m1a/src/wayland_host_presenter.c').read_text()
        gpu = (SCRIPT.parents[1] / 'experiments/m1a/src/gpu_presenter.c').read_text()
        self.assertIn('--app-id', host)
        self.assertIn('xdg_toplevel_set_app_id(app.toplevel, config->app_id)', gpu)

    def test_second_app_requires_a_distinct_package_and_virtual_display_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'differ'):
                SESSION.make_session_runner(
                    Path(directory), app_package='com.android.settings',
                    app_package2='com.android.settings', experimental_virtual_display=True)
            with self.assertRaisesRegex(ValueError, 'requires'):
                SESSION.make_session_runner(
                    Path(directory), app_package2='com.android.deskclock')

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
