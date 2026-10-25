import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from scripts import audit_android_runtime as audit


class RuntimeAuditTest(unittest.TestCase):
    def test_graphics_candidate_is_pinned_and_unverified(self):
        manifest = Path(__file__).resolve().parent.parent / 'manifests/android-graphics-candidates.json'
        data = json.loads(manifest.read_text())
        candidate = data['candidates'][0]
        self.assertRegex(candidate['revision'], r'^[0-9a-f]{40}$')
        self.assertIn('allocator-service.minigbm', candidate['modules'][0])
        self.assertIn('mapper.minigbm', candidate['modules'])
        self.assertEqual(candidate['status'], 'source_verified_build_unattempted')

    def test_classifies_modified_and_original_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root'
            parts = Path(tmp) / 'parts'
            (root / 'system/bin').mkdir(parents=True)
            parts.mkdir()
            (parts / 'system.raw.img').write_bytes(b'image')
            (root / 'system/bin/first').write_bytes(b'original')
            (root / 'system/bin/second').write_bytes(b'patched')
            with patch.object(audit, 'original_bytes', return_value=b'original'):
                result = audit.audit(root, parts,
                                     ('system/bin/first', 'system/bin/second'))
            self.assertEqual([item['status'] for item in result],
                             ['identical', 'modified'])
            self.assertNotEqual(result[1]['original_sha256'],
                                result[1]['current_sha256'])

    def test_missing_partition_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = audit.audit(Path(tmp), Path(tmp), ('vendor/bin/service',))
            self.assertEqual(result[0]['status'], 'missing_partition')

    def test_detects_unexpected_overlay_and_modified_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay = root / 'system/lib64/libselinux_shim.so'
            overlay.parent.mkdir(parents=True)
            overlay.write_bytes(b'shim')
            findings = audit.audit_overlays(root)
            self.assertEqual(findings[0]['status'], 'unexpected_overlay')
            with patch.object(audit.subprocess, 'run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = ' M src/Vulkan/libVulkan.cpp\n'
                source = audit.audit_source_checkout(root)
            self.assertEqual(source[0]['status'], 'source_modified')
            self.assertEqual(source[0]['modified_entries'], 1)


if __name__ == '__main__':
    unittest.main()
