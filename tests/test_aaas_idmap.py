from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_idmap
import aaas_clipboard


class AaasIdMapTests(unittest.TestCase):
    def test_resolves_username_or_numeric_account_subid_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'subid'
            path.write_text('# comment\nother:300000:65536\n1001:420000:70000\n')
            self.assertEqual(aaas_idmap.parse_subid_file(path, 'dev', 1001),
                             aaas_idmap.SubordinateRange(420000, 70000))

    def test_rejects_missing_or_too_short_ranges(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'subid'
            path.write_text('dev:500000:1024\n')
            with self.assertRaisesRegex(aaas_idmap.IdMapError, 'no 65535-ID'):
                aaas_idmap.parse_subid_file(path, 'dev', 1001)

    def test_dynamic_android_uid_translation_uses_selected_range(self):
        with mock.patch.object(aaas_idmap, 'current_ranges', return_value=(
                aaas_idmap.SubordinateRange(420000, 65535),
                aaas_idmap.SubordinateRange(520000, 65535))):
            self.assertEqual(aaas_idmap.android_host_id(1041), 421040)
            self.assertEqual(aaas_idmap.android_host_id(1023), 421022)
            self.assertEqual(aaas_idmap.android_host_id(1041, kind='gid'), 521040)

    def test_namespace_map_commands_use_detected_ranges(self):
        with mock.patch.object(aaas_idmap, 'current_ranges', return_value=(
                aaas_idmap.SubordinateRange(420000, 65535),
                aaas_idmap.SubordinateRange(520000, 65535))):
            uid, gid, _, _ = aaas_idmap.map_commands(42, host_uid=1001, host_gid=1002)
        self.assertEqual(uid, ['newuidmap', '42', '0', '1001', '1', '1', '420000', '65535'])
        self.assertEqual(gid, ['newgidmap', '42', '0', '1002', '1', '1', '520000', '65535'])

    def test_clipboard_host_uid_uses_current_subid_range(self):
        with mock.patch.object(aaas_idmap, 'current_ranges', return_value=(
                aaas_idmap.SubordinateRange(420000, 65535),
                aaas_idmap.SubordinateRange(520000, 65535))):
            self.assertEqual(aaas_clipboard.app_uid_to_host_uid(11000), 430999)


if __name__ == '__main__':
    unittest.main()
