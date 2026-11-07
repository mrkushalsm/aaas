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

    def test_rejects_wrong_filesystem_type(self):
        with patch.object(guard, 'mount_identity',
                          return_value={**self.identity, 'filesystem': 'ntfs3'}):
            with self.assertRaisesRegex(guard.WorkspaceError, 'identity changed'):
                guard.check(self.workspace)

    def test_rejects_read_only_workspace(self):
        with patch.object(guard, 'mount_identity', return_value=self.identity), \
             patch.object(guard.os, 'access', return_value=False):
            with self.assertRaisesRegex(guard.WorkspaceError, 'not writable'):
                guard.check(self.workspace)

    def test_rejects_insufficient_free_space(self):
        with patch.object(guard, 'mount_identity', return_value=self.identity), \
             patch.object(guard.os, 'statvfs', return_value=SimpleNamespace(
                 f_bavail=10, f_frsize=guard.GIB)):
            with self.assertRaisesRegex(guard.WorkspaceError, 'budget exceeded'):
                guard.check(self.workspace)

    def test_runtime_mount_probe_accepts_expected_mount_and_sentinels(self):
        userdata = self.workspace / 'android-userdata' / 'data'
        shared = self.workspace / 'shared-storage' / 'android-media'
        userdata.mkdir(parents=True)
        shared.mkdir(parents=True)
        with patch.object(guard, 'mount_identity', return_value=self.identity):
            with patch.object(guard.os, 'statvfs', return_value=SimpleNamespace(
                    f_bavail=100, f_frsize=guard.GIB)):
                result = guard.validate_mounted_workspace(
                    self.workspace, sentinels=(userdata, shared))
        self.assertEqual(result['mount']['uuid'], 'test-uuid')
        self.assertGreater(result['free_bytes'], 0)

    def test_runtime_mount_probe_rejects_changed_mount_and_missing_backing(self):
        with patch.object(guard, 'mount_identity', return_value={**self.identity, 'target': '/'}):
            with self.assertRaisesRegex(guard.WorkspaceError, 'not mounted'):
                guard.validate_mounted_workspace(self.workspace)
        missing = self.workspace / 'android-userdata' / 'data'
        with patch.object(guard, 'mount_identity', return_value=self.identity):
            with patch.object(guard.os, 'statvfs', return_value=SimpleNamespace(
                    f_bavail=100, f_frsize=guard.GIB)):
                with self.assertRaisesRegex(guard.WorkspaceError, 'backing unavailable'):
                    guard.validate_mounted_workspace(self.workspace, sentinels=(missing,))

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

    def test_device_matched_integrity_pause_blocks_before_accounting(self):
        self.marker.update(filesystem='ntfs3', mount_uuid='A2ACEDF2ACEDC0C1')
        (self.workspace / guard.MARKER).write_text(json.dumps(self.marker))
        identity = {**self.identity, 'filesystem': 'ntfs3',
                    'uuid': 'A2ACEDF2ACEDC0C1', 'source': '/dev/sda2'}
        with patch.object(guard, 'HEALTH_POLICY', Path(__file__).parents[1] /
                          'manifests' / 'workspace-health.json'), \
             patch.object(guard, 'mount_identity', return_value=identity), \
             patch.object(guard, 'allocated_bytes', side_effect=AssertionError('must not scan')):
            with self.assertRaisesRegex(guard.WorkspaceError,
                                        'DEVICE_FAILURE_SUSPECTED'):
                guard.check(self.workspace)

    def test_journal_error_is_filtered_by_partition_and_error_priority(self):
        import json as json_module
        entries = [
            {'MESSAGE': 'ntfs3(sda2): ino=abc, "x" mi_enum_attr',
             'PRIORITY': '3', '_BOOT_ID': 'boot',
             '__REALTIME_TIMESTAMP': '123', '__MONOTONIC_TIMESTAMP': '456'},
            {'MESSAGE': 'ntfs3(sdb1): ino=def, "x" mi_enum_attr', 'PRIORITY': '3'},
            {'MESSAGE': 'ntfs3(sda2): info only', 'PRIORITY': '6'},
        ]
        output = '\n'.join(json_module.dumps(item) for item in entries)
        with patch.object(guard.subprocess, 'run', return_value=SimpleNamespace(stdout=output)) as run:
            events = guard._journal_ntfs_events('/dev/sda2')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['boot_id'], 'boot')
        self.assertIn('-b', run.call_args.args[0])
        self.assertIn('--lines=200', run.call_args.args[0])

    def test_missing_or_unavailable_journal_is_unknown_for_ntfs3(self):
        identity = {**self.identity, 'filesystem': 'ntfs3',
                    'uuid': 'unknown-uuid', 'source': '/dev/test2'}
        with patch.object(guard, 'HEALTH_POLICY', Path(self.tmp.name) / 'missing.json'), \
             patch.object(guard, '_journal_ntfs_events', side_effect=PermissionError('denied')):
            result = guard.assess_workspace_health(identity, now=100)
        self.assertEqual(result['state'], 'HEALTH_UNKNOWN')

    def test_ntfs3_unknown_health_blocks_workspace_checks(self):
        self.marker.update(filesystem='ntfs3', mount_uuid='unverified')
        (self.workspace / guard.MARKER).write_text(json.dumps(self.marker))
        identity = {**self.identity, 'filesystem': 'ntfs3', 'uuid': 'unverified'}
        with patch.object(guard, 'HEALTH_POLICY', Path(self.tmp.name) / 'missing.json'), \
             patch.object(guard, 'mount_identity', return_value=identity), \
             patch.object(guard, '_journal_ntfs_events', return_value=[]), \
             patch.object(guard, 'allocated_bytes', side_effect=AssertionError('must not scan')):
            with self.assertRaisesRegex(guard.WorkspaceError, 'HEALTH_UNKNOWN'):
                guard.check(self.workspace)

    def test_ntfs3_journal_matching_event_classifies_integrity_warning(self):
        identity = {**self.identity, 'filesystem': 'ntfs3', 'uuid': 'other-uuid'}
        event = {'message': 'ntfs3(test): ino=1, "x" mi_enum_attr', 'priority': 3}
        with patch.object(guard, 'HEALTH_POLICY', Path(self.tmp.name) / 'missing.json'), \
             patch.object(guard, '_journal_ntfs_events', return_value=[event]):
            result = guard.assess_workspace_health(identity, now=1000)
        self.assertEqual(result['state'], 'INTEGRITY_WARNING')
        self.assertIn('device-matched', result['reason'])

    def test_diagnostic_rejects_malformed_marker(self):
        (self.workspace / guard.MARKER).write_text('{broken')
        with self.assertRaisesRegex(guard.WorkspaceError, 'valid workspace marker'):
            guard.diagnose_workspace(self.workspace)

    def test_malformed_health_policy_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / 'health.json'
            policy.write_text('[]')
            with self.assertRaisesRegex(guard.WorkspaceError, 'invalid schema'):
                guard.policy_health({'uuid': 'test-uuid'}, policy)

    def test_recovery_requires_offline_device_and_post_mount_evidence(self):
        base = {'uuid': 'test-uuid', 'state': 'HEALTHY_FOR_CONTROLLED_TESTING'}
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / 'health.json'
            policy.write_text(json.dumps({'schema': 1, 'volumes': {'test-uuid': base}}))
            self.assertEqual(guard.policy_health({'uuid': 'test-uuid'}, policy)['state'],
                             'HEALTH_UNKNOWN')
            valid = {**base, 'recovery': {
                'offline_check': {'tool': 'Windows CHKDSK', 'result': 'clean',
                                  'completed_at': '2026-11-08', 'evidence_ref': 'record-1'},
                'post_check': {'checked_at': '2026-11-08', 'boot_id': 'boot-2',
                               'uuid': 'test-uuid', 'ntfs3_errors': 0,
                               'metadata_probes': 'pass'},
                'device_health': {'status': 'healthy', 'evidence_ref': 'smart-1'},
            }}
            policy.write_text(json.dumps({'schema': 1,
                                          'volumes': {'test-uuid': valid}}))
            self.assertEqual(guard.policy_health({'uuid': 'test-uuid'}, policy)['state'],
                             'HEALTHY_FOR_CONTROLLED_TESTING')


if __name__ == '__main__':
    unittest.main()
