import stat
import sys
import os
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import android_newc


def newc_entry(name, mode, payload=b'', *, uid=0, gid=0, ino=1, nlink=1,
               rdevmajor=0, rdevminor=0):
    fields = (ino, mode, uid, gid, nlink, 1, len(payload), 0, 0,
              rdevmajor, rdevminor, len(name.encode()) + 1, 0)
    header = b'070701' + b''.join(f'{value:08x}'.encode() for value in fields)
    result = header + name.encode() + b'\0'
    result += b'\0' * ((-len(result)) % 4)
    result += payload
    result += b'\0' * ((-len(result)) % 4)
    return result


class AndroidNewcTests(unittest.TestCase):
    def test_parser_reads_ordinary_entries_and_stops_at_trailer(self):
        data = (newc_entry('init', stat.S_IFREG | 0o755, b'init bytes')
                + newc_entry('TRAILER!!!', 0))
        entries = list(android_newc.parse_newc(data))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1:], ('init', b'init bytes'))

    def test_parser_rejects_truncated_payload_and_missing_trailer(self):
        entry = newc_entry('init', stat.S_IFREG | 0o755, b'init bytes')
        with self.assertRaisesRegex(android_newc.NewcError, 'trailer'):
            list(android_newc.parse_newc(entry))
        truncated = bytearray(entry)
        truncated[54:62] = b'000000ff'
        with self.assertRaisesRegex(android_newc.NewcError, 'truncated'):
            list(android_newc.parse_newc(bytes(truncated)))

    def test_archive_path_validation_rejects_escape(self):
        data = newc_entry('../outside', stat.S_IFREG | 0o600, b'x')
        data += newc_entry('TRAILER!!!', 0)
        with self.assertRaisesRegex(android_newc.NewcError, 'unsafe ramdisk path'):
            android_newc.extract_newc(data, Path('/tmp/unused-aaas-newc'))

    def test_entries_cannot_traverse_an_archived_symlink(self):
        data = newc_entry('link', stat.S_IFLNK | 0o777, b'/tmp')
        data += newc_entry('link/child', stat.S_IFREG | 0o600, b'x')
        data += newc_entry('TRAILER!!!', 0)
        with self.assertRaisesRegex(android_newc.NewcError, 'traverses an archived symlink'):
            android_newc.extract_newc(data, Path('/tmp/unused-aaas-newc'))

    def test_ramdisk_entry_cannot_traverse_preexisting_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'link').symlink_to('/tmp')
            data = newc_entry('link/child', stat.S_IFREG | 0o600, b'x',
                              uid=os.getuid(), gid=os.getgid())
            data += newc_entry('TRAILER!!!', 0)
            with self.assertRaisesRegex(android_newc.NewcError,
                                        'existing symlink'):
                android_newc.extract_newc(data, root)

    def test_ramdisk_init_replaces_the_system_partition_init_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'system/bin').mkdir(parents=True)
            init_link = root / 'init'
            init_link.symlink_to('/system/bin/init')
            data = newc_entry('init', stat.S_IFREG | 0o755, b'ramdisk-init',
                              uid=os.getuid(), gid=os.getgid())
            data += newc_entry('TRAILER!!!', 0)
            report = android_newc.extract_newc(data, root)
            self.assertEqual(init_link.read_bytes(), b'ramdisk-init')
            self.assertFalse(init_link.is_symlink())
            self.assertEqual(report['inventory'][0]['path'], 'init')


if __name__ == '__main__':
    unittest.main()
