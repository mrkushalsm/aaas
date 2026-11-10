import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_cli
import aaas_dev


class DeveloperProfileTests(unittest.TestCase):
    def test_developer_commands_are_explicit_and_separate_from_production_start(self):
        args = aaas_cli._parser().parse_args(['dev', 'start', '--audio'])
        self.assertEqual(args.command, 'dev')
        self.assertEqual(args.dev_command, 'start')
        self.assertTrue(args.audio)
        production = aaas_cli._parser().parse_args(['start'])
        self.assertEqual(production.command, 'start')

    def test_signing_key_is_generated_once_with_private_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)

            def keytool(command, **kwargs):
                if '-genkeypair' in command:
                    path = Path(command[command.index('-keystore') + 1])
                    path.write_bytes(b'fresh private development key')
                return subprocess.CompletedProcess(command, 0, '', '')

            with patch.object(aaas_dev.subprocess, 'run', side_effect=keytool) as run:
                first = aaas_dev.ensure_signing_key(state)
                self.assertEqual(first, state / 'signing/storage-probe.keystore')
                self.assertEqual(first.stat().st_mode & 0o777, 0o600)
                second = aaas_dev.ensure_signing_key(state)
            self.assertEqual(first, second)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[0].args[0][0], 'keytool')

    def test_existing_group_readable_signing_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / 'signing/storage-probe.keystore'
            key.parent.mkdir(parents=True)
            key.write_bytes(b'key')
            key.chmod(0o644)
            with self.assertRaisesRegex(aaas_dev.DeveloperRuntimeError, 'unsafe ownership or mode'):
                aaas_dev.ensure_signing_key(Path(temporary))

    def test_legacy_workspace_signer_migrates_without_changing_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / 'workspace/storage-probe.keystore'
            legacy.parent.mkdir()
            legacy.write_bytes(b'prior signer')
            legacy.chmod(0o600)

            def keytool(command, **kwargs):
                return subprocess.CompletedProcess(command, 0, '', '')

            with patch.object(aaas_dev.subprocess, 'run', side_effect=keytool):
                migrated = aaas_dev.ensure_signing_key(root / 'state', legacy)
            self.assertEqual(migrated.read_bytes(), b'prior signer')
            self.assertEqual(migrated.stat().st_mode & 0o777, 0o600)
            self.assertEqual(legacy.read_bytes(), b'prior signer')


if __name__ == '__main__':
    unittest.main()
