import json
import unittest
from pathlib import Path
from scripts.android_repo_lock import SHA


class LipstickDependencyTest(unittest.TestCase):
    def test_fork_pin_is_immutable(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / 'manifests/sources.json').read_text())
        fork = next(s for s in manifest['sources'] if s['name'] == 'sailfish-qtwayland')
        self.assertTrue(SHA.fullmatch(fork['revision']))
        self.assertEqual(fork['kind'], 'standalone-git')

    def test_isolated_image_notices_and_missing_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        inventory = json.loads((root / 'tests/fixtures/lipstick/image-packages-and-notices.json').read_text())
        self.assertGreater(len(inventory['packages']), 300)
        self.assertEqual(inventory['notice_missing'], [])
        closure = json.loads((root / 'tests/fixtures/lipstick/dependencies-container.json').read_text())
        missing = {e['module'] for e in closure['immediate_requirements'] if e['state'] == 'environment-pkgconfig-missing'}
        self.assertIn('pkgconfig(mlite5)', missing)
        self.assertIn('pkgconfig(mce-qt5)', missing)


if __name__ == '__main__': unittest.main()
