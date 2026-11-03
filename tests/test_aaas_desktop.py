from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import aaas_desktop


class DesktopLauncherTests(unittest.TestCase):
    def test_package_identity_is_validated(self):
        with self.assertRaises(ValueError):
            aaas_desktop.render_launcher("com.example;touch /tmp/pwn", "App")

    def test_exec_quoting_and_percent_field_codes_are_safe(self):
        entry = aaas_desktop.render_launcher("com.example.reader", "Reader % Copy")
        self.assertIn("Name=Reader % Copy", entry)
        exec_line = next(line for line in entry.splitlines() if line.startswith("Exec="))
        self.assertEqual(aaas_desktop.desktop_exec_quote("reader%copy"),
                         '"reader%%copy"')
        self.assertIn('"--package" "com.example.reader"', exec_line)

    def test_installs_atomically_in_user_applications_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"XDG_DATA_HOME": directory}
            with patch.object(aaas_desktop, "ROOT", Path(directory) / "repo"):
                path = aaas_desktop.install_launcher(
                    "com.example.reader", "Reader", env=env)
            self.assertEqual(path, Path(directory) / "applications/aaas-com.example.reader.desktop")
            self.assertTrue(path.is_file())
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertIn("Name=Reader", path.read_text())
            self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_launcher_refuses_invalid_icon_and_multiline_name(self):
        with tempfile.TemporaryDirectory() as directory:
            icon = Path(directory) / "icon.png"
            icon.write_bytes(b"not an image, but an existing icon path")
            with self.assertRaises(ValueError):
                aaas_desktop.render_launcher("com.example.reader", "Bad\nName")
            with self.assertRaises(ValueError):
                aaas_desktop.render_launcher("com.example.reader", "Reader", "icon.png")

    def test_anchor_is_distinct(self):
        self.assertNotEqual(aaas_desktop._choose_anchor("com.android.settings"),
                            "com.android.settings")
        with patch.object(aaas_desktop, "ANCHORS", ("com.android.settings",)):
            with self.assertRaises(RuntimeError):
                aaas_desktop._choose_anchor("com.android.settings")


if __name__ == "__main__":
    unittest.main()
