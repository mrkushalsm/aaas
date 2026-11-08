from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_profiles


class AndroidProfileTests(unittest.TestCase):
    def rootfs(self, root):
        profile = aaas_profiles.profiles()['android16-ranchu-x86_64']
        for relative in profile['required_files']:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        (root / 'system/build.prop').write_text(
            'ro.build.version.release=16\nro.build.version.sdk=36\n'
            'ro.product.cpu.abi=x86_64\nro.build.id=BE2A.250530.026.D1\n')
        (root / 'vendor/build.prop').write_text(
            'ro.vendor.build.id=BE2A.250530.026.D1\nro.hardware.power=ranchu\n')

    def test_matching_image_properties_do_not_claim_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'rootfs'
            root.mkdir()
            self.rootfs(root)
            result = aaas_profiles.inspect_rootfs(root)
        self.assertEqual(result['compatibility'], 'MATCH')
        self.assertEqual(result['provenance'], 'UNVERIFIED')
        self.assertFalse(result['provisionable'])

    def test_rootfs_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'rootfs'
            root.mkdir()
            link = Path(temporary) / 'link'
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(aaas_profiles.ProfileError, 'symlink'):
                aaas_profiles.inspect_rootfs(link)

    def test_sdk_archive_inspection_does_not_claim_runtime_compatibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'synthetic.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('system.img', b'not a runtime image')
            result = aaas_profiles.inspect_archive(archive)
        self.assertIn('system.img', result['layout'])
        self.assertEqual(result['compatibility'], 'UNVERIFIED')
        self.assertEqual(len(result['sha256']), 64)
        self.assertFalse(result['declared_match'])
        self.assertIn('emulator', result['archive_type'].lower())


if __name__ == '__main__':
    unittest.main()
