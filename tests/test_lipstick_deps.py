import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.android_repo_lock import SHA


class LipstickDependencyTest(unittest.TestCase):
    def test_fork_pin_is_immutable(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / 'manifests/sources.json').read_text())
        fork = next(s for s in manifest['sources'] if s['name'] == 'sailfish-qtwayland')
        self.assertTrue(SHA.fullmatch(fork['revision']))
        self.assertEqual(fork['kind'], 'standalone-git')


if __name__ == '__main__': unittest.main()
