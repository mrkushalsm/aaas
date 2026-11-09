from pathlib import Path
import base64
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import aaas_desktop


class DesktopLauncherTests(unittest.TestCase):
    def test_detects_only_an_installed_active_persistent_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory)
            unit = config_home / 'systemd/user/aaas-runtime.service'
            unit.parent.mkdir(parents=True)
            unit.write_text('[Service]\n')
            with patch.object(aaas_desktop.aaas_config, 'xdg_paths',
                              return_value={'config_home': config_home}), \
                    patch.object(aaas_desktop.subprocess, 'run', return_value=
                                 SimpleNamespace(returncode=0, stdout='active\n')):
                self.assertTrue(aaas_desktop._persistent_service_active())
            with patch.object(aaas_desktop.aaas_config, 'xdg_paths',
                              return_value={'config_home': config_home}), \
                    patch.object(aaas_desktop.subprocess, 'run', return_value=
                                 SimpleNamespace(returncode=3, stdout='inactive\n')):
                self.assertFalse(aaas_desktop._persistent_service_active())

    def test_package_identity_is_validated(self):
        with self.assertRaises(ValueError):
            aaas_desktop.render_launcher("com.example;touch /tmp/pwn", "App")

    def test_relative_xdg_data_home_and_control_character_names_are_rejected(self):
        with self.assertRaises(ValueError):
            aaas_desktop.applications_dir({"XDG_DATA_HOME": "relative/path"})
        with self.assertRaises(ValueError):
            aaas_desktop.render_launcher("com.example.reader", "Bad\x01Name")

    def test_exec_quoting_and_percent_field_codes_are_safe(self):
        entry = aaas_desktop.render_launcher("com.example.reader", "Reader % Copy")
        self.assertIn("Name=Reader % Copy", entry)
        exec_line = next(line for line in entry.splitlines() if line.startswith("Exec="))
        self.assertEqual(aaas_desktop.desktop_exec_quote("reader%copy"),
                         '"reader%%copy"')
        self.assertIn('"--package" "com.example.reader"', exec_line)

    def test_catalog_launcher_prefers_verified_installed_runtime_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_home = root / "data"
            runtime = root / "installation" / "runtime"
            scripts = runtime / "scripts"
            scripts.mkdir(parents=True)
            installed_script = scripts / "aaas_desktop.py"
            installed_script.write_text("# installed runtime\n")
            catalog_root = data_home / "aaas"
            catalog_root.mkdir(parents=True)
            (catalog_root / "installation.json").write_text(json.dumps({
                "classification": "LOCAL_DEVELOPMENT_DIAGNOSTIC",
                "paths": {"runtime": str(runtime)}}))
            entry = aaas_desktop.render_launcher(
                "com.example.reader", "Reader", env={"XDG_DATA_HOME": str(data_home)})
            self.assertIn(str(installed_script), entry)
            self.assertNotIn(str(aaas_desktop.ROOT), entry)
            aaas_desktop.sync_package_catalog([{
                "package": "com.example.reader", "activity": "com.example.Reader",
                "label": "Reader", "version_code": 1, "version_name": "1",
                "enabled": True, "icon_png": b"",
            }], env={"XDG_DATA_HOME": str(data_home)})
            desktop = data_home / "applications/aaas-catalog-com.example.reader.desktop"
            self.assertIn(str(installed_script), desktop.read_text())
            self.assertIn("Android SELinux enforcement unavailable", desktop.read_text())
            self.assertIn("X-AaaS-Security-Classification=LOCAL_DEVELOPMENT_DIAGNOSTIC",
                          desktop.read_text())

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

    @staticmethod
    def _catalog_file(path, request="a" * 32, rows=(), truncated="0"):
        path.write_text("\t".join(("AAAS-CATALOG", "1", request, truncated)) + "\n" +
                        "".join("\t".join((
                            *(base64.b64encode(value.encode()).decode() for value in row[:3]),
                            row[3], base64.b64encode(row[4].encode()).decode(), row[5],
                            base64.b64encode(row[6].encode()).decode() if row[6] else "",
                        )) + "\n" for row in rows))

    @staticmethod
    def _row(package, label, version="1", activity=None, icon=""):
        values = (package, activity or package + ".MainActivity", label, version,
                  "1.0", "1", icon)
        return tuple(values)

    def test_catalog_parser_deduplicates_and_validates_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.tsv"
            self._catalog_file(path, rows=(
                self._row("com.example.reader", "Reader"),
                self._row("com.example.reader", "Duplicate"),
                self._row("com.example.notes", "Notes"),
            ))
            parsed = aaas_desktop.parse_package_catalog(path, "a" * 32)
            self.assertEqual([item["package"] for item in parsed["applications"]],
                             ["com.example.notes", "com.example.reader"])
            self.assertEqual(len(parsed["applications"]), 2)
            self.assertFalse(parsed["truncated"])
            self._catalog_file(path, request="b" * 32,
                               rows=(self._row("com.example.reader", "Reader"),))
            with self.assertRaises(ValueError):
                aaas_desktop.parse_package_catalog(path, "a" * 32)

    def test_catalog_parser_rejects_invalid_package_activity_and_disabled_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.tsv"
            for row in (self._row("com.example;evil", "Bad"),
                        self._row("com.example.reader", "Bad", activity="../../evil"),
                        (*self._row("com.example.reader", "Disabled")[:5], "0", "")):
                self._catalog_file(path, rows=(row,))
                with self.assertRaises(ValueError):
                    aaas_desktop.parse_package_catalog(path, "a" * 32)

    def test_catalog_creates_safe_entries_fallback_icons_and_reconciles_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"XDG_DATA_HOME": directory}
            with patch.object(aaas_desktop, "ROOT", Path(directory) / "repo"):
                first = aaas_desktop.sync_package_catalog([
                    {"package": "com.example.reader", "activity": "com.example.Reader",
                     "label": "Reader % Copy", "version_code": 1, "version_name": "1",
                     "enabled": True, "icon_png": b""},
                    {"package": "com.example.notes", "activity": "com.example.Notes",
                     "label": "Notes", "version_code": 3, "version_name": "3",
                     "enabled": True, "icon_png": b""},
                ], env=env)
            self.assertEqual(first["count"], 2)
            reader = Path(directory) / "applications/aaas-catalog-com.example.reader.desktop"
            unrelated = Path(directory) / "applications/unrelated.desktop"
            unrelated.write_text("keep")
            entry = reader.read_text()
            self.assertIn("Name=Reader % Copy", entry)
            self.assertIn("Icon=application-x-executable", entry)
            self.assertIn('"--package" "com.example.reader"', entry)
            second = aaas_desktop.sync_package_catalog([
                {"package": "com.example.reader", "activity": "com.example.Reader",
                 "label": "Reader Updated", "version_code": 2, "version_name": "2",
                 "enabled": True, "icon_png": b""},
            ], env=env)
            self.assertEqual(second["count"], 1)
            self.assertIn("Name=Reader Updated", reader.read_text())
            self.assertFalse((Path(directory) /
                              "applications/aaas-catalog-com.example.notes.desktop").exists())
            self.assertEqual(unrelated.read_text(), "keep")
            catalog = json.loads((Path(directory) / "aaas/catalog.json").read_text())
            self.assertEqual(catalog["applications"][0]["version_code"], 2)

    def test_catalog_preserves_unowned_collision_and_atomic_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"XDG_DATA_HOME": directory}
            appdir = Path(directory) / "applications"
            appdir.mkdir()
            desktop = appdir / "aaas-catalog-com.example.reader.desktop"
            desktop.write_text("user-owned")
            result = aaas_desktop.sync_package_catalog([{
                "package": "com.example.reader", "activity": "com.example.Reader",
                "label": "Reader", "version_code": 1, "version_name": "1",
                "enabled": True, "icon_png": b"",
            }], env=env)
            self.assertEqual(result["count"], 0)
            self.assertEqual(result["collisions"], ["com.example.reader"])
            self.assertEqual(desktop.read_text(), "user-owned")
            self.assertFalse(list(Path(directory).rglob("*.tmp")))

    def test_catalog_adopts_legacy_aaas_entry_during_portable_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"XDG_DATA_HOME": directory}
            appdir = Path(directory) / "applications"
            appdir.mkdir()
            desktop = appdir / "aaas-catalog-com.example.reader.desktop"
            desktop.write_text(
                "[Desktop Entry]\nType=Application\nName=Old Reader\n"
                "X-AaaS-Package=com.example.reader\n"
                'Exec="/usr/bin/python3" "~/old/aaas_desktop.py" "launch" '
                '"--package" "com.example.reader"\n', encoding="utf-8")
            result = aaas_desktop.sync_package_catalog([{
                "package": "com.example.reader", "activity": "com.example.Reader",
                "label": "Reader", "version_code": 2, "version_name": "2",
                "enabled": True, "icon_png": b"",
            }], env=env)
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["collisions"], [])
            self.assertIn("Name=Reader", desktop.read_text(encoding="utf-8"))

    def test_truncated_catalog_does_not_remove_entries_for_omitted_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"XDG_DATA_HOME": directory}
            apps = [{"package": package, "activity": package + ".Main",
                     "label": package, "version_code": 1, "version_name": "1",
                     "enabled": True, "icon_png": b""}
                    for package in ("com.example.one", "com.example.two")]
            aaas_desktop.sync_package_catalog(apps, env=env)
            preserved = Path(directory) / (
                "applications/aaas-catalog-com.example.two.desktop")
            self.assertTrue(preserved.exists())
            result = aaas_desktop.sync_package_catalog(apps[:1], env=env, truncated=True)
            self.assertTrue(preserved.exists())
            self.assertEqual(result["count"], 2)
            aaas_desktop.sync_package_catalog([], env=env, truncated=False)
            self.assertFalse(preserved.exists())

    def test_catalog_refresh_reuses_active_runtime(self):
        endpoint = Path("/tmp/session/ipc/aaas-control.sock")
        snapshot = {"request_id": "a" * 32, "truncated": False,
                    "applications": []}
        with patch.object(aaas_desktop, "_active_session",
                          return_value=({"state": "RUNNING"}, endpoint)), \
                patch.object(aaas_desktop, "launch_application") as launch, \
                patch.object(aaas_desktop, "request_package_catalog", return_value=snapshot), \
                patch.object(aaas_desktop, "sync_package_catalog",
                             return_value={"count": 0, "collisions": [], "catalog": "x"}), \
                patch.object(aaas_desktop, "_control_request") as request:
            result = aaas_desktop.refresh_package_catalog()
        launch.assert_not_called()
        request.assert_not_called()
        self.assertFalse(result["started_temporary_runtime"])

    def test_catalog_refresh_stops_its_temporary_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            endpoint = Path(directory) / "session/ipc/aaas-control.sock"
            endpoint.parent.mkdir(parents=True)
            (endpoint.parent.parent / "status").write_text("STOPPED")
            snapshot = {"request_id": "b" * 32, "truncated": False,
                        "applications": []}
            with patch.object(aaas_desktop, "_active_session", side_effect=(
                    (None, None), ({"state": "RUNNING"}, endpoint))), \
                    patch.object(aaas_desktop, "_persistent_service_unit_path",
                                 return_value=Path(directory) / "missing-service"), \
                    patch.object(aaas_desktop, "launch_application") as launch, \
                    patch.object(aaas_desktop, "request_package_catalog",
                                 return_value=snapshot), \
                    patch.object(aaas_desktop, "sync_package_catalog",
                                 return_value={"count": 0, "collisions": [], "catalog": "x"}), \
                    patch.object(aaas_desktop, "_control_request",
                                 return_value=(endpoint, {"ok": True})) as request:
                result = aaas_desktop.refresh_package_catalog()
            launch.assert_called_once_with("com.android.settings")
            request.assert_called_once_with({"op": "stop"}, timeout=3)
            self.assertTrue(result["started_temporary_runtime"])

    def test_cold_launch_closes_only_the_bootstrap_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            session.mkdir()
            (session / "status").write_text("RUNNING")
            installation_manifest = root / "installation.json"
            installation_manifest.write_text(json.dumps({
                "classification": "LOCAL_DEVELOPMENT_DIAGNOSTIC"}))
            with patch.object(aaas_desktop, "WORKSPACE_TMP", root), \
                    patch.object(aaas_desktop, "_persistent_service_unit_path",
                                 return_value=root / "missing-service"), \
                    patch.object(aaas_desktop, "cached_application",
                                 return_value={"package": "com.android.documentsui"}), \
                    patch.object(aaas_desktop.aaas_config, "resolve_config",
                                 return_value=SimpleNamespace(
                                     installation_manifest=installation_manifest)), \
                    patch.object(aaas_desktop, "_newest_session_after", return_value=session), \
                    patch.object(aaas_desktop.subprocess, "Popen") as popen, \
                    patch.object(aaas_desktop, "_control_request", side_effect=(
                        RuntimeError("no session"),
                        (root / "session/ipc/aaas-control.sock", {
                            "state": "RUNNING", "windows": [
                                {"package": "com.android.documentsui", "slot": 1,
                                 "state": "RUNNING"},
                                {"package": "com.android.settings", "slot": 2,
                                 "state": "RUNNING"}]}),
                        (root / "session/ipc/aaas-control.sock", {"ok": True}),
                        (root / "session/ipc/aaas-control.sock", {
                            "windows": [{"slot": 2, "state": "CLOSED",
                                         "presenter_pid": None}]})
                    )) as request:
                popen.return_value.poll.return_value = None
                result = aaas_desktop.launch_application("com.android.documentsui")
            self.assertEqual(result["mode"], "cold-start")
            self.assertTrue(result["bootstrap_window_closed"])
            command = popen.call_args.args[0]
            self.assertIn(str(aaas_desktop.ROOT / "scripts/aaas_cli.py"), command)
            self.assertEqual(command[2:4], ["dev", "start"])
            self.assertEqual(request.call_args_list[2].args[0], {
                "op": "stop_app", "slot": 2})


if __name__ == "__main__":
    unittest.main()
