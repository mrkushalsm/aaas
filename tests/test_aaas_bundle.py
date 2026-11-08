import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_bundle


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
                    result = aaas_bundle.install_bundle(
                        bundle=bundle, workspace=base / f'workspace-{suffix}',
                        install_root=base / f'install-{suffix}',
                        config_home=base / f'config-{suffix}', data_home=base / f'data-{suffix}')
                results.append(result)
                self.assertEqual(result['installation_integrity'], 'PASS')
                self.assertEqual(result['general_runtime_start'], 'BLOCKED')
                self.assertTrue((base / f'install-{suffix}/bin/aaas').is_file())
                self.assertTrue((base / f'install-{suffix}/rootfs/data').is_dir())
                self.assertFalse((base / f'install-{suffix}/rootfs/data/private.db').exists())
                self.assertEqual(aaas_bundle.verify_installation(
                    base / f'install-{suffix}')['integrity'], 'PASS')
                self.assertIn(str(base / f'install-{suffix}/rootfs'),
                              (base / f'config-{suffix}/aaas/config.toml').read_text())
            self.assertNotEqual(results[0]['installation'], results[1]['installation'])
            installed = json.loads((base / 'data-one/aaas/installation.json').read_text())
            self.assertNotIn(str(source_workspace), installed['paths'].values())

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
                aaas_bundle.install_bundle(bundle=bundle,
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

    def test_bundle_paths_reject_parent_escape(self):
        with self.assertRaises(aaas_bundle.BundleError):
            aaas_bundle._safe_relative('../outside')


if __name__ == '__main__':
    unittest.main()
