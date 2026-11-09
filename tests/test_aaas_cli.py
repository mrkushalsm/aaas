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
        build = parser.parse_args(['images', 'build', 'android16-ranchu-x86_64',
                                   '--dry-run', '--image', '/tmp/image.zip'])
        self.assertEqual(build.images_command, 'build')
        self.assertTrue(build.dry_run)
        self.assertEqual(build.image, Path('/tmp/image.zip'))
        self.assertEqual(parser.parse_args(['verify', '--json']).command, 'verify')

    def test_images_build_dispatches_to_source_assembler(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            with mock.patch.object(aaas_cli.aaas_config, 'resolve_config',
                                   return_value=config), \
                    mock.patch.object(aaas_cli, '_run_script', return_value=0) as run:
                result = aaas_cli.main(['images', 'build', 'android16-ranchu-x86_64',
                                        '--image', '/tmp/image.zip', '--dry-run'])
        self.assertEqual(result, 0)
        args = run.call_args
        self.assertEqual(args.args[:2], ('assemble_android_rootfs.py', '--workspace'))
        self.assertIn('--profile', args.args)
        self.assertIn('--dry-run', args.args)

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

    def test_developer_start_uses_installed_runtime_payload_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            payload = Path(temporary) / 'installation/runtime'
            host = {'ip': '/usr/bin/ip'}
            report = {'development_launch': 'PERMITTED', 'checks': {'host': host}}
            with mock.patch.object(aaas_cli.aaas_config, 'resolve_config',
                                   return_value=config), \
                    mock.patch.object(aaas_cli.aaas_dev, 'verify', return_value=report), \
                    mock.patch.object(aaas_cli.aaas_dev, 'runtime_root',
                                      return_value=payload), \
                    mock.patch.object(aaas_cli, '_run_script', return_value=0) as run:
                result = aaas_cli.main(['dev', 'start'])
        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.kwargs['env_extra']['AAAS_RUNTIME_ROOT'],
                         str(payload))

    def test_developer_install_uses_headless_diagnostic_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            apk = Path(temporary) / 'trusted-test.apk'
            apk.write_bytes(b'fixture')
            report = {'headless_storage_launch': 'PERMITTED'}
            with mock.patch.object(aaas_cli.aaas_config, 'resolve_config',
                                   return_value=config), \
                    mock.patch.object(aaas_cli.aaas_dev, 'verify_storage',
                                      return_value=report), \
                    mock.patch.object(aaas_cli.aaas_dev, 'runtime_root',
                                      return_value=Path(temporary) / 'runtime'), \
                    mock.patch.object(aaas_cli, '_status', return_value={
                        'runtime': {'state': 'STOPPED'}}), \
                    mock.patch.object(aaas_cli, '_run_script', return_value=0) as run:
                self.assertEqual(aaas_cli.main(['dev', 'install', str(apk)]), 0)
            args = run.call_args
            self.assertEqual(args.args[:3],
                             ('run_aaas.py', '--headless-storage', '--install-apk'))
            self.assertIn('AAAS_HEADLESS_STORAGE', args.kwargs['env_extra'])

    def test_logs_ignore_matching_files_and_choose_latest_session_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            root = config.workspace / 'tmp'
            root.mkdir(parents=True)
            (root / 'm1b84_session_stale.log').write_text('not a session')
            session = root / 'm1b84_session_live'
            session.mkdir()
            (session / 'android.log').write_text('boot evidence\n')
            with mock.patch.object(aaas_cli.aaas_config, 'resolve_config',
                                   return_value=config), \
                    mock.patch('builtins.print') as output:
                self.assertEqual(aaas_cli.main(['dev', 'logs', '--lines', '10']), 0)
            self.assertIn('boot evidence\n', output.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
