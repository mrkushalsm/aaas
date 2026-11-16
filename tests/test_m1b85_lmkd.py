"""Tests for the M1B.8.5 LMKD build, overlay selection, and probes."""

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN_AAAS = load_script('run_aaas')
BUILD_LMKD = load_script('build_lmkd')
OOM_PROBE = load_script('probe_oom_score_adj')
CGROUP_PROBE = load_script('probe_cgroup_memory')
SELECTION_PROBE = load_script('probe_lmkd_selection')


class LmkdOverlayTests(unittest.TestCase):
    def test_default_uses_verified_diagnostic_overlay(self):
        self.assertEqual(
            RUN_AAAS.select_lmkd_overlay(False),
            ('m1b83_lmkd_vmstats_diagnostic',
             '9780759ba36e50d061064f05c77520809f3291edad6a43a1495e9d91f21d54bd'))

    def test_flag_uses_source_built_overlay(self):
        self.assertEqual(
            RUN_AAAS.select_lmkd_overlay(True),
            ('m1b85_lmkd_source_built',
             'a36135b6948342163186fe57acb9de0245fe00aeafcb9556c48a2e4c52f291ce'))

    def test_source_overlay_hash_matches_build_receipt(self):
        receipt = json.loads(
            (ROOT / 'tests/fixtures/m1b85/lmkd-build-receipt.json').read_text())
        self.assertEqual(receipt['sha256'], RUN_AAAS.LMKD_SOURCE_BUILT_SHA256)
        self.assertEqual(receipt['schema'], 1)
        self.assertEqual(receipt['source_verification'], 'passed')
        for name, entry in receipt['sources'].items():
            self.assertTrue(entry['commit_matches'], name)
            self.assertTrue(entry['patch_matches'], name)


class SourceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.repo / 'source.c').write_text('int value = 1;\n')
        self.git('add', 'source.c')
        self.git('commit', '-q', '-m', 'initial')
        self.commit = self.git('rev-parse', 'HEAD').strip()

    def tearDown(self):
        self.directory.cleanup()

    def git(self, *arguments):
        return subprocess.check_output(
            ['git', '-C', str(self.repo), *arguments], text=True)

    def manifest(self, commit=None):
        path = self.root / 'source_manifest.json'
        path.write_text(json.dumps({'sources': {
            'repo': {'path': str(self.repo), 'commit': commit or self.commit}}}))
        return path

    def diff_patch(self):
        diff = self.git('diff', 'HEAD')
        path = self.root / 'change.patch'
        path.write_text(diff)
        return path

    def test_clean_tree_passes(self):
        with patch.object(BUILD_LMKD, 'SOURCE_MANIFEST', self.manifest()), \
                patch.object(BUILD_LMKD, 'ALLOWED_PATCHES', {}):
            entries = BUILD_LMKD.verify_sources()
        self.assertTrue(entries['repo']['commit_matches'])
        self.assertTrue(entries['repo']['patch_matches'])

    def test_exact_patch_is_accepted(self):
        (self.repo / 'source.c').write_text('int value = 2;\n')
        patch_path = self.diff_patch()
        with patch.object(BUILD_LMKD, 'SOURCE_MANIFEST', self.manifest()), \
                patch.object(BUILD_LMKD, 'ALLOWED_PATCHES', {'repo': [patch_path]}):
            entries = BUILD_LMKD.verify_sources()
        self.assertTrue(entries['repo']['patch_matches'])

    def test_unexpected_change_is_rejected(self):
        (self.repo / 'source.c').write_text('int value = 2;\n')
        patch_path = self.diff_patch()
        (self.repo / 'source.c').write_text('int value = 3;\n')
        with patch.object(BUILD_LMKD, 'SOURCE_MANIFEST', self.manifest()), \
                patch.object(BUILD_LMKD, 'ALLOWED_PATCHES', {'repo': [patch_path]}):
            with self.assertRaisesRegex(RuntimeError, 'does not match pinned patches'):
                BUILD_LMKD.verify_sources()

    def test_commit_mismatch_is_rejected(self):
        with patch.object(BUILD_LMKD, 'SOURCE_MANIFEST', self.manifest('0' * 40)), \
                patch.object(BUILD_LMKD, 'ALLOWED_PATCHES', {}):
            with self.assertRaisesRegex(RuntimeError, 'provenance verification failed'):
                BUILD_LMKD.verify_sources()


class OomProbeTests(unittest.TestCase):
    def test_capability_names_include_sys_resource(self):
        names = OOM_PROBE.capability_names((1 << 24) | (1 << 0))
        self.assertIn('CAP24', names)
        self.assertIn('CAP0', names)

    def test_android_landmarks_are_covered(self):
        values = {name: value for name, value in OOM_PROBE.CASES}
        self.assertEqual(values['foreground'], 0)
        self.assertEqual(values['cached'], 900)
        self.assertEqual(values['native'], -1000)
        self.assertIn('visible', values)
        self.assertIn('system', values)


class CgroupProbeTests(unittest.TestCase):
    def test_events_pressure_and_snapshot_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            group = Path(directory)
            (group / 'memory.events').write_text(
                'low 0\nhigh 12\nmax 0\noom 0\noom_kill 1\n')
            (group / 'memory.pressure').write_text(
                'some avg10=1.25 avg60=0.50 total=100\n'
                'full avg10=0.00 avg60=0.00 total=0\n')
            (group / 'memory.current').write_text('4096\n')
            (group / 'memory.peak').write_text('8192\n')
            snapshot = CGROUP_PROBE.snapshot(group)
        self.assertEqual(snapshot['memory_current'], '4096')
        self.assertEqual(snapshot['memory_peak'], '8192')
        self.assertEqual(snapshot['memory_events']['oom_kill'], 1)
        self.assertEqual(snapshot['memory_pressure']['some']['avg10'], '1.25')
        self.assertEqual(CGROUP_PROBE.MEMBERS[0], 'memory.min')


class SelectionProbeTests(unittest.TestCase):
    def test_kill_notification_protocol(self):
        self.assertEqual(SELECTION_PROBE.LMK_ASYNC_EVENT_KILL, 0)
        self.assertEqual(SELECTION_PROBE.LMK_PROCKILL, 6)
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            SELECTION_PROBE.send_int_packet(
                left, [SELECTION_PROBE.LMK_PROCKILL, 42, 1000, 512])
            self.assertEqual(SELECTION_PROBE.recv_int_packet(right, 1),
                             [SELECTION_PROBE.LMK_PROCKILL, 42, 1000, 512])
        finally:
            left.close()
            right.close()

    def test_pressure_and_event_parsing(self):
        pressure = SELECTION_PROBE.parse_pressure_text(
            'some avg10=2.50 avg60=1.00 total=123\n'
            'full avg10=0.50 avg60=0.25 total=45\n')
        self.assertEqual(pressure['some']['avg10'], 2.5)
        self.assertEqual(pressure['full']['total'], 45)
        events = SELECTION_PROBE.parse_events_text(
            'low 0\nhigh 3\nmax 0\noom 0\noom_kill 0\n')
        self.assertEqual(events['high'], 3)
        self.assertEqual(events['oom_kill'], 0)


if __name__ == '__main__':
    unittest.main()
