"""Guard the diagnostic session's generated runner and mount isolation."""

import importlib.util
import json
from pathlib import Path
import shlex
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_aaas.py'
SPEC = importlib.util.spec_from_file_location('run_aaas', SCRIPT)
SESSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SESSION)


class DiagnosticOverlayManifestTests(unittest.TestCase):
    def _overlay_with_manifest(self, directory):
        import hashlib
        overlay = Path(directory) / 'swiftshader-trace.so'
        payload = b'diagnostic shared object fixture'
        overlay.write_bytes(payload)
        manifest = {
            'schema_version': 1,
            'source_revision': 'cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5',
            'output': {
                'sha256': hashlib.sha256(payload).hexdigest(),
                'build_id': 'aabbcc',
            },
        }
        Path(str(overlay) + '.manifest.json').write_text(json.dumps(manifest))
        return overlay

    def test_accepts_pinned_manifest_and_matching_hash_and_build_id(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = self._overlay_with_manifest(directory)
            with patch.object(SESSION, 'TMP', Path(directory)), \
                    patch.object(SESSION.subprocess, 'run', return_value=SESSION.subprocess.CompletedProcess(
                        ['readelf'], 0, stdout='Build ID: aabbcc\n')):
                self.assertEqual(SESSION.validate_diagnostic_vulkan_overlay(overlay), overlay)

    def test_rejects_stale_overlay_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = self._overlay_with_manifest(directory)
            overlay.write_bytes(b'changed after manifest')
            with patch.object(SESSION, 'TMP', Path(directory)):
                with self.assertRaisesRegex(ValueError, 'hash does not match'):
                    SESSION.validate_diagnostic_vulkan_overlay(overlay)

    def test_rejects_unpinned_source_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = self._overlay_with_manifest(directory)
            manifest_path = Path(str(overlay) + '.manifest.json')
            manifest = json.loads(manifest_path.read_text())
            manifest['source_revision'] = 'other'
            manifest_path.write_text(json.dumps(manifest))
            with patch.object(SESSION, 'TMP', Path(directory)):
                with self.assertRaisesRegex(ValueError, 'source revision'):
                    SESSION.validate_diagnostic_vulkan_overlay(overlay)

    def test_rejects_overlay_outside_workspace_tmp(self):
        with tempfile.TemporaryDirectory() as directory, \
                tempfile.TemporaryDirectory() as other:
            overlay = self._overlay_with_manifest(other)
            with patch.object(SESSION, 'TMP', Path(directory)):
                with self.assertRaisesRegex(ValueError, 'inside the AaaS workspace tmp'):
                    SESSION.validate_diagnostic_vulkan_overlay(overlay)


class NativeBridgeOverlayTests(unittest.TestCase):
    def _bundle(self, root):
        import hashlib
        bundle = Path(root) / 'bundle'
        required = {
            'system/lib64/libberberis_arm64.so': b'host translator',
            'system/lib64/libberberis_exec_region.so': b'exec region',
            'system/etc/ld.config.arm64.txt': b'guest linker config',
            'system/lib64/arm64/libc.so': b'guest libc',
        }
        for index in range(70):
            required[f'system/lib64/libproxy{index}.so'] = f'proxy {index}'.encode()
        lines = []
        for name, data in sorted(required.items()):
            path = bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            lines.append(f'{hashlib.sha256(data).hexdigest()}  {name}')
        (bundle / 'SHA256SUMS').write_text('\n'.join(lines) + '\n')
        (bundle / 'MANIFEST.txt').write_text('fixture\n')
        return bundle

    def test_validates_and_builds_session_local_hardlink_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            base = root / 'rootfs/rootfs_m1b1/system'
            for subtree in ('bin', 'etc', 'lib64'):
                (base / subtree).mkdir(parents=True)
                (base / subtree / 'base-file').write_text('base')
            (base / 'build.prop').write_text(
                'ro.dalvik.vm.native.bridge=0\nro.product.cpu.abi=x86_64\n')
            session = root / 'session'
            session.mkdir()
            with patch.object(SESSION, 'TMP', root), \
                    patch.object(SESSION, 'WORKSPACE', root / 'rootfs'):
                verified_bundle, entries = SESSION.validate_native_bridge_bundle(bundle)
                overlay = SESSION.prepare_native_bridge_overlay(
                    verified_bundle, entries, session)
                generated = SESSION.make_session_runner(
                    session, experimental_virtual_display=True,
                    native_bridge_overlay=overlay).read_text()
            props = (overlay / 'system/build.prop').read_text()
            self.assertIn('ro.dalvik.vm.native.bridge=libberberis_arm64.so', props)
            self.assertIn('ro.product.cpu.abilist=x86_64,arm64-v8a', props)
            self.assertIn('ro.enable.native.bridge.exec=0', props)
            self.assertIn(f'--ro-bind "{overlay / "system/lib64"}" /system/lib64', generated)
            self.assertTrue((overlay / 'system/lib64/libberberis_arm64.so').is_file())
            self.assertEqual((base / 'build.prop').read_text(),
                             'ro.dalvik.vm.native.bridge=0\nro.product.cpu.abi=x86_64\n')

    def test_arm64_first_abi_order_is_opt_in_and_session_local(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            base = root / 'rootfs/rootfs_m1b1/system'
            for subtree in ('bin', 'etc', 'lib64'):
                (base / subtree).mkdir(parents=True)
            (base / 'build.prop').write_text('ro.product.cpu.abi=x86_64\n')
            session = root / 'session'
            session.mkdir()
            with patch.object(SESSION, 'TMP', root), \
                    patch.object(SESSION, 'WORKSPACE', root / 'rootfs'):
                verified, entries = SESSION.validate_native_bridge_bundle(bundle)
                overlay = SESSION.prepare_native_bridge_overlay(
                    verified, entries, session, arm64_first=True)
            props = (overlay / 'system/build.prop').read_text()
            self.assertIn('ro.product.cpu.abilist=arm64-v8a,x86_64', props)
            self.assertIn('ro.product.cpu.abilist64=arm64-v8a,x86_64', props)
            self.assertIn('ro.product.cpu.abi=x86_64', props)
            self.assertEqual((base / 'build.prop').read_text(), 'ro.product.cpu.abi=x86_64\n')

    def test_rejects_checksum_mismatch_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self._bundle(directory)
            with patch.object(SESSION, 'TMP', Path(directory)):
                artifact = bundle / 'system/lib64/libberberis_arm64.so'
                artifact.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    SESSION.validate_native_bridge_bundle(bundle)


class DiagnosticApkNativeLibraryTests(unittest.TestCase):
    @staticmethod
    def _elf64_arm64():
        data = bytearray(20)
        data[:6] = b'\x7fELF\x02\x01'
        data[18:20] = (183).to_bytes(2, 'little')
        return bytes(data)

    def test_stages_compressed_arm64_library_in_system_app_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apk = root / 'third-party.apk'
            payload = self._elf64_arm64()
            with zipfile.ZipFile(apk, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('lib/arm64-v8a/libmain.so', payload)
            staged, manifest = SESSION.prepare_diagnostic_apk_native_libraries(
                apk, root / 'session', 'AaasLatencyProbe')
            library = staged / 'arm64/libmain.so'
            self.assertEqual(library.read_bytes(), payload)
            self.assertEqual(manifest['libraries'][0]['apk_entry'],
                             'lib/arm64-v8a/libmain.so')
            self.assertEqual(manifest['source_apk_sha256'], SESSION.sha256(apk))

    def test_rejects_path_traversal_and_elf_abi_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apk = root / 'bad.apk'
            with zipfile.ZipFile(apk, 'w') as archive:
                archive.writestr('lib/arm64-v8a/../libmain.so', self._elf64_arm64())
            with self.assertRaisesRegex(ValueError, 'unsafe or unsupported'):
                SESSION.prepare_diagnostic_apk_native_libraries(
                    apk, root / 'session', 'AaasLatencyProbe')
            apk2 = root / 'bad-elf.apk'
            wrong_arch = bytearray(self._elf64_arm64())
            wrong_arch[18:20] = (62).to_bytes(2, 'little')
            with zipfile.ZipFile(apk2, 'w') as archive:
                archive.writestr('lib/arm64-v8a/libmain.so', wrong_arch)
            with self.assertRaisesRegex(ValueError, 'ABI/ELF mismatch'):
                SESSION.prepare_diagnostic_apk_native_libraries(
                    apk2, root / 'session2', 'AaasLatencyProbe')
                sums = bundle / 'SHA256SUMS'
                sums.write_text(sums.read_text().replace('system/lib64/libberberis_arm64.so',
                                                         'system/../../unsafe'))
                with self.assertRaisesRegex(ValueError, 'unsafe'):
                    SESSION.validate_native_bridge_bundle(bundle)

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
        self.assertIn('    ) &\n    (\n      /system/bin/toybox umask 077', generated)
        self.assertIn('    exec /system/bin/init second_stage', generated)
        self.assertNotIn('/system/bin/init second_stage &', generated)
        self.assertIn('    echo RUNNING > /aaas_session_status', generated)

    def test_runner_binds_persistent_shared_storage_and_starts_storaged(self):
        with tempfile.TemporaryDirectory(prefix='aaas storage ') as directory:
            root = Path(directory)
            shared = root / 'persistent' / 'android-media' / '0'
            shared.mkdir(parents=True)
            session = root / 'session'
            session.mkdir()
            generated = SESSION.make_session_runner(
                session, shared_storage_dir=shared).read_text()
        self.assertIn('--dir /data/media', generated)
        self.assertIn(f'--bind {shlex.quote(str(shared.parent))} /data/media',
                      generated)
        self.assertLess(generated.index('--tmpfs /data'),
                        generated.index('{shared_storage_bind}'))
        self.assertIn('{fuse_bind}  --dev-bind /dev/dri /dev/dri', generated)
        self.assertLess(generated.index('/system/bin/start storaged'),
                        generated.index('/system/bin/start vold'))
        self.assertIn('/system/bin/sm mount "emulated;0"', generated)
        self.assertNotIn('aaas-storage-android-to-host.txt', generated)
        self.assertNotIn('aaas-storage-host-to-android.txt', generated)

    def test_runner_mounts_verified_bluetooth_unavailable_policy_before_init(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rootfs = root / 'rootfs'
            policy = root / 'bluetooth-policy'
            self._make_bluetooth_rootfs(rootfs)
            SESSION.aaas_bluetooth.create_unavailable_policy(rootfs, policy)
            generated_path = SESSION.make_session_runner(
                root, bluetooth_policy_dir=policy)
            generated = generated_path.read_text()
            compiled = __import__('subprocess').run(
                [__import__('sys').executable, '-m', 'py_compile', str(generated_path)],
                capture_output=True, text=True,
            )
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        self.assertIn('--ro-bind "', generated)
        self.assertIn('/vendor/etc/permissions/handheld_core_hardware.xml', generated)
        self.assertIn('/vendor/etc/init/bluetooth-service-default.rc', generated)
        self.assertIn('/vendor/etc/vintf/manifest/bluetooth-service-default.xml', generated)
        self.assertIn('/vendor/etc/init/hw/init.ranchu.rc', generated)
        self.assertLess(generated.index('/vendor/etc/init/bluetooth-service-default.rc'),
                        generated.index('exec /system/bin/init second_stage'))

    @staticmethod
    def _make_bluetooth_rootfs(root):
        for relative, body in {
            'vendor/etc/permissions/handheld_core_hardware.xml': (
                '<permissions><feature name="android.hardware.bluetooth" />'
                '<feature name="android.hardware.bluetooth_le" />'
                '<feature name="android.hardware.touchscreen" /></permissions>'),
            'vendor/etc/permissions/android.hardware.bluetooth.xml': (
                '<permissions><feature name="android.hardware.bluetooth" /></permissions>'),
            'vendor/etc/permissions/android.hardware.bluetooth_le.xml': (
                '<permissions><feature name="android.hardware.bluetooth_le" /></permissions>'),
            SESSION.aaas_bluetooth.HAL_INIT: 'service vendor.bluetooth-default /bin/false\n',
            SESSION.aaas_bluetooth.HAL_MANIFEST: (
                '<manifest version="9.0" type="device"><hal><name>android.hardware.bluetooth'
                '</name></hal></manifest>'),
            SESSION.aaas_bluetooth.RANCHU_INIT: (
                'on property:vendor.qemu.vport.bluetooth=*\n'
                '    symlink ${vendor.qemu.vport.bluetooth} /dev/bluetooth0\n\n'
                'service bt_vhci_forwarder /vendor/bin/bt_vhci_forwarder -virtio_console_dev=/dev/bluetooth0\n'
                '    class main\n    user bluetooth\n    group root bluetooth\n\n'
                'on property:vendor.qemu.vport.uwb=*\n    start vendor.uwb_hal\n'),
        }.items():
            path = Path(root) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)

    def test_runner_exports_stable_tombstones_before_android_teardown(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            generated_path = SESSION.make_session_runner(
                Path(directory), experimental_virtual_display=True,
                app_package2='com.android.contacts')
            generated = generated_path.read_text()
            compiled = subprocess.run(
                [sys.executable, '-m', 'py_compile', str(generated_path)],
                capture_output=True, text=True,
            )
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        self.assertIn('aaas_export_stable_tombstones()', generated)
        self.assertIn("stat -c '%s:%y'", generated)
        self.assertIn('tombstone_capture_request', generated)
        self.assertIn('tombstone_capture_ack', generated)
        self.assertIn('chmod 0600', generated)
        self.assertIn('AAAS_FRAMEWORK_DEATH service=surfaceflinger', generated)
        self.assertIn('AAAS_BROKER_UNAVAILABLE_AFTER_FRAMEWORK_DEATH', generated)
        self.assertIn('AAAS_SURFACEFLINGER_INITIAL_PID', generated)
        self.assertIn('tombstone_capture_test_result', generated)
        self.assertIn('Cmdline: /system/bin/surfaceflinger', generated)
        self.assertIn('tombstone_capture_test_pid', generated)
        self.assertIn('pid: $test_pid,', generated)
        self.assertIn('os.chmod(tombstone_dir, 0o700)', generated)

    def test_app_tombstone_export_is_explicit_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'limited').mkdir()
            (root / 'expanded').mkdir()
            limited = SESSION.make_session_runner(
                root / 'limited', experimental_virtual_display=True).read_text()
            expanded = SESSION.make_session_runner(
                root / 'expanded', experimental_virtual_display=True,
                capture_app_tombstones=True).read_text()
        self.assertIn('Cmdline: /system/bin/surfaceflinger', limited)
        self.assertNotIn('Cmdline: /system/bin/surfaceflinger', expanded)
        self.assertIn('os.chmod(tombstone_dir, 0o700)', expanded)
        self.assertIn('chmod 0600', expanded)

    def test_failure_classifier_ignores_framework_death_command_source(self):
        with tempfile.TemporaryDirectory() as directory:
            command_log = Path(directory) / 'commands.log'
            command_log.write_text(
                '      echo "AAAS_FRAMEWORK_DEATH service=surfaceflinger" '
                '>> /aaas_session_commands\n'
                'Android app com.android.settings did not become ready\n'
            )
            self.assertEqual(
                SESSION.classify_session_failure(command_log),
                'runtime_or_control_failure',
            )

    def test_failure_classifier_recognizes_emitted_surfaceflinger_death(self):
        with tempfile.TemporaryDirectory() as directory:
            command_log = Path(directory) / 'commands.log'
            command_log.write_text(
                'AAAS_FRAMEWORK_DEATH service=surfaceflinger '
                'initial=237 current=\n'
            )
            self.assertEqual(
                SESSION.classify_session_failure(command_log),
                'surfaceflinger_died',
            )

    def test_crash_manifest_records_missing_tombstone_without_fabrication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / 'session'
            export = root / 'tombstones'
            session.mkdir()
            export.mkdir(mode=0o700)
            manifest = SESSION.write_crash_artifact_manifest(
                session, export, capture_status='complete')
            self.assertEqual(manifest['artifact_state'], 'missing')
            self.assertEqual(manifest['files'], [])
            self.assertEqual(json.loads(
                (session / 'crash-artifact-manifest.json').read_text()), manifest)

    def test_crash_manifest_hashes_exported_regular_files(self):
        import hashlib
        import json

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / 'session'
            export = root / 'tombstones'
            session.mkdir()
            export.mkdir(mode=0o700)
            content = b'bounded synthetic tombstone fixture\n'
            (export / 'tombstone_00').write_bytes(content)
            manifest = SESSION.write_crash_artifact_manifest(
                session, export, capture_status='complete')
            self.assertEqual(manifest['artifact_state'], 'captured')
            self.assertEqual(manifest['files'], [{
                'name': 'tombstone_00', 'size_bytes': len(content),
                'sha256': hashlib.sha256(content).hexdigest(),
            }])
            self.assertEqual((session / 'crash-artifact-manifest.json').stat().st_mode & 0o777,
                             0o600)

    def test_crash_manifest_keeps_missing_presenter_ownership_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / 'session'
            export = session / 'tombstones'
            session.mkdir()
            export.mkdir(mode=0o700)
            manifest = SESSION.write_crash_artifact_manifest(
                session, export, capture_status='timeout')
            states = [record['state'] for record in
                      manifest['presenter_terminal_ownership']]
            self.assertEqual(states, ['unknown', 'unknown', 'unknown'])
            self.assertTrue(all(record['summary'] is None for record in
                                manifest['presenter_terminal_ownership']))

    def test_tombstone_capture_timeout_is_bounded_and_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            ipc = Path(directory)
            (ipc / 'tombstone_capture_request').write_text('')
            (ipc / 'tombstone_capture_ack').write_text('')
            started = time.monotonic()
            result = SESSION.request_tombstone_capture(ipc, timeout=.05)
            elapsed = time.monotonic() - started
            self.assertEqual(result, 'timeout')
            self.assertLess(elapsed, .5)
            self.assertEqual((ipc / 'tombstone_capture_request').read_text(), 'stop\n')

    def test_tombstone_capture_waits_for_bounded_export_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            ipc = Path(directory)
            request = ipc / 'tombstone_capture_request'
            ack = ipc / 'tombstone_capture_ack'
            request.write_text('')
            ack.write_text('')

            def acknowledge():
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    if request.read_text().strip() == 'stop':
                        time.sleep(.08)
                        ack.write_text('complete\n')
                        return
                    time.sleep(.005)

            worker = threading.Thread(target=acknowledge)
            worker.start()
            self.assertEqual(SESSION.request_tombstone_capture(ipc, timeout=.5),
                             'complete')
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())

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

    def test_runner_binds_latency_probe_apks_only_when_explicitly_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / 'probe.apk'
            second = root / 'probe2.apk'
            with zipfile.ZipFile(first, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('lib/arm64-v8a/libfirst.so',
                                 DiagnosticApkNativeLibraryTests._elf64_arm64())
            with zipfile.ZipFile(second, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('lib/arm64-v8a/libsecond.so',
                                 DiagnosticApkNativeLibraryTests._elf64_arm64())
            default_root = root / 'default'
            diagnostic_root = root / 'diagnostic'
            default_root.mkdir()
            diagnostic_root.mkdir()
            default = SESSION.make_session_runner(default_root).read_text()
            generated = SESSION.make_session_runner(
                diagnostic_root, app_package='org.example.probe',
                app_package2='org.example.probe2',
                experimental_virtual_display=True,
                input_response_probe_apk=first,
                input_response_probe_apk2=second).read_text()
        self.assertNotIn('AaasLatencyProbe', default)
        self.assertIn(f'--ro-bind "{first.resolve()}" '
                      '/product/app/AaasLatencyProbe/AaasLatencyProbe.apk', generated)
        self.assertIn(f'--ro-bind "{second.resolve()}" '
                      '/product/app/AaasLatencyProbe2/AaasLatencyProbe2.apk', generated)
        self.assertIn('--ro-bind "' + str(diagnostic_root / 'diagnostic-apk-native-libs' /
                                           'AaasLatencyProbe') + '" '
                      '/product/app/AaasLatencyProbe/lib', generated)
        self.assertLess(generated.index('--bind "{rootfs}" /'),
                        generated.index('--dir /product/app/AaasLatencyProbe'))

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

    def test_android_keyboard_focus_ack_waits_for_inputdispatcher_window(self):
        broker = (SCRIPT.parents[1] /
                  'experiments/m1e/display_broker/AaasDisplayBroker.java').read_text()
        focus = broker[broker.index('private static int focusDisplayTask('):
                       broker.index('private static String readInputDispatcherFocusedWindows(')]
        self.assertLess(focus.index('"setFocusedTask"'),
                        focus.index('awaitInputFocusedWindow('))
        self.assertIn('FocusedWindows:', broker)
        self.assertIn('"displayId=" + displayId + ", name=\'"', broker)
        self.assertIn('hasInputFocusedWindow(focused, displayId)', broker)
        self.assertIn('focus_input_window_timeout', broker)
        self.assertIn('"unfocused " + focusFields[0]', broker)
        adapter = (SCRIPT.parents[1] /
                   'experiments/m1c/input_adapter/aaas_input_adapter.c').read_text()
        self.assertIn('3000000000ULL', adapter)
        self.assertIn('strncmp(cursor, "unfocused ", 10)', adapter)
        self.assertIn('android_display_focus_rejected', adapter)

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
        self.assertIn('AAAS_IDLE_TIMEOUT_SECONDS=60', generated)
        self.assertIn('while [ "$(/system/bin/getprop sys.boot_completed)" = "1" ]', generated)
        self.assertIn('AAAS_IDLE_STARTED timeout=$AAAS_IDLE_TIMEOUT_SECONDS', generated)
        self.assertIn('AAAS_IDLE_TIMEOUT_REACHED', generated)
        self.assertIn('if aaas_app_task_alive || aaas_app2_task_alive; then AAAS_IDLE_SINCE=0',
                      generated)
        self.assertIn('echo CLOSED > /dev/aaas/app1_state', generated)
        self.assertIn('echo CLOSED > /dev/aaas/app2_state', generated)
        self.assertIn('! aaas_app_task_alive && ! aaas_app2_task_alive', generated)

    def test_idle_timeout_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'between 1 and 3600'):
                SESSION.make_session_runner(Path(directory), idle_timeout_seconds=0)
            generated = SESSION.make_session_runner(
                Path(directory), experimental_virtual_display=True,
                app_package='com.android.settings', app_package2='com.android.deskclock',
                idle_timeout_seconds=2
            ).read_text()
        self.assertIn('AAAS_IDLE_TIMEOUT_SECONDS=2', generated)

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
        self.assertIn('app1_stop_request', generated)
        self.assertIn('app2_stop_request', generated)
        self.assertIn('app2_forced_closed', generated)
        self.assertIn('cmd activity force-stop --user 0 "$STOP_PACKAGE"', generated)
        self.assertIn('cmd activity stack remove "$STOP_TASK_ID"', generated)
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
        for command in ('list', 'launch', 'close', 'stop-app', 'stop'):
            self.assertIn(f"add_parser('{command}'", control)

    def test_dynamic_presenter_clears_previous_resize_before_reopen(self):
        launcher = SCRIPT.read_text()
        start = launcher.index('    def start_dynamic_presenter(')
        end = launcher.index('    def manager_request(', start)
        dynamic_start = launcher[start:end]
        clear = dynamic_start.index("resize_path.write_text('')")
        spawn = dynamic_start.index('subprocess.Popen(')
        self.assertLess(clear, spawn)

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
        self.assertIn('a->pending_w = (uint32_t)width', presenter)
        self.assertIn('aaas_resize_schedule(&a->resize_scheduler', presenter)
        self.assertIn('flush_scheduled_android_resize(&app)', presenter)
        self.assertIn('write_android_resize_request(a, a->w, a->h)', presenter)
        self.assertIn('virtual display resize observed', composer)

    def test_presenter_exposes_per_window_wayland_app_identity(self):
        host = (SCRIPT.parents[1] / 'experiments/m1a/src/wayland_host_presenter.c').read_text()
        gpu = (SCRIPT.parents[1] / 'experiments/m1a/src/gpu_presenter.c').read_text()
        self.assertIn('--app-id', host)
        self.assertIn('libdecor_frame_set_app_id(app.decor_frame, config->app_id)', gpu)

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
