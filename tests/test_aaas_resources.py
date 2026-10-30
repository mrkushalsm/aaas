"""Read-only, bounded host resource diagnostics."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/aaas_resources.py'
SPEC = importlib.util.spec_from_file_location('aaas_resources_tested', SCRIPT)
RESOURCES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESOURCES)


class ResourceSnapshotTests(unittest.TestCase):
    def test_meminfo_units_are_preserved(self):
        parsed = RESOURCES.parse_meminfo('MemAvailable: 12 kB\nHugePages: 3')
        self.assertEqual(parsed['MemAvailable'], {'value': 12, 'unit': 'kB'})
        self.assertEqual(parsed['HugePages'], {'value': 3, 'unit': None})

    def test_psi_fields_are_numeric_and_separated_by_stall_type(self):
        parsed = RESOURCES.parse_psi(
            'some avg10=0.12 avg60=0.20 avg300=0.30 total=44\n'
            'full avg10=0.01 avg60=0.02 avg300=0.03 total=5\n')
        self.assertEqual(parsed['some']['avg10'], 0.12)
        self.assertEqual(parsed['full']['total'], 5)

    def test_snapshot_is_read_only_and_contains_workspace_and_cgroup_context(self):
        before = Path('/proc/self/cgroup').read_text()
        with tempfile.TemporaryDirectory() as directory:
            snap = RESOURCES.snapshot(directory)
            target = Path(directory) / 'snapshot.json'
            RESOURCES.write_snapshot(target, workspace=directory)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            loaded = json.loads(target.read_text())
        self.assertEqual(Path('/proc/self/cgroup').read_text(), before)
        self.assertIn('MemAvailable', snap['host']['meminfo'])
        self.assertIn('memory', snap['host']['psi'])
        self.assertIn('launcher', snap['cgroups'])
        self.assertGreater(loaded['workspace']['available_bytes'], 0)

    def test_periodic_sample_limit_is_finite(self):
        self.assertEqual(RESOURCES.MAX_PERIODIC_SAMPLES, 3600)

    def test_selected_app_processes_are_classified_without_recording_cmdline(self):
        role = RESOURCES._process_role(
            'app_process64', b'app_process64 com.android.settings',
            ('com.android.settings', 'com.android.deskclock'))
        self.assertEqual(role, 'android_app:com.android.settings')

    def test_process_rss_rollup_parser(self):
        self.assertEqual(RESOURCES._pss_kib('Rss: 2048 kB\nPss: 1536 kB\n'), 1536)
        self.assertIsNone(RESOURCES._pss_kib({'unavailable': 13}))

    def test_cgroup_snapshot_accepts_absolute_session_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'cgroup'
            session = root / 'aaas' / 'session'
            session.mkdir(parents=True)
            (session / 'memory.current').write_text('4096\n')
            (session / 'memory.max').write_text('8192\n')
            (session / 'memory.events').write_text('low 2\nhigh 1\noom 0\n')
            with patch.object(RESOURCES, 'CGROUP_ROOT', root):
                result = RESOURCES._cgroup_snapshot(str(session))
        self.assertEqual(result['memory.current'], 4096)
        self.assertEqual(result['memory.max'], 8192)
        self.assertEqual(result['memory.events']['low'], 2)

    def test_cgroup_snapshot_resolves_proc_hierarchy_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'cgroup'
            session = root / 'user.slice' / 'aaas'
            session.mkdir(parents=True)
            (session / 'memory.current').write_text('12345\n')
            with patch.object(RESOURCES, 'CGROUP_ROOT', root):
                result = RESOURCES._cgroup_snapshot('/user.slice/aaas')
        self.assertEqual(result['memory.current'], 12345)

    def test_truncated_presenter_process_name_is_classified_before_app(self):
        self.assertEqual(
            RESOURCES._process_role('wayland-host-pr',
                                    b'wayland-host-presenter com.android.settings',
                                    ('com.android.settings',)),
            'wayland-host-presenter')


if __name__ == '__main__':
    unittest.main()
