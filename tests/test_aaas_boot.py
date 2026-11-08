import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_boot
import aaas_cli


class AaasBootPreflightTests(unittest.TestCase):
    def candidate(self, workspace):
        candidate = workspace / 'rootfs-candidates/profile/build'
        (candidate / 'rootfs').mkdir(parents=True)
        (candidate / 'manifest.json').write_text(json.dumps({
            'profile': 'android16-ranchu-x86_64',
            'build_id': 'BE2A.250530.026.D1',
            'status': 'ASSEMBLED_INCOMPLETE',
            'trust_classification': 'RECONSTRUCTED_EXPERIMENTAL',
            'runtime_ready': False,
            'candidate_rootfs_relative': 'rootfs',
            'missing_components': ['APEX activation unresolved'],
        }))
        return candidate

    def test_candidate_preflight_fails_closed_without_selinux_and_does_not_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            candidate = self.candidate(workspace)
            with mock.patch.object(aaas_boot.android_workspace, 'check', return_value={
                    'health': {'state': 'HEALTHY_FOR_CONTROLLED_TESTING'},
                    'mount': {'filesystem': 'ext4', 'uuid': 'test'},
            }), mock.patch.object(aaas_boot.aaas_profiles, 'inspect_rootfs', return_value={
                    'assembly_record_validation': 'PASS', 'compatibility': 'MATCH',
                    'provisionable': False, 'provenance': 'ASSEMBLY_RECORD_VALID',
                    'assembly_status': 'ASSEMBLED_INCOMPLETE',
                    'security': {'status': 'UNVERIFIED'},
                    'provisioning_blockers': ['SELinux not verified'],
            }):
                report = aaas_boot.inspect_candidate(
                    candidate, workspace, lsm_path=workspace / 'lsm',
                    selinux_load=workspace / 'load')
        self.assertEqual(report['outcome'], 'SECURITY_BLOCKED')
        self.assertEqual(report['failure_class'], 'SECURITY_GATE')
        self.assertFalse(report['launch_permitted'])
        self.assertIsNone(report['session_id'])
        self.assertEqual(report['side_effects'], [])
        self.assertEqual(report['checks'][-1]['state'], 'NOT_ATTEMPTED')

    def test_rejects_candidate_outside_configured_workspace(self):
        with tempfile.TemporaryDirectory() as workspace_tmp, \
                tempfile.TemporaryDirectory() as outside_tmp:
            outside = self.candidate(Path(outside_tmp))
            with self.assertRaisesRegex(aaas_boot.BootPreflightError,
                                        'inside the configured workspace'):
                aaas_boot.inspect_candidate(outside, Path(workspace_tmp))

    def test_rejects_legacy_rootfs_without_reconstructed_candidate_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            candidate = self.candidate(workspace)
            manifest = json.loads((candidate / 'manifest.json').read_text())
            manifest['status'] = 'READY'
            (candidate / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(aaas_boot.BootPreflightError,
                                        'not an incomplete reconstructed'):
                aaas_boot.inspect_candidate(candidate, workspace)

    def test_cli_exposes_read_only_boot_preflight(self):
        args = aaas_cli._parser().parse_args([
            'debug', 'boot', '--candidate', '/tmp/candidate', '--json'])
        self.assertEqual(args.debug_command, 'boot')
        self.assertTrue(args.json_local)
        self.assertEqual(args.candidate, Path('/tmp/candidate'))


if __name__ == '__main__':
    unittest.main()
