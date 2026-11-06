import tempfile
import unittest
from pathlib import Path

from scripts.aaas_clipboard import (
    app_uid_to_host_uid, atomic_write, decode_frame, encode_frame,
    parse_runtime_state, prepare_ipc_directory,
)


class ClipboardFrameTests(unittest.TestCase):
    def test_ascii_unicode_multiline_and_punctuation_round_trip(self):
        value = 'AaaS clipboard — नमस्ते\nline two: !? 你好'
        self.assertEqual(decode_frame(encode_frame(value)), value)

    def test_clear_is_explicit(self):
        self.assertIsNone(decode_frame(encode_frame(None)))
        self.assertIsNone(decode_frame(encode_frame('')))

    def test_exact_limit_is_accepted_and_oversize_rejected(self):
        value = 'a' * (64 * 1024)
        self.assertEqual(decode_frame(encode_frame(value)), value)
        with self.assertRaises(ValueError):
            encode_frame(value + 'a')

    def test_rejects_malformed_frames(self):
        invalid = [b'', b'wrong\nT\nx', b'AASCLIP1\nX\ntext',
                   b'AASCLIP1\nC\nextra', b'AASCLIP1\nT\n\xff',
                   b'AASCLIP1\nT\na\0b']
        for frame in invalid:
            with self.subTest(frame=frame[:20]), self.assertRaises(ValueError):
                decode_frame(frame)

    def test_atomic_write_preserves_complete_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'clip'
            frame = encode_frame('same value')
            atomic_write(path, frame)
            self.assertEqual(decode_frame(path.read_bytes()), 'same value')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_atomic_write_rejects_symlink_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_text('unrelated')
            link = Path(directory) / 'clip'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                atomic_write(link, encode_frame('secret'))
            self.assertEqual(target.read_text(), 'unrelated')

    def test_runtime_state_and_uid_mapping_are_bounded(self):
        self.assertEqual(parse_runtime_state('10150 1'), (10150, True))
        self.assertEqual(parse_runtime_state('10150 0'), (10150, False))
        for value in ('1 1', '70000 1', '10150 yes', '10150 1 extra', 'bad 0'):
            self.assertIsNone(parse_runtime_state(value))
        self.assertEqual(app_uid_to_host_uid(10150), 110149)
        with self.assertRaises(ValueError):
            app_uid_to_host_uid(9999)

    def test_ipc_area_is_sticky_and_not_listable(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = prepare_ipc_directory(Path(temporary))
            self.assertEqual(directory.stat().st_mode & 0o7777, 0o1733)
            self.assertFalse(directory.is_symlink())

    def test_ipc_area_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'target'
            target.mkdir()
            (root / 'clipboard').symlink_to(target)
            with self.assertRaises(ValueError):
                prepare_ipc_directory(root)

    def test_apk_builder_inlines_bionic_open_flags(self):
        builder = Path(__file__).resolve().parents[1] / 'experiments/m4/clipboard/build_clipboard_ime.py'
        source = builder.read_text()
        self.assertIn('O_WRONLY=1,O_CREAT=64,O_EXCL=128', source)

    def test_wayland_seat_listener_handles_name_event(self):
        source = (Path(__file__).resolve().parents[1] /
                  'experiments/m4/clipboard/wayland_clipboard.c').read_text()
        self.assertIn('.name = seat_name', source)
        self.assertIn('static void seat_name(', source)


if __name__ == '__main__':
    unittest.main()
