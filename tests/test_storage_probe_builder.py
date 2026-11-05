import contextlib
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.m4.shared_storage_probe import build_probe


class StorageProbeBuilderTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
