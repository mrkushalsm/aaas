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
    def test_validate_media_scan_path_allows_missing_leaf_for_deletion_reconcile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Download').mkdir()
            self.assertEqual(
                aaas_storage.validate_media_scan_path(
                    'Download/missing image.png', root),
                root / 'Download/missing image.png')

    def test_validate_media_scan_path_rejects_traversal_private_and_symlink_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Download').mkdir()
            (root / 'Android' / 'data').mkdir(parents=True)
            (root / 'outside').mkdir()
            (root / 'Download' / 'escape.png').symlink_to(root / 'outside')
            for value in ('../outside/file.png', '/tmp/file.png',
                          'Android/data/private.jpg', 'Android/obb/game.obb',
                          'Download/escape.png', 'Download/invalid\nname.png'):
                with self.subTest(path=value), self.assertRaises(ValueError):
                    aaas_storage.validate_media_scan_path(value, root)

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
                self.assertIn('group::rwx', acl)
                self.assertIn('default:group::rwx', acl)
                public_acl = subprocess.run(
                    ['getfacl', '--omit-header', '--numeric',
                     str(path / 'Documents')],
                    check=True, capture_output=True, text=True).stdout.splitlines()
                self.assertIn('group::rwx', public_acl)
                self.assertIn('default:group::rwx', public_acl)
                private_acl = subprocess.run(
                    ['getfacl', '--omit-header', '--numeric',
                     str(path / 'Android' / 'data')],
                    check=True, capture_output=True, text=True).stdout.splitlines()
                self.assertIn('group::---', private_acl)
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

    def test_mapped_owner_acl_repair_works_without_host_path_traversal(self):
        if not all(shutil.which(name) for name in
                   ('unshare', 'newuidmap', 'newgidmap', 'setpriv', 'mount',
                    'setfacl', 'getfacl')):
            self.skipTest('rootless namespace and ACL tools are unavailable')
        with tempfile.TemporaryDirectory(prefix='aaas-acl-repair-') as directory:
            root = Path(directory) / 'android-media'
            root.mkdir()
            # Model the Android-owned, host-inaccessible mode observed after
            # the removable NTFS3 volume was remounted.
            aaas_storage._run_mapped_storage_command(
                root,
                'read ready; cd -- "$1" || exit; '
                'chown 1023:1023 .; chmod 550 .; setfacl -b .',
                'host',
            )
            self.assertEqual(
                root.stat().st_uid,
                aaas_storage.SUBID_BASE + aaas_storage.ANDROID_MEDIA_RW_ID - 1,
            )
            self.assertFalse(os.access(root, os.R_OK | os.W_OK | os.X_OK))

            aaas_storage.ensure_host_access(root)

            acl = set(aaas_storage._acl_entries(root))
            host_acl = {
                f'user:{os.getuid()}:rwx',
                f'default:user:{os.getuid()}:rwx',
            }
            self.assertTrue(host_acl.issubset(acl))
            self.assertTrue(os.access(root, os.R_OK | os.W_OK | os.X_OK))


if __name__ == '__main__':
    unittest.main()
