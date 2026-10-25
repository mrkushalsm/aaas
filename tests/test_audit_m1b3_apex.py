import io
import tempfile
import unittest
from pathlib import Path
import zipfile

from scripts.audit_m1b3_apex import audit, manifest


def field(number, value):
    if isinstance(value, int):
        return bytes([number << 3, value])
    encoded = value.encode()
    return bytes([(number << 3) | 2, len(encoded)]) + encoded


class ApexAuditTests(unittest.TestCase):
    def test_manifest_identity_and_dependencies(self):
        parsed = manifest(field(1, "com.android.test") + field(2, 3) +
                          field(7, "libprovided.so") + field(8, "libneeded.so"))
        self.assertEqual(parsed["version"], 3)
        self.assertEqual(parsed["requires"], ["libneeded.so"])

    def test_truncated_manifest_fails(self):
        with self.assertRaises(ValueError):
            manifest(b"\x0a\x05ab")

    def test_package_identity_is_checked_without_activation_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "apex").mkdir()
            (root / "system/apex").mkdir(parents=True)
            (root / "apex/apex-info-list.xml").write_text(
                '<apex-info-list><apex-info moduleName="com.android.test" '
                'modulePath="/system/apex/com.android.test.apex" versionCode="3" '
                'isActive="false"/></apex-info-list>')
            with zipfile.ZipFile(root / "system/apex/com.android.test.apex", "w") as package:
                package.writestr("apex_manifest.pb", field(1, "com.android.test") + field(2, 3))
            result = audit(root)
            self.assertEqual(result["errors"], [])
            self.assertFalse(result["activation_verified"])
            (root / "apex/apex-info-list.xml").write_text(
                (root / "apex/apex-info-list.xml").read_text().replace('versionCode="3"', 'versionCode="4"'))
            self.assertIn("differs", audit(root)["errors"][0]["error"])


if __name__ == "__main__":
    unittest.main()
