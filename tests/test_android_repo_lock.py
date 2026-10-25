import tempfile
import unittest
from pathlib import Path
from scripts.android_repo_lock import manifest_projects, validate_locked


class RepoLockTest(unittest.TestCase):
    def test_include_override_and_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'default.xml').write_text('<manifest><default revision="moving"/><project name="old" path="x"/><include name="extra.xml"/></manifest>')
            (root / 'extra.xml').write_text('<manifest><remove-project path="x"/><project name="new" path="x" revision="' + 'a' * 40 + '"/></manifest>')
            projects, _ = manifest_projects(root)
            self.assertEqual(projects['x']['revision'], 'a' * 40)

    def test_lock_rejects_branches_and_override_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock.xml'
            path.write_text('<manifest><project name="x" path="x" revision="main"/></manifest>')
            with self.assertRaisesRegex(ValueError, 'unpinned'):
                validate_locked(path, {})
            path.write_text('<manifest><project name="x" path="x" revision="' + 'a' * 40 + '"/></manifest>')
            with self.assertRaisesRegex(ValueError, 'override mismatch'):
                validate_locked(path, {'x': 'b' * 40})
            self.assertEqual(validate_locked(path, {'x': 'a' * 40})['x'], 'a' * 40)
            with self.assertRaisesRegex(ValueError, 'project path mismatch'):
                validate_locked(path, {'x': 'a' * 40}, {'x', 'y'})


if __name__ == '__main__':
    unittest.main()
