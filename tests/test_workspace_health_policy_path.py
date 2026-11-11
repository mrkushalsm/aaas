import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceHealthPolicyPathTests(unittest.TestCase):
    def _loaded_policy(self, environment):
        return subprocess.check_output(
            [sys.executable, '-c',
             'from scripts import android_workspace; print(android_workspace.HEALTH_POLICY)'],
            cwd=ROOT, env={**environment, 'PYTHONPATH': os.pathsep.join((str(ROOT), str(ROOT / 'scripts')))}, text=True).strip()

    def test_xdg_state_policy_overrides_repository_template(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state'
            local = state / 'aaas' / 'workspace-health.json'
            local.parent.mkdir(parents=True)
            local.write_text('{"schema": 1, "volumes": {}}')
            env = {**os.environ, 'XDG_STATE_HOME': str(state)}
            env.pop('AAAS_WORKSPACE_HEALTH_POLICY', None)
            self.assertEqual(Path(self._loaded_policy(env)), local)

    def test_explicit_health_policy_override_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state'
            local = state / 'aaas' / 'workspace-health.json'
            local.parent.mkdir(parents=True)
            local.write_text('{"schema": 1, "volumes": {}}')
            explicit = Path(temp) / 'explicit.json'
            explicit.write_text('{"schema": 1, "volumes": {}}')
            env = {**os.environ, 'XDG_STATE_HOME': str(state),
                   'AAAS_WORKSPACE_HEALTH_POLICY': str(explicit)}
            self.assertEqual(Path(self._loaded_policy(env)), explicit)


if __name__ == '__main__':
    unittest.main()
