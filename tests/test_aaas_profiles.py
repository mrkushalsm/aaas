from pathlib import Path
import sys
import tempfile
import json
import unittest
import zipfile
import hashlib
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_profiles


class AndroidProfileTests(unittest.TestCase):
    def test_profile_classification_is_explicit_and_validated(self):
        profile = aaas_profiles.profiles()['android16-ranchu-x86_64']
        self.assertEqual(profile['trust_classification'], 'DIAGNOSTIC_LEGACY')
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / 'profiles.json'
            value = json.loads(aaas_profiles.PROFILE_MANIFEST.read_text())
            value['profiles'][0]['trust_classification'] = 'TRUST_ME'
            manifest.write_text(json.dumps(value))
            with mock.patch.object(aaas_profiles, 'PROFILE_MANIFEST', manifest):
                with self.assertRaisesRegex(aaas_profiles.ProfileError,
                                            'invalid trust classification'):
                    aaas_profiles.profiles()

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
        self.assertEqual(result['trust_classification'], 'DIAGNOSTIC_LEGACY')
        self.assertEqual(result['security']['status'], 'UNVERIFIED')
        self.assertEqual(result['security']['enforcement'], 'UNVERIFIED')
        self.assertFalse(result['provisionable'])

    def test_candidate_manifest_is_reported_as_incomplete_and_never_provisionable(self):
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / 'candidate'
            root = candidate / 'rootfs'
            root.mkdir(parents=True)
            self.rootfs(root)
            profile = aaas_profiles.profiles()['android16-ranchu-x86_64']
            inventory = b'{"sample":true}\n'
            (candidate / 'file-inventory.jsonl').write_bytes(inventory)
            map_hash = hashlib.sha256(aaas_profiles.TRANSFORMATION_MANIFEST.read_bytes()).hexdigest()
            (candidate / 'manifest.json').write_text(json.dumps({
                'schema': 1, 'status': 'ASSEMBLED_INCOMPLETE',
                'profile': profile['id'], 'build_id': profile['build_id'],
                'trust_classification': 'RECONSTRUCTED_EXPERIMENTAL',
                'runtime_ready': False, 'candidate_rootfs_relative': 'rootfs',
                'distribution_approved': False,
                'source_archive': {'size_bytes': profile['source_image']['size_bytes'],
                                   'sha1': profile['source_image']['sha1'],
                                   'sha256': profile['source_image']['sha256']},
                'file_inventory': {'path': 'file-inventory.jsonl',
                                   'sha256': hashlib.sha256(inventory).hexdigest()},
                'historical_transformations': {
                    'map': 'manifests/android16-reconstruction-transformations.json',
                    'map_sha256': map_hash},
                'critical_base_file_verification': {'mismatch_count': 0,
                                                    'missing_count': 0},
                'security': {'authorization_bypass_artifacts': {'status': 'PASS'}},
            }))
            result = aaas_profiles.inspect_rootfs(root)
        self.assertEqual(result['assembly_status'], 'ASSEMBLED_INCOMPLETE')
        self.assertEqual(result['trust_classification'], 'RECONSTRUCTED_EXPERIMENTAL')
        self.assertEqual(result['provenance'], 'ASSEMBLY_RECORD_VALID')
        self.assertEqual(result['assembly_record_validation'], 'PASS')
        self.assertFalse(result['runtime_ready'])
        self.assertFalse(result['provisionable'])

    def test_candidate_manifest_with_corrupt_inventory_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / 'candidate'
            root = candidate / 'rootfs'
            root.mkdir(parents=True)
            self.rootfs(root)
            profile = aaas_profiles.profiles()['android16-ranchu-x86_64']
            (candidate / 'file-inventory.jsonl').write_text('changed\n')
            (candidate / 'manifest.json').write_text(json.dumps({
                'schema': 1, 'profile': profile['id'],
                'candidate_rootfs_relative': 'rootfs',
                'status': 'ASSEMBLED_INCOMPLETE',
                'runtime_ready': False, 'distribution_approved': False,
                'source_archive': {'size_bytes': profile['source_image']['size_bytes'],
                                   'sha1': profile['source_image']['sha1'],
                                   'sha256': profile['source_image']['sha256']},
                'file_inventory': {'path': 'file-inventory.jsonl', 'sha256': '0' * 64},
            }))
            result = aaas_profiles.inspect_rootfs(root)
        self.assertEqual(result['assembly_record_validation'], 'FAIL')
        self.assertEqual(result['provenance'], 'UNVERIFIED')

    def test_selinux_success_shim_makes_rootfs_explicitly_unsafe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'rootfs'
            root.mkdir()
            self.rootfs(root)
            shim = root / 'vendor/lib64/libselinux_shim.so'
            shim.parent.mkdir(parents=True, exist_ok=True)
            shim.write_bytes(b'diagnostic shim marker')
            init = root / 'vendor/etc/init/aaas.rc'
            init.parent.mkdir(parents=True)
            init.write_text('    setenv LD_PRELOAD /vendor/lib64/libselinux_shim.so\n')
            result = aaas_profiles.inspect_rootfs(root)
        self.assertEqual(result['security']['status'], 'BYPASS_DETECTED')
        self.assertEqual(result['security']['enforcement'], 'UNVERIFIED')
        self.assertFalse(result['provisionable'])
        self.assertTrue(result['provisioning_blockers'])

    def test_static_inspection_never_claims_selinux_enforcement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'rootfs'
            root.mkdir()
            self.rootfs(root)
            manifest = Path(temporary) / 'profiles.json'
            value = json.loads(aaas_profiles.PROFILE_MANIFEST.read_text())
            value['profiles'][0]['provisioning']['automatically_installable'] = True
            manifest.write_text(json.dumps(value))
            with mock.patch.object(aaas_profiles, 'PROFILE_MANIFEST', manifest):
                result = aaas_profiles.inspect_rootfs(root)
        self.assertEqual(result['security']['enforcement'], 'UNVERIFIED')
        self.assertFalse(result['provisionable'])

    def test_diagnostic_audit_manifest_keeps_unknown_changes_unresolved(self):
        manifest_path = (Path(__file__).resolve().parents[1] /
                         'manifests/android16-diagnostic-rootfs-audit.json')
        manifest = json.loads(manifest_path.read_text())
        modified = [item for item in manifest['entries']
                    if item['classification'] == 'UNRESOLVED' and
                    item.get('original_sha256')]
        self.assertEqual(len(modified), 16)
        self.assertFalse(manifest['security_gate']['provisionable'])
        self.assertFalse(manifest['security_gate']['selinux_enforcement_verified'])

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
