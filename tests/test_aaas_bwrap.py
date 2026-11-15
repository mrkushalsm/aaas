from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_bwrap
import aaas_session_runner_base


class BubblewrapResolutionTests(unittest.TestCase):
    def test_user_path_wrapper_cannot_hijack_normal_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user_bin = root / 'user-bin'
            system_bin = root / 'system-bin'
            user_bin.mkdir()
            system_bin.mkdir()
            wrapper = user_bin / 'bwrap'
            wrapper.write_text('#!/bin/sh\necho traced wrapper\n')
            wrapper.chmod(0o755)
            actual = system_bin / 'bwrap'
            actual.write_bytes(b'\x7fELFtest binary')
            actual.chmod(0o755)
            help_result = type('Result', (), {
                'returncode': 0,
                'stdout': ' '.join(aaas_bwrap.REQUIRED_OPTIONS),
                'stderr': '',
            })()
            with patch.object(aaas_bwrap, 'SYSTEM_SEARCH_PATH', str(system_bin)), \
                    patch.object(aaas_bwrap.subprocess, 'run', return_value=help_result) as run:
                selected = aaas_bwrap.resolve_bwrap({'PATH': str(user_bin)})
                command = aaas_session_runner_base.bubblewrap_shell_command(
                    {'PATH': str(user_bin)})
            self.assertEqual(selected, actual.resolve())
            self.assertEqual(run.call_args.args[0][0], str(actual.resolve()))
            self.assertEqual(command, str(actual.resolve()))

    def test_explicit_bwrap_override_must_be_absolute_and_compatible(self):
        with self.assertRaisesRegex(aaas_bwrap.BubblewrapError, 'absolute path'):
            aaas_bwrap.resolve_bwrap({'AAAS_BWRAP': 'bwrap'})

    def test_diagnostic_wrapper_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            wrapper = Path(temporary) / 'bwrap-trace'
            wrapper.write_text('#!/bin/sh\nexec /usr/bin/strace "$@"\n')
            wrapper.chmod(0o755)
            selected = aaas_bwrap.resolve_bwrap(
                {'AAAS_BWRAP_TRACE_WRAPPER': str(wrapper)})
            self.assertEqual(selected, wrapper.resolve())


if __name__ == '__main__':
    unittest.main()
