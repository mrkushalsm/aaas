import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_bundle
import android_workspace


def install_fixture(**kwargs):
    def identity(target):
        return {'target': str(target), 'source': '/dev/test', 'filesystem': 'ext4',
                'uuid': 'test-uuid', 'mount_id': '1', 'options': 'rw'}
    with patch.object(android_workspace, 'mount_identity', side_effect=identity), \
            patch.object(android_workspace, '_require_workspace_health',
                         return_value={'state': 'HEALTHY_FOR_CONTROLLED_TESTING'}), \
            patch.object(android_workspace.os, 'statvfs',
                         return_value=SimpleNamespace(f_bavail=(64 << 30) // 4096,
                                                      f_bfree=(64 << 30) // 4096,
                                                      f_blocks=(80 << 30) // 4096,
                                                      f_frsize=4096)):
        return aaas_bundle.install_bundle(**kwargs)


class BundleTests(unittest.TestCase):
    def test_bundle_capacity_uses_user_available_blocks_not_privileged_free_blocks(self):
        stat = SimpleNamespace(f_bavail=7, f_bfree=99, f_blocks=100,
                               f_frsize=4096, f_bsize=4096)
        with patch.object(aaas_bundle.os, 'statvfs', return_value=stat):
            self.assertEqual(aaas_bundle._filesystem_available_bytes(Path('/tmp')),
                             7 * 4096)

    def fixture(self, root: Path):
        repo = root / 'repo'
        workspace = root / 'workspace'
        rootfs = workspace / 'rootfs_m1b1'
        (repo / 'scripts').mkdir(parents=True)
        (repo / 'scripts/aaas_cli.py').write_text('print("bundle cli")\n')
        (repo / 'scripts/aaas_portable_installer.py').write_text(
            'import argparse\n'
            'def main():\n'
            '    p=argparse.ArgumentParser()\n'
            '    p.add_argument("--workspace")\n'
            '    p.parse_args()\n')
        (repo / 'scripts/aaas_bundle.py').write_text('')
        (repo / 'scripts/aaas_config.py').write_text('')
        (repo / 'manifests').mkdir()
        (repo / 'manifests/android-profiles.json').write_text('{}\n')
        (repo / 'experiments/m1a').mkdir(parents=True)
        (repo / 'experiments/m1a/host.bin').write_bytes(b'host executable')
        helper_source = repo / 'experiments/perf/input_latency_probe/build_probe.py'
        helper_source.parent.mkdir(parents=True)
        helper_source.write_text('def binary_manifest(*args, **kwargs): return b"manifest"\n')
        for name in ('system', 'system/bin', 'system/lib64', 'system/etc/init',
                     'vendor', 'vendor/lib64', 'product',
                     'system_ext', 'apex', 'data', 'cache', 'tmp'):
            (rootfs / name).mkdir(parents=True, exist_ok=True)
        (rootfs / 'system/bin/init').write_bytes(b'android init')
        (rootfs / 'system/bin/init').chmod(0o755)
        (rootfs / 'vendor/build.prop').write_text('ro.test=true\n')
        (rootfs / 'system/lib64/libselinux_shim.so').write_bytes(b'known legacy shim')
        (rootfs / 'vendor/lib64/libselinux_shim.so').write_bytes(b'known legacy shim')
        (rootfs / 'system/etc/init/servicemanager.rc').write_text(
            'setenv LD_PRELOAD /system/lib64/libselinux_shim.so\n')
        (rootfs / 'data/private.db').write_bytes(b'private userdata')
        (rootfs / 'tmp/old.log').write_text('not bundle data')
        (rootfs / 'init').symlink_to('system/bin/init')
        (workspace / 'tmp').mkdir(exist_ok=True)
        (workspace / 'tmp/m1e_composer_two_output').write_bytes(b'composer-binary')
        (workspace / 'tmp/m1e_composer_two_output.json').write_text(
            '{"endpoint_mode":"on-demand"}\n')
        return repo, workspace, rootfs

    def test_create_manifest_excludes_user_state_and_verifies_relocated_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo, workspace, _ = self.fixture(base)
            output = base / 'bundle'
            result = aaas_bundle.create_bundle(repo=repo, rootfs=workspace / 'rootfs_m1b1',
                                               output=output, workspace=workspace)
            self.assertEqual(result['integrity'], 'PASS')
            self.assertEqual(result['runtime_security'], 'NOT_APPROVED')
            self.assertTrue((output / 'install').stat().st_mode & 0o111)
            self.assertTrue((output / 'install.py').stat().st_mode & 0o111)
            bundle_manifest = json.loads((output / 'manifest.json').read_text())
            installer_provenance = {r['path']: r for r in bundle_manifest['provenance']['executable_library_provenance']}
            for installer_path in ('install', 'install.py'):
                self.assertEqual(installer_provenance[installer_path]['role'],
                                 'AaaS portable bundle installer')
                self.assertIn('scripts/aaas_bundle.py',
                              installer_provenance[installer_path]['source_identity'])
            installer_help = subprocess.run([sys.executable, str(output / 'install.py'),
                                             '--help'], capture_output=True, text=True)
            self.assertEqual(installer_help.returncode, 0, installer_help.stderr)
            self.assertIn('--workspace', installer_help.stdout)
            self.assertFalse((output / 'rootfs/data/private.db').exists())
            self.assertFalse((output / 'rootfs/tmp/old.log').exists())
            self.assertTrue((output / 'workspace-artifacts/tmp/m1e_composer_two_output.json').is_file())
            self.assertTrue((output / 'rootfs/init').is_symlink())
            self.assertEqual(
                (output / 'runtime/experiments/perf/input_latency_probe/build_probe.py').read_bytes(),
                (repo / 'experiments/perf/input_latency_probe/build_probe.py').read_bytes())
            moved = base / 'moved' / 'bundle'
            moved.parent.mkdir()
            output.rename(moved)
            self.assertEqual(aaas_bundle.verify_bundle(moved)['integrity'], 'PASS')

    def test_manifest_detects_tampering_and_unmanifested_files(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo, workspace, _ = self.fixture(base)
            output = base / 'bundle'
            aaas_bundle.create_bundle(repo=repo, rootfs=workspace / 'rootfs_m1b1',
                                      output=output, workspace=workspace)
            artifact = output / 'rootfs/system/bin/init'
            artifact.write_bytes(b'tampered')
            with self.assertRaisesRegex(aaas_bundle.BundleError, 'size mismatch|hash mismatch'):
                aaas_bundle.verify_bundle(output)
            artifact.write_bytes(b'android init')
            extra = output / 'untracked'
            extra.write_text('extra')
            with self.assertRaisesRegex(aaas_bundle.BundleError, 'unmanifested'):
                aaas_bundle.verify_bundle(output)

    def test_two_installations_are_independent_and_security_stays_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo, source_workspace, _ = self.fixture(base)
            bundle = base / 'bundle'
            aaas_bundle.create_bundle(repo=repo, rootfs=source_workspace / 'rootfs_m1b1',
                                      output=bundle, workspace=source_workspace)
            results = []
            for suffix in ('one', 'two'):
                with patch.object(aaas_bundle.shutil, 'disk_usage',
                                  return_value=SimpleNamespace(free=64 << 30)):
                    result = install_fixture(
                        bundle=bundle, workspace=base / f'workspace-{suffix}',
                        install_root=base / f'install-{suffix}',
                        config_home=base / f'config-{suffix}', data_home=base / f'data-{suffix}')
                results.append(result)
                self.assertEqual(result['installation_integrity'], 'PASS')
                expected_closure = aaas_bundle.inspect_bundle(bundle)['runtime_closure']['status']
                self.assertEqual(result['runtime_closure'], expected_closure)
                self.assertEqual(result['general_runtime_start'], 'BLOCKED')
                self.assertTrue((base / f'install-{suffix}/bin/aaas').is_file())
                self.assertTrue((base / f'install-{suffix}/rootfs/data').is_dir())
                self.assertTrue((base / f'install-{suffix}/rootfs/linkerconfig').is_dir())
                self.assertTrue((base / f'install-{suffix}/rootfs/debug_ramdisk').is_dir())
                self.assertFalse((base / f'install-{suffix}/rootfs/data/private.db').exists())
                self.assertTrue((base / f'workspace-{suffix}/.aaas-workspace.json').is_file())
                self.assertTrue((base / f'workspace-{suffix}/android-userdata/.aaas-userdata.json').is_file())
                self.assertEqual(aaas_bundle.verify_installation(
                    base / f'install-{suffix}')['integrity'], 'PASS')
                self.assertIn(str(base / f'install-{suffix}/rootfs'),
                              (base / f'config-{suffix}/aaas/config.toml').read_text())
            self.assertNotEqual(results[0]['installation'], results[1]['installation'])
            installed = json.loads((base / 'data-one/aaas/installation.json').read_text())
            self.assertNotIn(str(source_workspace), installed['paths'].values())
            self.assertEqual(installed['workspace_enrollment'], 'PASS')
            self.assertEqual(installed['userdata'], 'fresh installation-local backing initialized')
            self.assertIn('linkerconfig', installed['generated_rootfs_mountpoints'])

    def test_update_and_rollback_preserve_workspace_and_userdata(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo, source_workspace, _ = self.fixture(base)
            first_bundle = base / 'bundle-first'
            aaas_bundle.create_bundle(repo=repo, rootfs=source_workspace / 'rootfs_m1b1',
                                      output=first_bundle, workspace=source_workspace)
            install = base / 'install'
            workspace = base / 'runtime-workspace'
            with patch.object(aaas_bundle.shutil, 'disk_usage',
                              return_value=SimpleNamespace(free=64 << 30)):
                install_fixture(bundle=first_bundle, workspace=workspace,
                                install_root=install, config_home=base / 'config',
                                data_home=base / 'data')
            userdata = workspace / 'android-userdata/data/keep.txt'
            userdata.write_text('persistent app data')
            (repo / 'scripts/aaas_cli.py').write_text('print("updated CLI")\n')
            second_bundle = base / 'bundle-second'
            aaas_bundle.create_bundle(repo=repo, rootfs=source_workspace / 'rootfs_m1b1',
                                      output=second_bundle, workspace=source_workspace)
            stage = aaas_bundle.stage_installation_update(bundle=second_bundle,
                                                           installation=install)
            previous = aaas_bundle.activate_staged_update(stage=stage,
                                                            installation=install)
            self.assertEqual(aaas_bundle.verify_installation(install)['integrity'], 'PASS')
            self.assertEqual((install / 'runtime/scripts/aaas_cli.py').read_text(),
                             'print("updated CLI")\n')
            self.assertEqual(userdata.read_text(), 'persistent app data')
            failed = aaas_bundle.restore_previous_installation(installation=install,
                                                                 previous=previous)
            self.assertEqual(aaas_bundle.verify_installation(install)['integrity'], 'PASS')
            self.assertEqual((install / 'runtime/scripts/aaas_cli.py').read_text(),
                             'print("bundle cli")\n')
            self.assertEqual(userdata.read_text(), 'persistent app data')
            self.assertEqual(aaas_bundle.verify_installation(failed)['integrity'], 'PASS')

    def test_reinstall_preserves_enrolled_workspace_and_existing_config(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo, source_workspace, _ = self.fixture(base)
            bundle = base / 'bundle'
            aaas_bundle.create_bundle(repo=repo, rootfs=source_workspace / 'rootfs_m1b1',
                                      output=bundle, workspace=source_workspace)
            install = base / 'install'
            workspace = base / 'runtime-workspace'
            config = base / 'config'
            data = base / 'data'
            with patch.object(aaas_bundle.shutil, 'disk_usage',
                              return_value=SimpleNamespace(free=64 << 30)):
                install_fixture(bundle=bundle, workspace=workspace, install_root=install,
                                config_home=config, data_home=data)
            marker = workspace / 'android-userdata/data/keep.txt'
            marker.write_text('do not replace')
            config_file = config / 'aaas/config.toml'
            config_file.write_text(config_file.read_text() + '\n# user setting preserved\n')
            shutil.rmtree(install)
            with patch.object(aaas_bundle.shutil, 'disk_usage',
                              return_value=SimpleNamespace(free=64 << 30)):
                result = install_fixture(bundle=bundle, workspace=workspace,
                                         install_root=install, config_home=config,
                                         data_home=data)
            self.assertTrue(result['workspace_reused'])
            self.assertTrue(result['configuration_preserved'])
            self.assertEqual(marker.read_text(), 'do not replace')
            self.assertIn('# user setting preserved', config_file.read_text())

    def test_installer_owned_workspace_migration_rejects_unrecognized_files(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo, source_workspace, _ = self.fixture(base)
            bundle = base / 'bundle'
            aaas_bundle.create_bundle(repo=repo, rootfs=source_workspace / 'rootfs_m1b1',
                                      output=bundle, workspace=source_workspace)
            install = base / 'install'
            workspace = base / 'workspace-new'
            with patch.object(aaas_bundle.shutil, 'disk_usage',
                              return_value=SimpleNamespace(free=64 << 30)):
                install_fixture(bundle=bundle, workspace=workspace,
                    install_root=install, config_home=base / 'config', data_home=base / 'data')
            marker = workspace / '.aaas-workspace.json'
            marker.unlink()
            (workspace / 'unrecognized.txt').write_text('preserve me')
            with self.assertRaisesRegex(aaas_bundle.BundleError, 'outside installer-staged'):
                aaas_bundle.enroll_installer_workspace(install, workspace)
            self.assertEqual((workspace / 'unrecognized.txt').read_text(), 'preserve me')

    def test_installed_artifact_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo, source_workspace, _ = self.fixture(base)
            bundle = base / 'bundle'
            aaas_bundle.create_bundle(repo=repo, rootfs=source_workspace / 'rootfs_m1b1',
                                      output=bundle, workspace=source_workspace)
            install = base / 'install'
            with patch.object(aaas_bundle.shutil, 'disk_usage',
                              return_value=SimpleNamespace(free=64 << 30)):
                install_fixture(bundle=bundle,
                    workspace=base / 'workspace-new', install_root=install,
                    config_home=base / 'config', data_home=base / 'data')
            (install / 'rootfs/system/bin/init').write_bytes(b'altered')
            with self.assertRaisesRegex(aaas_bundle.BundleError, 'size/type mismatch|hash mismatch'):
                aaas_bundle.verify_installation(install)

    def test_install_refuses_existing_workspace_and_preserves_it(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo, source_workspace, _ = self.fixture(base)
            bundle = base / 'bundle'
            aaas_bundle.create_bundle(repo=repo, rootfs=source_workspace / 'rootfs_m1b1',
                                      output=bundle, workspace=source_workspace)
            workspace = base / 'existing-workspace'
            workspace.mkdir(); marker = workspace / 'keep'; marker.write_text('preserve')
            with self.assertRaisesRegex(aaas_bundle.BundleError, 'must be empty'):
                aaas_bundle.install_bundle(bundle=bundle, workspace=workspace,
                                           install_root=base / 'install',
                                           config_home=base / 'config', data_home=base / 'data')
            self.assertEqual(marker.read_text(), 'preserve')
            self.assertFalse((base / 'install').exists())

    def test_refresh_runtime_file_updates_verified_bundle_and_install_only(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo, source_workspace, _ = self.fixture(base)
            bundle = base / 'bundle'
            aaas_bundle.create_bundle(repo=repo, rootfs=source_workspace / 'rootfs_m1b1',
                                      output=bundle, workspace=source_workspace)
            install_root = base / 'install'
            with patch.object(aaas_bundle.shutil, 'disk_usage',
                              return_value=SimpleNamespace(free=64 << 30)):
                install_fixture(bundle=bundle, workspace=base / 'fresh-workspace',
                                install_root=install_root, config_home=base / 'config',
                                data_home=base / 'data')
            source = base / 'fixed_runner.py'
            source.write_text('print("new runner")\n')
            before = (install_root / 'rootfs/system/bin/init').read_bytes()
            result = aaas_bundle.refresh_runtime_file(
                bundle=bundle, installation=install_root, source=source,
                relative='runtime/scripts/aaas_cli.py')
            self.assertEqual(result['bundle_integrity'], 'PASS')
            self.assertEqual(result['installation_integrity'], 'PASS')
            self.assertEqual((bundle / 'runtime/scripts/aaas_cli.py').read_bytes(),
                             source.read_bytes())
            self.assertEqual((install_root / 'runtime/scripts/aaas_cli.py').read_bytes(),
                             source.read_bytes())
            self.assertEqual((install_root / 'rootfs/system/bin/init').read_bytes(), before)

    def test_bundle_paths_reject_parent_escape(self):
        with self.assertRaises(aaas_bundle.BundleError):
            aaas_bundle._safe_relative('../outside')


if __name__ == '__main__':
    unittest.main()
