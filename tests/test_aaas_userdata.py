import json
import os
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_userdata


class PersistentUserdataTests(unittest.TestCase):
    def test_proc_start_time_parser_handles_current_process(self):
        start_time = aaas_userdata._proc_start_time(os.getpid())
        self.assertTrue(start_time.isdigit())

    def test_initializes_private_directory_and_reuses_it(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            data = aaas_userdata.prepare_userdata_directory(workspace)
            marker = data.parent / aaas_userdata.MANIFEST_NAME
            self.assertEqual(data, workspace / 'android-userdata' / 'data')
            self.assertTrue(data.is_dir())
            self.assertFalse((data / 'media').exists())
            self.assertEqual(json.loads(marker.read_text())['schema'], 1)
            self.assertEqual(data, aaas_userdata.prepare_userdata_directory(workspace))

    def test_refuses_unrecognized_nonempty_data_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            data = workspace / 'android-userdata' / 'data'
            data.mkdir(parents=True)
            data.parent.chmod(0o700)
            sentinel = data / 'unknown-state'
            sentinel.write_bytes(b'preserve')
            with self.assertRaisesRegex(aaas_userdata.UserdataError,
                                        'unrecognized nonempty'):
                aaas_userdata.prepare_userdata_directory(workspace)
            self.assertEqual(sentinel.read_bytes(), b'preserve')

    def test_refuses_symlinked_backing(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            external = workspace / 'outside'
            external.mkdir()
            data = workspace / 'android-userdata' / 'data'
            data.parent.mkdir(mode=0o700)
            data.symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(aaas_userdata.UserdataError,
                                        'symlinked userdata backing'):
                aaas_userdata.prepare_userdata_directory(workspace)

    def test_status_reports_dynamic_directory_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            data = aaas_userdata.prepare_userdata_directory(workspace)
            (data / 'fixture').write_bytes(b'bounded')
            result = aaas_userdata.backing_status(data)
            self.assertEqual(result['backing'], 'directory')
            self.assertIsNone(result['logical_limit'])
            self.assertGreater(result['filesystem_available_bytes'], 0)
            self.assertGreaterEqual(result['allocated_bytes'], 0)


if __name__ == '__main__':
    unittest.main()
