import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import probe_clean_bionic as probe


class CleanBionicProbeTest(unittest.TestCase):
    def test_namespace_uses_read_only_images_and_clears_environment(self):
        argv = probe.bwrap_argv(Path('/tmp/system'), Path('/tmp/runtime'),
                                '/system/bin/toybox id')
        self.assertIn('--clearenv', argv)
        self.assertIn('--unshare-net', argv)
        self.assertEqual(argv.count('--ro-bind'), 2)
        self.assertNotIn('LD_PRELOAD', argv)
        self.assertEqual(argv[-3:], ['/system/bin/sh', '-c', '/system/bin/toybox id'])

    def test_missing_partition_stops_before_mount(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(probe.ws, 'check'):
                with self.assertRaisesRegex(RuntimeError, 'missing system image'):
                    probe.run(Path(tmp), 'true', 1)


if __name__ == '__main__':
    unittest.main()
