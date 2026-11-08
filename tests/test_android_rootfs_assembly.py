import json
import shutil
import sys
from pathlib import Path
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import assemble_android_rootfs as assembly
import aaas_profiles


class AndroidRootfsAssemblyTests(unittest.TestCase):
    def test_tar_paths_are_normalized_and_escape_paths_rejected(self):
        self.assertEqual(assembly._safe_tar_member('./system/bin/init'), 'system/bin/init')
        for path in ('/etc/passwd', '../outside', 'system/../../outside'):
            with self.subTest(path=path), self.assertRaises(assembly.AssemblyError):
                assembly._safe_tar_member(path)

    def test_workspace_output_directories_reject_symlink_components(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / 'workspace'
            workspace.mkdir()
            outside = Path(temporary) / 'outside'
            outside.mkdir()
            (workspace / 'cache').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(assembly.AssemblyError, 'not a real directory'):
                assembly._workspace_directory(workspace, 'cache/android-images')

    def test_selinux_success_shim_and_preload_are_rejected(self):
        items = [{'partition': 'vendor', 'path': 'lib64/libselinux_shim.so'}]
        result = assembly._validate_no_selinux_bypass(items, [])
        self.assertEqual(result['status'], 'FAIL')
        result = assembly._validate_no_selinux_bypass([], ['vendor/etc/init/aaas.rc'])
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(assembly._validate_no_selinux_bypass([], [])['status'], 'PASS')

    def test_mountpoint_preparation_preserves_image_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'sdcard').symlink_to('/storage/self/primary')
            created = assembly._prepare_mountpoints(root)
            self.assertTrue((root / 'sdcard').is_symlink())
            self.assertTrue((root / 'data').is_dir())
            self.assertIn('data', created)

    def test_critical_file_hash_verification_uses_system_as_root_paths(self):
        audit = {'entries': [
            {'path': 'system/bin/apexd', 'source_partition': 'system',
             'original_sha256': 'a' * 64},
            {'path': 'vendor/etc/init/vendor.rc', 'source_partition': 'vendor',
             'original_sha256': 'b' * 64},
        ]}
        items = [
            {'partition': 'system', 'path': 'system/bin/apexd', 'sha256': 'a' * 64},
            {'partition': 'vendor', 'path': 'etc/init/vendor.rc', 'sha256': 'b' * 64},
        ]
        with mock.patch.object(assembly, '__file__', str(Path('/repo/scripts/assembler.py'))), \
                mock.patch('pathlib.Path.read_text', return_value=json.dumps(audit)):
            result = assembly._verify_critical_files(items)
        self.assertEqual(len(result['verified_base_critical_files']), 2)

    def test_transformation_map_accounts_for_all_critical_audit_entries(self):
        root = Path(__file__).resolve().parents[1]
        audit = json.loads((root / 'manifests/android16-diagnostic-rootfs-audit.json').read_text())
        mapping = json.loads((root / 'manifests/android16-reconstruction-transformations.json').read_text())
        critical = {e['path'] for e in audit['entries']
                    if e['path'].startswith(('system/', 'system_ext/', 'vendor/'))}
        mapped = ({e['path'] for e in mapping['entries']}
                  | {e['path'] for e in mapping['excluded_security_artifacts']})
        mapped.discard('sources/swiftshader')
        self.assertEqual(critical, mapped)
        self.assertEqual(len(mapping['excluded_security_artifacts']), 2)
        self.assertEqual(mapping['status'], 'PARTIAL')

    @unittest.skipUnless(shutil.which('unshare'), 'unshare unavailable')
    def test_validated_stage_cleanup_uses_subordinate_uid_map(self):
        profile_id = 'android16-ranchu-x86_64'
        build_id = aaas_profiles.profiles()[profile_id]['build_id']
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            stage = workspace / 'tmp/android-rootfs-build' / f'{profile_id}-{build_id}'
            (stage / 'rootfs/system').mkdir(parents=True)
            (stage / '.aaas-assembly-staging').write_text(json.dumps({
                'profile': profile_id, 'archive_sha256': 'c' * 64,
                'created_by': 'scripts/assemble_android_rootfs.py',
            }))
            assembly._remove_owned_stage(workspace, stage, profile_id, 'c' * 64)
            self.assertFalse(stage.exists())


if __name__ == '__main__':
    unittest.main()
