import json
from pathlib import Path
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
                         return_value=SimpleNamespace(f_bavail=1 << 30, f_frsize=4096)):
        return aaas_bundle.install_bundle(**kwargs)


class BundleTests(unittest.TestCase):
    def fixture(self, root: Path):
        repo = root / 'repo'
        workspace = root / 'workspace'
        rootfs = workspace / 'rootfs_m1b1'
        (repo / 'scripts').mkdir(parents=True)
        (repo / 'scripts/aaas_cli.py').write_text('print("bundle cli")\n')
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
            self.assertFalse((output / 'rootfs/data/private.db').exists())
            self.assertFalse((output / 'rootfs/tmp/old.log').exists())
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
