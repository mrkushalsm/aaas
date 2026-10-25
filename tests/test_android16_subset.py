import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Android16SubsetTests(unittest.TestCase):
    def test_release_lock_has_immutable_unique_projects(self):
        data = json.loads((ROOT / "manifests/android16-r1-subset.json").read_text())
        self.assertEqual(data["release_tag"], "android-16.0.0_r1")
        self.assertRegex(data["manifest_revision"], r"^[0-9a-f]{40}$")
        self.assertRegex(data["manifest_sha256"], r"^[0-9a-f]{64}$")
        paths = [project["path"] for project in data["projects"]]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue({"art", "system/apex", "system/core", "system/sepolicy",
                         "frameworks/native", "hardware/interfaces", "external/minigbm",
                         "build/soong"}.issubset(paths))
        for project in data["projects"]:
            self.assertRegex(project["revision"], r"^[0-9a-f]{40}$")
            self.assertTrue(project["repository"].startswith("https://android.googlesource.com/"))


if __name__ == "__main__":
    unittest.main()
