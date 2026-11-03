import tempfile
import unittest
from pathlib import Path
import os
import shutil
import subprocess

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_storage


class SharedStorageBackingTests(unittest.TestCase):
    def test_prepare_creates_private_parent_and_stable_user_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = aaas_storage.prepare_backing_directory(workspace)
            self.assertEqual(path, workspace / 'shared-storage/android-media/0')
            self.assertEqual(aaas_storage.media_root_path(workspace), path.parent)
            self.assertTrue(path.parent.is_dir())
            self.assertTrue(path.is_dir())
            self.assertEqual(path.stat().st_uid, __import__('os').getuid())
            self.assertTrue(path.stat().st_mode & 0o111)
            self.assertTrue((path / 'Documents').is_dir())
            self.assertTrue((path / 'Android' / 'data').is_dir())
            self.assertTrue((path / 'Android' / 'obb').is_dir())
            self.assertEqual((path / 'Android' / 'data').stat().st_mode & 0o777,
                             0o700)
            if shutil.which('getfacl'):
                acl = subprocess.run(
                    ['getfacl', '--omit-header', '--numeric', str(path)],
                    check=True, capture_output=True, text=True).stdout.splitlines()
                self.assertIn(f'user:{os.getuid()}:rwx', acl)
                self.assertIn(f'default:user:{os.getuid()}:rwx', acl)
            self.assertEqual(aaas_storage.prepare_backing_directory(workspace), path)
            # The app-specific Android/data and Android/obb directories are
            # deliberately private to media_rw. Restore test cleanup access.
            aaas_storage._run_mapped_storage_command(
                path,
                'read ready; cd -- "$1" || exit; '
                'setpriv --reuid=1023 --regid=1023 --clear-groups '
                'setfacl -m u:0:rwx Android Android/data Android/obb',
                'media-rw',
            )

    def test_refuses_symlink_backing(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            external = workspace / 'external'
            external.mkdir()
            parent = workspace / 'shared-storage' / 'android-media'
            parent.mkdir(parents=True)
            (parent / '0').symlink_to(external)
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                aaas_storage.prepare_backing_directory(workspace)

    def test_refuses_symlink_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            external = workspace / 'external'
            external.mkdir()
            (workspace / 'shared-storage').symlink_to(external)
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                aaas_storage.prepare_backing_directory(workspace)


if __name__ == '__main__':
    unittest.main()
