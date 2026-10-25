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


if __name__ == '__main__':
    unittest.main()
