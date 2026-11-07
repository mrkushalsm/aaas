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

    def test_ext4_device_io_pause_blocks_before_accounting(self):
        import json as json_module
        self.marker.update(filesystem='ext4',
                           mount_uuid='094120c3-e1f8-4a61-a95a-c347ecb711d1')
        (self.workspace / guard.MARKER).write_text(json.dumps(self.marker))
        identity = {**self.identity, 'filesystem': 'ext4',
                    'uuid': '094120c3-e1f8-4a61-a95a-c347ecb711d1',
                    'source': '/dev/sda3'}
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / 'health.json'
            policy.write_text(json_module.dumps({'schema': 1, 'volumes': {
                identity['uuid']: {'uuid': identity['uuid'],
                                   'incident_id': 'fixture-ext4-incident',
                                   'state': 'DEVICE_FAILURE_SUSPECTED',
                                   'reason': 'fixture unresolved I/O incident',
                                   'recovery': None}}}))
            with patch.object(guard, 'HEALTH_POLICY', policy), \
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

    def test_storage_event_classifier_correlates_partition_disk_and_usb_path(self):
        classify = guard._classify_storage_event
        self.assertEqual(classify('ntfs3(sda2): inode mi_enum_attr', 3,
                                  'sda2', 'sda'), 'ntfs3_integrity')
        self.assertIsNone(classify('ntfs3(sdb2): inode mi_enum_attr', 3,
                                   'sda2', 'sda'))
        self.assertEqual(classify('I/O error, dev sda, sector 123', 3,
                                  'sda2', 'sda'), 'block_io')
        self.assertEqual(classify('Buffer I/O error on dev sda3, logical block 7', 3,
                                  'sda3', 'sda'), 'block_io')
        self.assertEqual(classify('JBD2: I/O error when updating journal superblock for sda3-8.', 3,
                                  'sda3', 'sda'), 'block_io')
        self.assertEqual(classify('EXT4-fs (sda3): shut down requested (2)', 3,
                                  'sda3', 'sda'), 'ext4_integrity')
        self.assertEqual(classify('sd 0:0:0:0: [sda] uas_eh_abort_handler', 4,
                                  'sda2', 'sda'), 'uas_transport')
        self.assertEqual(classify('usb 2-3: reset SuperSpeed USB device', 4,
                                  'sda2', 'sda', '2-3'), 'usb_transport')
        self.assertIsNone(classify('usb 2-4: reset device', 4,
                                   'sda2', 'sda', '2-3'))

    def test_workspace_journal_diagnostic_accepts_empty_match_set(self):
        empty = SimpleNamespace(stdout='', returncode=1, args=['journalctl'], stderr='')
        with patch.object(guard.subprocess, 'run', side_effect=[
                SimpleNamespace(stdout='sda'), empty]) as run:
            result = guard._journal_workspace_storage_events(
                {'source': '/dev/sda3'})
        self.assertEqual(result['events'], [])
        self.assertFalse(result['truncated'])
        self.assertIn('--lines=500', run.call_args.args[0])
        self.assertTrue(any(arg.startswith('--grep=') for arg in run.call_args.args[0]))

    def test_post_recovery_journal_detects_new_transport_and_ntfs_errors(self):
        rows = [
            {'MESSAGE': 'I/O error, dev testdisk, sector 7', 'PRIORITY': '3',
             '_BOOT_ID': 'boot', '__REALTIME_TIMESTAMP': '1'},
            {'MESSAGE': 'ntfs3(testpart): ino=abc, "x" mi_enum_attr',
             'PRIORITY': '3', '_BOOT_ID': 'boot'},
        ]
        output = '\n'.join(json.dumps(row) for row in rows)
        identity = {'source': '/dev/testpart'}
        entry = {'device': {'path': '/dev/testdisk', 'serial': 'test'},
                 'recovery': {'post_check': {'checked_at': '2026-11-07T09:00:00+05:30'}}}
        with patch.object(guard.subprocess, 'run',
                          return_value=SimpleNamespace(stdout=output)) as run:
            events = guard._journal_post_recovery_events(identity, entry)
        self.assertEqual([item['kind'] for item in events],
                         ['block_io', 'ntfs3_integrity'])
        self.assertTrue(any(arg.startswith('--since=')
                            for arg in run.call_args.args[0]))

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
        import time
        now = time.time()
        base = {'uuid': 'test-uuid', 'state': 'HEALTHY_FOR_CONTROLLED_TESTING',
                'device': {'path': '/dev/testdisk', 'serial': 'TEST_SERIAL',
                           'usb_path': '2-3'}}
        identity = {**self.identity, 'source': '/dev/testpart', 'mount_id': '41'}
        def iso(seconds):
            from datetime import datetime, timezone
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def evidence(name):
                content = f'synthetic test fixture {name}'.encode()
                (root / name).write_bytes(content)
                import hashlib
                return {'evidence_path': name,
                        'evidence_sha256': hashlib.sha256(content).hexdigest()}
            recovery = {
                'offline_check': {'tool': 'Windows CHKDSK', 'result': 'clean',
                                  'volume_uuid': 'test-uuid',
                                  'completed_at': iso(now - 3600),
                                  **evidence('offline.txt')},
                'device_health': {'status': 'healthy', 'serial': 'TEST_SERIAL',
                                  'checked_at': iso(now - 1800),
                                  **evidence('device.txt')},
                'post_check': {'checked_at': iso(now - 600),
                               'boot_id': 'boot-current', 'uuid': 'test-uuid',
                               'source': '/dev/testpart',
                               'device_serial': 'TEST_SERIAL', 'mount_epoch': '41',
                               'ntfs3_errors': 0, 'transport_errors': 0,
                               'metadata_probes': 'pass', 'workspace_manifest': 'pass',
                               'userdata_manifest': 'pass', **evidence('post.txt')},
            }
            policy = Path(tmp) / 'health.json'
            policy.write_text(json.dumps({'schema': 1,
                                          'volumes': {'test-uuid': base}}))
            self.assertEqual(guard.policy_health({'uuid': 'test-uuid'}, policy)['state'],
                             'HEALTH_UNKNOWN')
            valid = {**base, 'recovery': recovery}
            policy.write_text(json.dumps({'schema': 1,
                                          'volumes': {'test-uuid': valid}}))
            with patch.object(guard, '_current_boot_id', return_value='boot-current'), \
                 patch.object(guard, '_device_serial', return_value='TEST_SERIAL'), \
                 patch.object(guard, 'REPOSITORY_ROOT', root):
                self.assertEqual(guard.policy_health(identity, policy)['state'],
                                 'HEALTHY_FOR_CONTROLLED_TESTING')
                self.assertEqual(guard.policy_health(
                    {**identity, 'mount_id': '42'}, policy)['state'], 'HEALTH_UNKNOWN')
            with patch.object(guard, '_current_boot_id', return_value='new-boot'), \
                 patch.object(guard, '_device_serial', return_value='TEST_SERIAL'), \
                 patch.object(guard, 'REPOSITORY_ROOT', root):
                self.assertEqual(guard.policy_health(identity, policy)['state'],
                                 'HEALTH_UNKNOWN')
            (root / 'device.txt').write_text('tampered evidence')
            with patch.object(guard, '_current_boot_id', return_value='boot-current'), \
                 patch.object(guard, '_device_serial', return_value='TEST_SERIAL'), \
                 patch.object(guard, 'REPOSITORY_ROOT', root):
                self.assertEqual(guard.policy_health(identity, policy)['state'],
                                 'HEALTH_UNKNOWN')
            (root / 'device.txt').write_text('synthetic test fixture device.txt')
            import hashlib
            recovery['device_health']['evidence_sha256'] = hashlib.sha256(
                (root / 'device.txt').read_bytes()).hexdigest()
            stale_recovery = json.loads(json.dumps(recovery))
            stale_recovery['post_check']['checked_at'] = iso(
                now - guard.RECOVERY_POST_MAX_AGE_SECONDS - 1)
            stale_recovery['device_health']['checked_at'] = stale_recovery[
                'post_check']['checked_at']
            stale_recovery['offline_check']['completed_at'] = iso(now - 100000)
            policy.write_text(json.dumps({'schema': 1, 'volumes': {
                'test-uuid': {**base, 'recovery': stale_recovery}}}))
            with patch.object(guard, '_current_boot_id', return_value='boot-current'), \
                 patch.object(guard, '_device_serial', return_value='TEST_SERIAL'), \
                 patch.object(guard, 'REPOSITORY_ROOT', root):
                self.assertEqual(guard.policy_health(identity, policy)['state'],
                                 'HEALTH_UNKNOWN')

    def test_post_recovery_device_error_reactivates_quarantine(self):
        import time
        now = time.time()
        from datetime import datetime, timezone
        iso = lambda age: datetime.fromtimestamp(now - age, timezone.utc).isoformat()
        identity = {**self.identity, 'filesystem': 'ntfs3', 'uuid': 'recovered-id',
                    'source': '/dev/testpart', 'mount_id': '77'}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def evidence(name):
                content = f'synthetic test fixture {name}'.encode()
                (root / name).write_bytes(content)
                import hashlib
                return {'evidence_path': name,
                        'evidence_sha256': hashlib.sha256(content).hexdigest()}
            entry = {'uuid': 'recovered-id',
                     'state': 'HEALTHY_FOR_CONTROLLED_TESTING',
                     'device': {'path': '/dev/testdisk', 'serial': 'TEST_SERIAL',
                                'usb_path': '2-3'},
                     'recovery': {
                         'offline_check': {'tool': 'CHKDSK', 'result': 'clean',
                                           'volume_uuid': 'recovered-id',
                                           'completed_at': iso(3600),
                                           **evidence('offline.txt')},
                         'device_health': {'status': 'healthy',
                                           'serial': 'TEST_SERIAL',
                                           'checked_at': iso(1800),
                                           **evidence('device.txt')},
                         'post_check': {'checked_at': iso(600),
                                        'boot_id': 'boot-current',
                                        'uuid': 'recovered-id',
                                        'source': '/dev/testpart',
                                        'device_serial': 'TEST_SERIAL',
                                        'mount_epoch': '77', 'ntfs3_errors': 0,
                                        'transport_errors': 0,
                                        'metadata_probes': 'pass',
                                        'workspace_manifest': 'pass',
                                        'userdata_manifest': 'pass',
                                        **evidence('post.txt')}}}
            policy = Path(tmp) / 'health.json'
            policy.write_text(json.dumps({'schema': 1,
                                          'volumes': {'recovered-id': entry}}))
            with patch.object(guard, '_current_boot_id', return_value='boot-current'), \
                 patch.object(guard, '_device_serial', return_value='TEST_SERIAL'), \
                 patch.object(guard, 'REPOSITORY_ROOT', root), \
                 patch.object(guard, '_journal_post_recovery_events', return_value=[{
                     'kind': 'block_io', 'message': 'I/O error, dev testdisk'}]):
                result = guard.assess_workspace_health(identity, policy, now=1000)
        self.assertEqual(result['state'], 'DEVICE_FAILURE_SUSPECTED')

    def test_ext4_recovery_clears_only_after_verified_checkpoint(self):
        import hashlib
        import time
        from datetime import datetime, timezone
        now = time.time()
        iso = lambda age: datetime.fromtimestamp(now - age, timezone.utc).isoformat()
        identity = {**self.identity, 'filesystem': 'ext4', 'uuid': 'ext4-id',
                    'source': '/dev/testpart', 'mount_id': '246'}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def evidence(name, content):
                path = root / name
                path.write_text(content)
                return {'evidence_path': name,
                        'evidence_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

            recovery = {
                'offline_check': {
                    'tool': 'e2fsck -fn', 'mode': 'read-only', 'filesystem': 'ext4',
                    'result': 'clean', 'volume_uuid': 'ext4-id',
                    'completed_at': iso(600),
                    **evidence('offline.txt', 'user supplied clean e2fsck report')},
                'device_health': {
                    'status': 'media_passed_transport_history',
                    'serial': 'TEST_SERIAL', 'checked_at': iso(300),
                    **evidence('device.txt', 'SMART passed; transport counters recorded')},
                'post_check': {
                    'checked_at': iso(60), 'boot_id': 'boot-current', 'uuid': 'ext4-id',
                    'source': '/dev/testpart', 'device_serial': 'TEST_SERIAL',
                    'mount_epoch': '246', 'filesystem_errors': 0,
                    'transport_errors': 0, 'metadata_probes': 'pass',
                    'workspace_manifest': 'pass', 'userdata_manifest': 'pass',
                    **evidence('post.txt', 'post-check evidence')},
            }
            entry = {'uuid': 'ext4-id', 'state': 'DEVICE_FAILURE_SUSPECTED',
                     'incident_id': 'ext4-incident', 'filesystem': 'ext4',
                     'device': {'path': '/dev/testdisk', 'serial': 'TEST_SERIAL'},
                     'recovery': recovery}
            policy = Path(tmp) / 'health.json'
            policy.write_text(json.dumps({'schema': 1,
                                          'volumes': {'ext4-id': entry}}))
            with patch.object(guard, '_current_boot_id', return_value='boot-current'), \
                 patch.object(guard, '_device_serial', return_value='TEST_SERIAL'), \
                 patch.object(guard, 'REPOSITORY_ROOT', root):
                state = guard.policy_health(identity, policy)
                self.assertEqual(state['state'], 'HEALTHY_FOR_CONTROLLED_TESTING')
                self.assertEqual(state['incident_id'], 'ext4-incident')
                with patch.object(guard, '_journal_post_recovery_events', return_value=[]):
                    result = guard.assess_workspace_health(identity, policy, now=now)
                self.assertEqual(result['state'], 'HEALTHY_FOR_CONTROLLED_TESTING')
                with patch.object(guard, '_journal_post_recovery_events', return_value=[{
                        'kind': 'block_io', 'message': 'I/O error, dev testdisk'}]):
                    result = guard.assess_workspace_health(identity, policy, now=now + 6)
                self.assertEqual(result['state'], 'DEVICE_FAILURE_SUSPECTED')


if __name__ == '__main__':
    unittest.main()
