import fcntl
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_cli
import aaas_config
import android_workspace


class AaasCliTests(unittest.TestCase):
    def config(self, root):
        return aaas_config.resolve_config(repository=Path(root), env={
            'HOME': str(Path(root) / 'home'),
            'XDG_CONFIG_HOME': str(Path(root) / 'cfg'),
            'XDG_DATA_HOME': str(Path(root) / 'data'),
            'XDG_CACHE_HOME': str(Path(root) / 'cache'),
            'XDG_STATE_HOME': str(Path(root) / 'state'),
            'XDG_RUNTIME_DIR': str(Path(root) / 'run'),
        })

    def test_public_command_shapes_accept_json_after_command(self):
        parser = aaas_cli._parser()
        self.assertEqual(parser.parse_args(['help', 'setup']).topic, 'setup')
        self.assertEqual(parser.parse_args(['doctor', '--json']).command, 'doctor')
        self.assertEqual(parser.parse_args(['apps', '--json', 'list']).apps_command, 'list')
        self.assertEqual(parser.parse_args(['images', '--json', 'list']).images_command, 'list')
        self.assertEqual(parser.parse_args(['verify', '--json']).command, 'verify')

    def test_status_ignores_stale_running_sentinel_when_lock_is_free(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            session = config.workspace / 'tmp/m1b84_session_old'
            session.mkdir(parents=True)
            (session / 'status').write_text('RUNNING\n')
            (session.parent / '.aaas_session.lock').touch()
            self.assertEqual(aaas_cli._status(config)['runtime']['state'], 'STOPPED')

    def test_status_requires_held_session_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            session = config.workspace / 'tmp/m1b84_session_live'
            session.mkdir(parents=True)
            (session / 'status').write_text('RUNNING\n')
            lock = session.parent / '.aaas_session.lock'
            with lock.open('w+') as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(aaas_cli._status(config)['runtime']['state'], 'RUNNING')

    def test_missing_artifacts_are_never_reported_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = aaas_cli._verify(self.config(temporary))
        self.assertFalse(result['ready'])
        self.assertEqual(result['checks']['image']['compatibility'], 'MISSING')

    def test_experimental_profile_cannot_pass_production_verify(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            config.workspace.mkdir(parents=True)
            config.rootfs.mkdir(parents=True)
            verified_image = {
                'compatibility': 'MATCH', 'provenance': 'VERIFIED',
                'trust_classification': 'RECONSTRUCTED_EXPERIMENTAL',
                'provisionable': True, 'security': {'enforcement': 'VERIFIED'},
            }
            with mock.patch.object(android_workspace, 'check', return_value={'state': 'PASS'}), \
                    mock.patch.object(aaas_cli.aaas_profiles, 'inspect_rootfs',
                                      return_value=verified_image):
                result = aaas_cli._verify(config)
        self.assertFalse(result['ready'])


if __name__ == '__main__':
    unittest.main()
