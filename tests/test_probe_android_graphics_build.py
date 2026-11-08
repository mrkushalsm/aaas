import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import probe_android_graphics_build as probe


class GraphicsBuildProbeTest(unittest.TestCase):
    def test_manifest_source_snapshot_is_immutable(self):
        data = json.loads(probe.MANIFEST.read_text())
        snapshot = data['source_snapshot']
        self.assertRegex(snapshot['superproject_revision'], r'^[0-9a-f]{40}$')
        for project in snapshot['projects']:
            self.assertRegex(project['revision'], r'^[0-9a-f]{40}$')
            self.assertIn(project['layout'], ('copy', 'symlink'))

    def test_revision_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / 'sources' / 'sample'
            checkout.mkdir(parents=True)
            project = dict(checkout='sample', path='external/sample', revision='a' * 40)
            with patch.object(probe.subprocess, 'run') as run:
                run.return_value.stdout = 'b' * 40 + '\n'
                with self.assertRaisesRegex(probe.ws.WorkspaceError, 'revision mismatch'):
                    probe.verify_sources(Path(tmp), [project])

    def test_layout_rejects_conflicting_existing_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            src = workspace / 'sources/sample'
            src.mkdir(parents=True)
            dest = workspace / 'probes/graphics-qpr2/external/sample'
            dest.mkdir(parents=True)
            project = dict(checkout='sample', path='external/sample',
                           revision='a' * 40, layout='symlink')
            with patch.object(probe.subprocess, 'run') as run:
                run.return_value.returncode = 1
                with self.assertRaisesRegex(probe.ws.WorkspaceError, 'conflicting'):
                    probe.prepare_layout(workspace, [project])

    def test_layout_replaces_own_symlink_with_copy_for_soong_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            src = workspace / 'sources/sample'
            src.mkdir(parents=True)
            (src / 'Android.bp').write_text('package {}\n')
            dest = workspace / 'probes/graphics-qpr2/external/sample'
            dest.parent.mkdir(parents=True)
            dest.symlink_to(src, target_is_directory=True)
            project = dict(checkout='sample', path='external/sample',
                           revision='a' * 40, layout='copy')
            probe.prepare_layout(workspace, [project])
            self.assertFalse(dest.is_symlink())
            self.assertEqual((dest / 'Android.bp').read_text(), 'package {}\n')
            self.assertTrue((src / 'Android.bp').exists())

    def test_repairs_only_dangling_generated_source_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            src = workspace / 'sources/build-make-qpr2'
            src.mkdir(parents=True)
            root = workspace / 'probes/graphics-qpr2'
            dest = root / 'build/make'
            dest.parent.mkdir(parents=True)
            dest.symlink_to('/old/mount/aaas-workspace/sources/build-make-qpr2')
            probe.prepare_layout(workspace, [{
                'path': 'build/make', 'checkout': 'build-make-qpr2',
                'revision': 'a' * 40, 'layout': 'copy'
            }])
            self.assertFalse(dest.is_symlink())
            self.assertTrue(dest.is_dir())

    def test_refuses_to_replace_live_conflicting_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / 'sources/sample').mkdir(parents=True)
            conflicting = workspace / 'other-source'
            conflicting.mkdir()
            dest = workspace / 'probes/graphics-qpr2/external/sample'
            dest.parent.mkdir(parents=True)
            dest.symlink_to(conflicting, target_is_directory=True)
            project = dict(checkout='sample', path='external/sample',
                           revision='a' * 40, layout='copy')
            with self.assertRaisesRegex(probe.ws.WorkspaceError, 'conflicting'):
                probe.prepare_layout(workspace, [project])
            self.assertTrue(dest.is_symlink())


if __name__ == '__main__':
    unittest.main()
