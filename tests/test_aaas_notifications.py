from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_notifications as notifications


class NotificationFrameTests(unittest.TestCase):
    def test_directory_creation_and_event_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ipc = root / 'ipc'
            ipc.mkdir()
            directory = notifications.prepare_ipc_directory(ipc)
            self.assertEqual(directory.stat().st_mode & 0o7777, 0o1733)
            (directory / ('event-' + 'a' * 32 + '.frame')).write_bytes(b'test')
            (directory / 'unrelated').write_text('preserved')
            self.assertFalse(notifications.clear_session_events(ipc))
            self.assertFalse((directory / ('event-' + 'a' * 32 + '.frame')).exists())
            self.assertTrue((directory / 'unrelated').exists())

    def test_event_directory_is_non_listable_and_host_can_read_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            ipc = Path(temporary) / 'ipc'
            ipc.mkdir()
            directory = notifications.prepare_ipc_directory(ipc)
            self.assertEqual(directory.stat().st_mode & 0o7777, 0o1733)
            acl = subprocess.run(['getfacl', '-cp', str(directory)], check=True,
                                 capture_output=True, text=True).stdout
            self.assertIn('default:user:mrkus:r--', acl)
            self.assertIn('other::-wx', acl)

    def test_posted_unicode_and_multiline_round_trip(self):
        event = {'type': 'posted', 'package': 'org.example.app', 'user': '0',
                 'key': '0|org.example.app|5|tag|10123', 'app': 'Example 🌙',
                 'title': 'A title', 'body': 'line one\nline two — café'}
        self.assertEqual(notifications.decode_event(notifications.encode_event(event)), event)

    def test_removed_event_round_trip(self):
        event = {'type': 'removed', 'package': 'org.example.app', 'user': '0',
                 'key': '0|org.example.app|5|tag|10123'}
        self.assertEqual(notifications.decode_event(notifications.encode_event(event)), event)

    def test_invalid_or_oversized_values_rejected(self):
        base = {'type': 'posted', 'package': 'org.example.app', 'user': '0',
                'key': 'key', 'app': 'App', 'title': '', 'body': ''}
        for change in ({'package': '../escape'}, {'body': 'x' * 8193}, {'user': 'x'},
                       {'key': ''}, {'body': '\0'}):
            with self.subTest(change=next(iter(change))):
                with self.assertRaises(ValueError):
                    notifications.encode_event(base | change)

    def test_corrupt_frames_rejected(self):
        for frame in (b'', b'bad', notifications.MAGIC + b'X\n',
                      notifications.MAGIC + b'P\nAA\n',
                      b'AASN1\nP\n!!!!\nMA\na2V5\nYQ\n\n\n'):
            with self.subTest(frame=frame[:20]):
                with self.assertRaises(ValueError):
                    notifications.decode_event(frame)

    def test_runtime_state_validation(self):
        self.assertEqual(notifications.parse_runtime_state('10150 1\n'), (10150, True))
        for value in ('', '0 1', '70000 1', '10150 yes', '10150 1 extra'):
            with self.subTest(value=value):
                self.assertIsNone(notifications.parse_runtime_state(value))

    def test_frame_requires_expected_owner_and_no_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event = {'type': 'removed', 'package': 'org.example.app', 'user': '0', 'key': 'k'}
            frame = root / ('event-' + '0' * 32 + '.frame')
            frame.write_bytes(notifications.encode_event(event))
            self.assertEqual(notifications.consume_frame(frame, os.getuid()), event)
            with self.assertRaises(ValueError):
                notifications.consume_frame(frame, os.getuid() + 1)
            link = root / ('event-' + '1' * 32 + '.frame')
            link.symlink_to(frame)
            with self.assertRaises(OSError):
                notifications.consume_frame(link, os.getuid())


class NotificationMappingTests(unittest.TestCase):
    def event(self, package, key, kind='posted', body='body'):
        return {'type': kind, 'package': package, 'user': '0', 'key': key,
                'app': package, 'title': 'title', 'body': body}

    def test_update_reuses_host_notification_id_and_remove_closes_it(self):
        notifications_sent = []
        closed = []
        ids = iter((41, 41))
        forwarder = notifications.NotificationForwarder(
            lambda app, replacement, title, body: notifications_sent.append(
                (app, replacement, title, body)) or next(ids), closed.append)
        self.assertEqual(forwarder.dispatch(self.event('org.a', 'key')), 41)
        self.assertEqual(forwarder.dispatch(self.event('org.a', 'key', body='updated')), 41)
        self.assertEqual([call[1] for call in notifications_sent], [0, 41])
        self.assertEqual(forwarder.dispatch(self.event('org.a', 'key', 'removed')), 41)
        self.assertEqual(closed, [41])
        self.assertFalse(forwarder.active)

    def test_same_android_id_from_distinct_packages_is_independent(self):
        calls = []
        forwarder = notifications.NotificationForwarder(
            lambda app, replacement, *_: calls.append((app, replacement)) or len(calls),
            lambda _id: None)
        forwarder.dispatch(self.event('org.a', 'same-id'))
        forwarder.dispatch(self.event('org.b', 'same-id'))
        self.assertEqual(len(forwarder.active), 2)
        self.assertEqual([entry[1] for entry in calls], [0, 0])

    def test_close_all_clears_session_mappings(self):
        closed = []
        forwarder = notifications.NotificationForwarder(
            lambda *_: 7, closed.append)
        forwarder.dispatch(self.event('org.a', 'key'))
        forwarder.close_all()
        self.assertEqual(closed, [7])
        self.assertFalse(forwarder.order)

    def test_active_mapping_limit_closes_oldest(self):
        closed = []
        counter = iter(range(1, 5))
        forwarder = notifications.NotificationForwarder(
            lambda *_: next(counter), closed.append, max_active=2)
        for index in range(3):
            forwarder.dispatch(self.event('org.a', f'key-{index}'))
        self.assertEqual(closed, [1])
        self.assertEqual(len(forwarder.active), 2)


if __name__ == '__main__':
    unittest.main()
