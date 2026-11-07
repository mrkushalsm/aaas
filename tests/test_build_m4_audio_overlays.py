import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_m4_audio_overlays as overlays


class AudioOverlayExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / 'system.raw.img'
        self.image.write_bytes(b'synthetic image identity')
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.output = self.root / 'overlays'

    def tearDown(self):
        self.temp.cleanup()

    def test_extracts_read_only_image_files_and_records_provenance(self):
        calls = []
        real_run = overlays.subprocess.run

        def run(command, **kwargs):
            calls.append(command)
            if command[0] == 'guestmount':
                mount = Path(command[-1])
                for name, (relative, _) in overlays.FILES.items():
                    target = mount / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile('/bin/ls', target)
                return type('Result', (), {'stdout': ''})()
            if command[0] == 'guestunmount':
                return type('Result', (), {'stdout': ''})()
            return real_run(command, **kwargs)

        with patch.object(overlays.subprocess, 'run', side_effect=run), \
             patch.object(overlays.workspace_guard, 'check') as guard:
            manifest = overlays.extract(self.image, self.output, self.workspace)

        self.assertIn('--ro', calls[0])
        self.assertEqual('/dev/sda', calls[0][calls[0].index('-m') + 1])
        self.assertEqual(set(overlays.FILES), set(manifest['files']))
        self.assertEqual(overlays.sha256_file(self.image), manifest['system_image_sha256'])
        saved = json.loads((self.output / overlays.MANIFEST).read_text())
        self.assertEqual(manifest, saved)
        self.assertEqual(2, guard.call_count)

    def test_cache_rejects_tampered_overlay(self):
        self.output.mkdir()
        for name in overlays.FILES:
            shutil.copyfile('/bin/ls', self.output / name)
        image_hash = overlays.sha256_file(self.image)
        manifest = {'schema_version': 1, 'system_image_sha256': image_hash,
                    'files': {name: {'sha256': overlays.sha256_file(self.output / name)}
                              for name in overlays.FILES}}
        (self.output / overlays.MANIFEST).write_text(json.dumps(manifest))
        self.assertIsNotNone(overlays.validate_outputs(self.output, image_hash))
        (self.output / 'audioserver').write_bytes(b'tampered')
        self.assertIsNone(overlays.validate_outputs(self.output, image_hash))

    def test_cache_rejects_different_system_image(self):
        self.output.mkdir()
        image_hash = overlays.sha256_file(self.image)
        manifest = {'schema_version': 1, 'system_image_sha256': '0' * 64,
                    'files': {}}
        (self.output / overlays.MANIFEST).write_text(json.dumps(manifest))
        self.assertIsNone(overlays.validate_outputs(self.output, image_hash))


if __name__ == '__main__':
    unittest.main()
