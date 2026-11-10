import fcntl
import os
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
        self.assertTrue(parser.parse_args(['apps', 'list', '--refresh']).refresh)
        self.assertEqual(parser.parse_args(['images', '--json', 'list']).images_command, 'list')
        build = parser.parse_args(['images', 'build', 'android16-ranchu-x86_64',
                                   '--dry-run', '--image', '/tmp/image.zip'])
        self.assertEqual(build.images_command, 'build')
        self.assertTrue(build.dry_run)
        self.assertEqual(build.image, Path('/tmp/image.zip'))
        self.assertEqual(parser.parse_args(['verify', '--json']).command, 'verify')
        self.assertEqual(parser.parse_args(['runtime', 'install-service', '--json']).runtime_command,
                         'install-service')

    def test_runtime_readiness_requires_zero_live_window_resources(self):
        self.assertTrue(aaas_cli._runtime_windows_are_idle([]))
        self.assertTrue(aaas_cli._runtime_windows_are_idle([
            {'state': 'CLOSED', 'presenter_pid': None, 'display_id': None},
        ]))
        self.assertFalse(aaas_cli._runtime_windows_are_idle([
            {'state': 'CLOSED', 'presenter_pid': 123, 'display_id': 7},
        ]))
        self.assertFalse(aaas_cli._runtime_windows_are_idle([
            {'state': 'RUNNING', 'presenter_pid': 123, 'display_id': 7},
        ]))

    def test_runtime_start_waits_through_systemd_auto_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            unit = Path(temporary) / 'aaas-runtime.service'
            is_active = [mock.Mock(returncode=1), mock.Mock(returncode=0)]

            def systemctl(*args, check=True):
                if args[0] == 'is-active':
                    return is_active.pop(0)
                if args[0] == 'show':
                    return mock.Mock(returncode=0, stdout=(
                        'ActiveState=activating\nSubState=auto-restart\nNRestarts=1\n'))
                return mock.Mock(returncode=0, stdout='')

            app_list = [mock.Mock(returncode=1, stdout=''),
                        mock.Mock(returncode=0,
                                   stdout='{"state":"RUNNING","windows":[]}\n')]
            with mock.patch.object(aaas_cli, '_runtime_unit_path', return_value=unit), \
                    mock.patch.object(aaas_cli, '_install_runtime_service'), \
                    mock.patch.object(aaas_cli, '_runtime_import_desktop_environment'), \
                    mock.patch.object(aaas_cli, '_runtime_systemctl', side_effect=systemctl), \
                    mock.patch.object(aaas_cli, '_status', return_value={
                        'runtime': {'state': 'RUNNING'}}), \
                    mock.patch.object(aaas_cli.subprocess, 'run', side_effect=app_list), \
                    mock.patch.object(aaas_cli.time, 'sleep'):
                result = aaas_cli._runtime_start(config)
        self.assertEqual(result['state'], 'RUNNING')
        self.assertEqual(result['windows'], [])

    def test_runtime_service_gracefully_stops_its_android_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            with mock.patch.object(aaas_cli, '_runtime_systemctl'), \
                    mock.patch.object(aaas_cli, '_runtime_unit_path',
                                      return_value=config.config_file.parent.parent /
                                      'systemd/user/aaas-runtime.service'):
                unit = aaas_cli._install_runtime_service(config)
            contents = unit.read_text()
        self.assertIn('KillMode=mixed', contents)
        self.assertNotIn('KillMode=control-group', contents)
        self.assertIn('StartLimitIntervalSec=60', contents)
        self.assertIn('StartLimitBurst=3', contents)
        self.assertIn('RestartSec=10s', contents)

    def test_runtime_service_enables_verified_workspace_native_bridge_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            bundle = config.workspace / 'tmp/m3_native_bridge/digitalis'
            bundle.mkdir(parents=True)
            (bundle / 'SHA256SUMS').write_text('verified bundle marker')
            with mock.patch.object(aaas_cli, '_runtime_systemctl'), \
                    mock.patch.object(aaas_cli, '_runtime_unit_path',
                                      return_value=config.config_file.parent.parent /
                                      'systemd/user/aaas-runtime.service'):
                unit = aaas_cli._install_runtime_service(config)
            contents = unit.read_text()
        self.assertIn(f'AAAS_NATIVE_BRIDGE_BUNDLE="{bundle}"', contents)

    def test_runtime_service_preserves_helper_signer_across_bundle_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            old_key = Path(temporary) / 'previous-state/aaas/signing/storage-probe.keystore'
            old_key.parent.mkdir(parents=True)
            old_key.write_bytes(b'existing per-install identity')
            unit_path = (config.config_file.parent.parent /
                         'systemd/user/aaas-runtime.service')
            unit_path.parent.mkdir(parents=True)
            unit_path.write_text(
                'Description=AaaS persistent Android runtime\n'
                f'Environment=AAAS_WORKSPACE="{config.workspace}"\n'
                f'Environment=AAAS_ROOTFS="{config.rootfs}"\n'
                f'Environment=AAAS_HELPER_KEYSTORE="{old_key}"\n')
            with mock.patch.object(aaas_cli, '_runtime_systemctl'), \
                    mock.patch.object(aaas_cli, '_runtime_unit_path', return_value=unit_path), \
                    mock.patch.object(aaas_cli.aaas_dev, 'ensure_signing_key',
                                      return_value=old_key) as ensure:
                unit = aaas_cli._install_runtime_service(config)
            contents = unit.read_text()
        self.assertEqual(ensure.call_args.args[0], old_key.parent.parent)
        self.assertIn(f'AAAS_HELPER_KEYSTORE="{old_key}"', contents)
        self.assertIn(f'XDG_CACHE_HOME="{Path(temporary) / "cache"}"', contents)
        self.assertIn(f'XDG_STATE_HOME="{Path(temporary) / "state"}"', contents)

    def test_runtime_service_name_can_be_isolated_for_profile_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            with mock.patch.dict(os.environ,
                                 {'AAAS_RUNTIME_SERVICE': 'aaas-isolated-check.service'}), \
                    mock.patch('subprocess.run') as run:
                run.return_value = mock.Mock(returncode=0, stdout='/tmp/user-config\n')
                path = aaas_cli._runtime_unit_path(config)
            self.assertEqual(path, Path('/tmp/user-config/systemd/user/aaas-isolated-check.service'))

    def test_release_lifecycle_refuses_foreign_service_before_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            foreign_unit = Path(temporary) / 'aaas-runtime.service'
            foreign_unit.write_text(
                'Description=AaaS persistent Android runtime\n'
                'Environment=AAAS_WORKSPACE="/different/workspace"\n'
                'Environment=AAAS_ROOTFS="/different/rootfs"\n')
            with mock.patch.object(aaas_cli, '_runtime_unit_path',
                                   return_value=foreign_unit), \
                    mock.patch.object(aaas_cli, '_runtime_systemctl') as systemctl:
                with self.assertRaisesRegex(aaas_cli.CliError, 'unowned service'):
                    aaas_cli._require_owned_runtime_unit(config)
                with self.assertRaisesRegex(aaas_cli.CliError, 'unowned service'):
                    aaas_cli._install_runtime_service(config)
            systemctl.assert_not_called()
            self.assertIn('/different/workspace', foreign_unit.read_text())

    def test_uninstall_discards_backup_unit_owned_by_removed_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            unit = Path(temporary) / 'aaas-runtime.service'
            backup = unit.with_name(unit.name + '.aaas-backup')
            backup.write_text(
                '[Unit]\nDescription=AaaS persistent Android runtime\n'
                '[Service]\n'
                f'Environment=AAAS_WORKSPACE="{config.workspace}"\n'
                f'Environment=AAAS_ROOTFS="{config.rootfs}"\n')

            aaas_cli._restore_previous_unit_after_uninstall(unit, backup, config)

        self.assertFalse(unit.exists())
        self.assertFalse(backup.exists())

    def test_uninstall_restores_backup_unit_for_another_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            unit = Path(temporary) / 'aaas-runtime.service'
            backup = unit.with_name(unit.name + '.aaas-backup')
            backup.write_text(
                '[Unit]\nDescription=AaaS persistent Android runtime\n'
                '[Service]\nEnvironment=AAAS_WORKSPACE="/other/workspace"\n'
                'Environment=AAAS_ROOTFS="/other/rootfs"\n')

            aaas_cli._restore_previous_unit_after_uninstall(unit, backup, config)

            self.assertTrue(unit.is_file())
            self.assertEqual(aaas_cli._unit_environment(unit, 'AAAS_WORKSPACE'),
                             '/other/workspace')
            self.assertFalse(backup.exists())

    def test_release_lifecycle_commands_are_available(self):
        parser = aaas_cli._parser()
        self.assertEqual(parser.parse_args(['update', '/tmp/release']).command, 'update')
        self.assertEqual(parser.parse_args(['rollback']).command, 'rollback')
        self.assertFalse(parser.parse_args(['uninstall']).remove_user_data)
        self.assertTrue(parser.parse_args(['uninstall', '--remove-user-data']).remove_user_data)

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
        self.assertNotIn('AAAS_PRESENTER_IMPLICIT_SYNC',
                         run.call_args.kwargs['env_extra'])

    def test_developer_start_supports_repeated_independent_app_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            report = {'development_launch': 'PERMITTED', 'checks': {
                'host': {'ip': '/usr/bin/ip'}}}
            with mock.patch.object(aaas_cli.aaas_config, 'resolve_config',
                                   return_value=config), \
                    mock.patch.object(aaas_cli.aaas_dev, 'verify', return_value=report), \
                    mock.patch.object(aaas_cli.aaas_dev, 'runtime_root',
                                      return_value=Path(temporary) / 'runtime'), \
                    mock.patch.object(aaas_cli, '_run_script', return_value=0) as run:
                self.assertEqual(aaas_cli.main([
                    'dev', 'start', '--app', 'com.android.settings',
                    '--app', 'com.android.contacts',
                    '--app', 'com.apotris.android',
                    '--app', 'com.android.calendar',
                    '--idle-timeout-seconds', '600']), 0)
            args = run.call_args.args
            self.assertEqual(args[0], 'run_aaas.py')
            self.assertIn('--experimental-virtual-display', args)
            self.assertEqual(args[args.index('--app'):args.index('--app') + 2],
                             ('--app', 'com.android.settings'))
            self.assertEqual(args[args.index('--app2'):args.index('--app2') + 2],
                             ('--app2', 'com.android.contacts'))
            self.assertEqual(args.count('--app-extra'), 2)
            self.assertIn(('--app-extra', 'com.apotris.android'),
                          tuple(zip(args, args[1:])))
            self.assertIn(('--app-extra', 'com.android.calendar'),
                          tuple(zip(args, args[1:])))
            self.assertEqual(args[args.index('--idle-timeout-seconds'):
                                  args.index('--idle-timeout-seconds') + 2],
                             ('--idle-timeout-seconds', '600'))

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
            args = run.call_args_list[0]
            self.assertEqual(args.args[:3],
                             ('run_aaas.py', '--headless-storage', '--install-apk'))
            self.assertIn('AAAS_HEADLESS_STORAGE', args.kwargs['env_extra'])
            self.assertEqual(run.call_args_list[1].args[:3],
                             ('aaas_desktop.py', 'catalog', 'refresh'))

    def test_apps_install_uses_the_running_package_manager(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(temporary)
            apk = Path(temporary) / 'trusted-test.apk'
            apk.write_bytes(b'fixture')
            unit = Path(temporary) / 'aaas-runtime.service'
            unit.write_text('installed')
            with mock.patch.object(aaas_cli.aaas_config, 'resolve_config',
                                   return_value=config), \
                    mock.patch.object(aaas_cli, '_verify', return_value={'ready': True}), \
                    mock.patch.object(aaas_cli, '_runtime_unit_path', return_value=unit), \
                    mock.patch.object(aaas_cli, '_status', return_value={
                        'runtime': {'state': 'RUNNING'}}), \
                    mock.patch.object(aaas_cli, '_run_script', return_value=0) as run:
                self.assertEqual(aaas_cli.main(['apps', 'install', str(apk)]), 0)
            self.assertEqual(run.call_args_list[0].args[:2],
                             ('aaasctl.py', 'install-apk'))
            self.assertEqual(run.call_args_list[1].args[:3],
                             ('aaas_desktop.py', 'catalog', 'refresh'))

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
