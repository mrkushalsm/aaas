import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts import android_workspace as guard


class WorkspaceGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mount = Path(self.tmp.name) / 'mount'
        self.workspace = self.mount / 'aaas-workspace'
        self.workspace.mkdir(parents=True)
        self.marker = dict(schema=1, workspace_id='test-id',
                           mount_target=str(self.mount), mount_uuid='test-uuid',
                           filesystem='ext4', budget_gib=100,
                           reserve_gib=20, working_ceiling_gib=80)
        (self.workspace / guard.MARKER).write_text(json.dumps(self.marker))
        self.identity = dict(target=str(self.mount), source='/dev/test',
                             filesystem='ext4', uuid='test-uuid')

    def test_rejects_unmounted_target(self):
        with patch.object(guard, 'mount_identity', return_value={**self.identity, 'target': '/'}):
            with self.assertRaisesRegex(guard.WorkspaceError, 'not mounted'):
                guard.check(self.workspace)

    def test_rejects_foreign_disk(self):
        with patch.object(guard, 'mount_identity', return_value={**self.identity, 'uuid': 'other'}):
            with self.assertRaisesRegex(guard.WorkspaceError, 'identity changed'):
                guard.check(self.workspace)

    def test_hardlinks_count_once(self):
        first = self.workspace / 'first'
        first.write_bytes(b'abc')
        os.link(first, self.workspace / 'second')
        st = first.stat()
        self.assertEqual(guard.allocated_bytes(self.workspace),
                         st.st_blocks * 512 + (self.workspace / guard.MARKER).stat().st_blocks * 512)

    def test_private_userdata_is_counted_by_mapped_read_only_scan(self):
        private = self.workspace / guard.aaas_userdata.DIRECTORY_NAME
        private.mkdir()
        (private / 'data').mkdir()
        with patch.object(guard.aaas_userdata, 'allocated_bytes_rootless',
                          return_value=8192) as scan:
            result = guard.allocated_bytes(self.workspace)
        scan.assert_called_once_with(private)
        self.assertGreaterEqual(result, 8192)

    def test_stops_child_after_actual_growth(self):
        self.marker.update(budget_gib=4, reserve_gib=1, working_ceiling_gib=2)
        (self.workspace / guard.MARKER).write_text(json.dumps(self.marker))
        payload = self.workspace / 'growth.bin'
        code = ("from pathlib import Path; import time; "
                f"Path({str(payload)!r}).write_bytes(b'X' * (3 << 20)); "
                "time.sleep(10)")
        with patch.object(guard, 'mount_identity', return_value=self.identity), \
             patch.object(guard, 'GIB', 1 << 20):
            with self.assertRaisesRegex(guard.WorkspaceError, 'budget exceeded'):
                guard.run_guarded(self.workspace, 0, 0.05,
                                  [sys.executable, '-c', code], None)
        self.assertTrue(payload.exists())

    def test_prediction_stays_below_ceiling(self):
        with patch.object(guard, 'mount_identity', return_value=self.identity), \
             patch.object(guard.os, 'statvfs', return_value=SimpleNamespace(f_bavail=200, f_frsize=guard.GIB)):
            with self.assertRaisesRegex(guard.WorkspaceError, 'budget exceeded'):
                guard.check(self.workspace, 90 * guard.GIB)
            self.assertLess(guard.check(self.workspace)['used_bytes'], 80 * guard.GIB)

    def test_initialize_new_workspace_and_repeat(self):
        (self.workspace / guard.MARKER).unlink()
        self.workspace.rmdir()
        with patch.object(guard, 'mount_identity', return_value=self.identity), \
             patch.object(guard.os, 'statvfs', return_value=SimpleNamespace(f_bavail=200, f_frsize=guard.GIB)):
            first = guard.initialize(self.workspace, self.mount)
            marker = json.loads((self.workspace / guard.MARKER).read_text())
            self.assertEqual(first['workspace'], str(self.workspace))
            self.assertTrue(all((self.workspace / name).is_dir() for name in guard.LAYOUT))
            guard.initialize(self.workspace, self.mount)
            self.assertEqual(json.loads((self.workspace / guard.MARKER).read_text()), marker)

    def test_initialize_refuses_existing_unmarked_data(self):
        (self.workspace / guard.MARKER).unlink()
        with patch.object(guard, 'mount_identity', return_value=self.identity):
            with self.assertRaisesRegex(guard.WorkspaceError, 'missing workspace marker'):
                guard.initialize(self.workspace, self.mount)


if __name__ == '__main__':
    unittest.main()
