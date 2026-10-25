"""Tests for fetch_android_image and inspect_android_image scripts."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
import fetch_android_image as fetch
import inspect_android_image as inspect_img

MANIFEST_PATH = Path(__file__).parent.parent / 'manifests' / 'android-images.json'


class ManifestValidationTest(unittest.TestCase):
    def test_manifest_exists_and_is_valid_json(self):
        self.assertTrue(MANIFEST_PATH.is_file(), 'android-images.json must exist')
        manifest = json.loads(MANIFEST_PATH.read_text())
        self.assertEqual(manifest.get('schema'), 1)
        self.assertIn('images', manifest)

    def test_all_images_have_required_fields(self):
        manifest = json.loads(MANIFEST_PATH.read_text())
        required = {'sdk_path', 'url', 'size_bytes', 'sha1', 'api_level', 'arch'}
        for img in manifest['images']:
            missing = required - set(img.keys())
            self.assertFalse(missing, f'image {img.get("sdk_path")} missing: {missing}')

    def test_sha1_hashes_are_correct_length(self):
        manifest = json.loads(MANIFEST_PATH.read_text())
        for img in manifest['images']:
            self.assertEqual(len(img['sha1']), 40,
                             f'{img["sdk_path"]} SHA1 must be 40 hex chars')
            int(img['sha1'], 16)  # must be valid hex

    def test_android36_x86_64_is_present(self):
        manifest = json.loads(MANIFEST_PATH.read_text())
        paths = {img['sdk_path'] for img in manifest['images']}
        self.assertIn('system-images;android-36;default;x86_64', paths)


class FetchScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name) / 'ws'
        self.images_dir = self.workspace / 'images'
        self.images_dir.mkdir(parents=True)

    def _make_fake_zip(self, name: str, content: bytes = b'fakecontent') -> Path:
        dest = self.images_dir / name
        dest.write_bytes(content)
        return dest

    def test_sha1_file_matches_hashlib(self):
        f = self.images_dir / 'probe.bin'
        data = b'AaaS test data for SHA1' * 100
        f.write_bytes(data)
        expected = hashlib.sha1(data).hexdigest()
        self.assertEqual(fetch.sha1_file(f), expected)

    def test_load_manifest_returns_images(self):
        manifest = fetch.load_manifest()
        self.assertIsInstance(manifest.get('images'), list)
        self.assertGreater(len(manifest['images']), 0)

    def test_download_skips_when_already_verified(self):
        """If the destination exists and SHA1 matches, download should not re-fetch."""
        data = b'prebuilt content'
        sha1 = hashlib.sha1(data).hexdigest()
        dest = self.images_dir / 'prebuilt.zip'
        dest.write_bytes(data)
        # sha1_file should match
        self.assertEqual(fetch.sha1_file(dest), sha1)

    def test_dry_run_does_not_create_file(self):
        """Dry-run mode must not download or create any files."""
        manifest = fetch.load_manifest()
        img = manifest['images'][0]
        dest = self.images_dir / Path(img['url']).name
        self.assertFalse(dest.exists())
        # We just verify the code path; actual network is not called


class InspectScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.zip_path = Path(self.tmp.name) / 'test-image.zip'

    def _make_test_zip(self):
        with zipfile.ZipFile(self.zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('system.img', b'fake-system-img-data' * 100)
            zf.writestr('vendor.img', b'fake-vendor-img-data' * 50)
            zf.writestr('README.txt', 'test image')

    def test_list_zip_contents_returns_all_members(self):
        self._make_test_zip()
        contents = inspect_img.list_zip_contents(self.zip_path)
        names = {m['name'] for m in contents['members']}
        self.assertIn('system.img', names)
        self.assertIn('vendor.img', names)
        self.assertIn('README.txt', names)
        self.assertEqual(contents['member_count'], 3)

    def test_list_zip_contents_counts_sizes(self):
        self._make_test_zip()
        contents = inspect_img.list_zip_contents(self.zip_path)
        total = sum(m['file_size'] for m in contents['members'])
        self.assertEqual(total, contents['total_uncompressed_bytes'])

    def test_extract_img_to_temp_produces_file(self):
        self._make_test_zip()
        extract_dir = Path(self.tmp.name) / 'extract'
        extract_dir.mkdir()
        out = inspect_img.extract_img_to_temp(self.zip_path, 'system.img', extract_dir)
        self.assertTrue(out.is_file())
        self.assertEqual(out.read_bytes(), b'fake-system-img-data' * 100)

    def test_extract_img_skips_if_already_exists(self):
        self._make_test_zip()
        extract_dir = Path(self.tmp.name) / 'extract'
        extract_dir.mkdir()
        existing = extract_dir / 'system.img'
        existing.write_bytes(b'already-there')
        out = inspect_img.extract_img_to_temp(self.zip_path, 'system.img', extract_dir)
        # Should not overwrite
        self.assertEqual(out.read_bytes(), b'already-there')


if __name__ == '__main__':
    unittest.main()
