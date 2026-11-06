import contextlib
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.m4.shared_storage_probe import build_probe
from experiments.perf.input_latency_probe.build_probe import binary_manifest


class StorageProbeBuilderTests(unittest.TestCase):
    def test_launcher_package_visibility_is_limited_to_launcher_intents(self):
        manifest = binary_manifest('org.aaas.catalogprobe', target_sdk=35)
        self.assertIn(b'queries', manifest)
        self.assertIn(b'android.intent.action.MAIN', manifest)
        self.assertIn(b'android.intent.category.LAUNCHER', manifest)
        self.assertNotIn(b'QUERY_ALL_PACKAGES', manifest)

    def test_custom_package_is_written_to_the_apk_manifest(self):
        package = 'org.aaas.acceptance.unique'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apktool = root / 'apktool.jar'
            keystore = root / 'probe.keystore'
            apksig = root / 'apksig.jar'
            output = root / 'probe.apk'
            for path in (apktool, keystore, apksig):
                path.write_bytes(b'fixture')

            def run(command):
                if command[1:4] == ['-jar', str(apktool), 'b']:
                    work = Path(command[-1])
                    dex = work / 'build/apk/classes.dex'
                    dex.parent.mkdir(parents=True)
                    dex.write_bytes(b'dex fixture')
                elif command[0] == 'java' and 'ApkSign' in command:
                    shutil.copyfile(command[-2], command[-1])
                elif command[0] == 'java':
                    self.fail(f'unexpected Java command: {command}')

            argv = [
                'build_probe.py', '--apktool', str(apktool), '--keystore', str(keystore),
                '--apksig', str(apksig), '--package', package, '--target-sdk', '35',
                '--output', str(output),
            ]
            with patch.object(sys, 'argv', argv), \
                    patch.object(build_probe, 'run', side_effect=run), \
                    patch.object(build_probe, 'binary_manifest', return_value=b'manifest') as manifest, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build_probe.main(), 0)

            self.assertEqual(manifest.call_args.args[0], package)
            self.assertTrue(output.is_file())

    def test_persisted_grant_revocation_diagnostic_is_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apktool = root / 'apktool.jar'
            keystore = root / 'probe.keystore'
            apksig = root / 'apksig.jar'
            dx = root / 'dx.jar'
            output = root / 'probe.apk'
            for path in (apktool, keystore, apksig, dx):
                path.write_bytes(b'fixture')
            compiled_sources = []

            def run(command):
                if command[1:4] == ['-jar', str(apktool), 'b']:
                    work = Path(command[-1])
                    dex = work / 'build/apk/classes.dex'
                    dex.parent.mkdir(parents=True)
                    dex.write_bytes(b'dex fixture')
                elif command[0] == 'javac':
                    source = Path(command[-1])
                    compiled_sources.append(source.read_text())
                elif command[0] == 'java' and 'ApkSign' in command:
                    shutil.copyfile(command[-2], command[-1])
                elif command[0] == 'java' and 'com.android.dx.command.Main' in command:
                    output_arg = next(arg for arg in command if arg.startswith('--output='))
                    Path(output_arg.split('=', 1)[1]).write_bytes(b'dex fixture')
                else:
                    self.fail(f'unexpected command: {command}')

            argv = [
                'build_probe.py', '--apktool', str(apktool), '--keystore', str(keystore),
                '--apksig', str(apksig), '--dx', str(dx), '--package',
                'org.aaas.storagetest', '--target-sdk', '35', '--userdata-diagnostics',
                '--release-persisted-grants-on-launch', '--output', str(output),
            ]
            with patch.object(sys, 'argv', argv), \
                    patch.object(build_probe, 'run', side_effect=run), \
                    patch.object(build_probe, 'binary_manifest', return_value=b'manifest'), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build_probe.main(), 0)

            helper = next(source for source in compiled_sources
                          if 'RELEASE_PERSISTED_GRANTS = true' in source)
            self.assertIn('PERSISTED_GRANT_READ_AFTER_RUNTIME_RESTART', helper)
            self.assertIn('aaas-saf-revocation-uri.txt', helper)
            self.assertTrue(output.is_file())

    def test_runtime_media_permission_probe_builds_api_query_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apktool = root / 'apktool.jar'
            keystore = root / 'probe.keystore'
            apksig = root / 'apksig.jar'
            dx = root / 'dx.jar'
            output = root / 'probe.apk'
            for path in (apktool, keystore, apksig, dx):
                path.write_bytes(b'fixture')
            compiled_sources = []

            def run(command):
                if command[1:4] == ['-jar', str(apktool), 'b']:
                    work = Path(command[-1])
                    dex = work / 'build/apk/classes.dex'
                    dex.parent.mkdir(parents=True)
                    dex.write_bytes(b'dex fixture')
                elif command[0] == 'javac':
                    source = Path(command[-1])
                    compiled_sources.append(source.read_text())
                elif command[0] == 'java' and 'ApkSign' in command:
                    shutil.copyfile(command[-2], command[-1])
                elif command[0] == 'java' and 'com.android.dx.command.Main' in command:
                    output_arg = next(arg for arg in command if arg.startswith('--output='))
                    Path(output_arg.split('=', 1)[1]).write_bytes(b'dex fixture')
                else:
                    self.fail(f'unexpected command: {command}')

            argv = [
                'build_probe.py', '--apktool', str(apktool), '--keystore', str(keystore),
                '--apksig', str(apksig), '--dx', str(dx), '--package',
                'org.aaas.permissionprobe', '--target-sdk', '35', '--userdata-diagnostics',
                '--request-media-permission-on-launch', '--output', str(output),
            ]
            with patch.object(sys, 'argv', argv), \
                    patch.object(build_probe, 'run', side_effect=run), \
                    patch.object(build_probe, 'binary_manifest', return_value=b'manifest'), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build_probe.main(), 0)

            helper = next(source for source in compiled_sources
                          if 'REQUEST_MEDIA_PERMISSION = true' in source)
            self.assertIn('MEDIA_IMAGE_QUERY checkpoint=', helper)
            self.assertIn('READ_MEDIA_IMAGES', helper)
            self.assertIn('reportMediaPermissionResult',
                          (Path(build_probe.__file__).parent / 'smali-open' /
                           'org/aaas/latencyprobe/ProbeActivity.smali').read_text())
            builder_source = Path(build_probe.__file__).read_text()
            self.assertIn("text = text.replace(call, call + '    return-void\\n', 1)",
                          builder_source)

    def test_runtime_media_permission_request_requires_userdata_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apktool = root / 'apktool.jar'
            keystore = root / 'probe.keystore'
            output = root / 'probe.apk'
            for path in (apktool, keystore):
                path.write_bytes(b'fixture')
            argv = [
                'build_probe.py', '--apktool', str(apktool), '--keystore', str(keystore),
                '--output', str(output), '--request-media-permission-on-launch',
            ]
            with patch.object(sys, 'argv', argv), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    build_probe.main()
            self.assertEqual(error.exception.code, 2)

    def test_symlink_probe_bakes_shared_path_and_content_resolver_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apktool = root / 'apktool.jar'
            keystore = root / 'probe.keystore'
            apksig = root / 'apksig.jar'
            dx = root / 'dx.jar'
            output = root / 'probe.apk'
            for path in (apktool, keystore, apksig, dx):
                path.write_bytes(b'fixture')
            compiled_sources = []

            def run(command):
                if command[1:4] == ['-jar', str(apktool), 'b']:
                    work = Path(command[-1])
                    dex = work / 'build/apk/classes.dex'
                    dex.parent.mkdir(parents=True)
                    dex.write_bytes(b'dex fixture')
                elif command[0] == 'javac':
                    compiled_sources.append(Path(command[-1]).read_text())
                elif command[0] == 'java' and 'ApkSign' in command:
                    shutil.copyfile(command[-2], command[-1])
                elif command[0] == 'java' and 'com.android.dx.command.Main' in command:
                    output_arg = next(arg for arg in command if arg.startswith('--output='))
                    Path(output_arg.split('=', 1)[1]).write_bytes(b'dex fixture')
                else:
                    self.fail(f'unexpected command: {command}')

            probe_dir = '/storage/emulated/0/Documents/AaasSymlinkFixture'
            argv = [
                'build_probe.py', '--apktool', str(apktool), '--keystore', str(keystore),
                '--apksig', str(apksig), '--dx', str(dx), '--package',
                'org.aaas.symlinkprobe', '--target-sdk', '35', '--userdata-diagnostics',
                '--symlink-probe-dir', probe_dir, '--output', str(output),
            ]
            with patch.object(sys, 'argv', argv), \
                    patch.object(build_probe, 'run', side_effect=run), \
                    patch.object(build_probe, 'binary_manifest', return_value=b'manifest'), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build_probe.main(), 0)

            helper = next(source for source in compiled_sources
                          if 'SYMLINK_PROBE_DIR' in source)
            self.assertIn('SYMLINK_PROBE_DIR = "' + probe_dir + '"', helper)
            self.assertIn('APP_SYMLINK_OPEN name=', helper)
            self.assertIn('APP_SYMLINK_CONTENT_RESOLVER name=', helper)
            self.assertIn('APP_SYMLINK_MEDIASTORE rows=', helper)
            self.assertTrue(output.is_file())


if __name__ == '__main__':
    unittest.main()
