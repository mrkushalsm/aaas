import json
import os
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_config


class AaasConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.env = {
            'HOME': str(self.root / 'home'),
            'XDG_CONFIG_HOME': str(self.root / 'cfg'),
            'XDG_DATA_HOME': str(self.root / 'data'),
            'XDG_CACHE_HOME': str(self.root / 'cache'),
            'XDG_STATE_HOME': str(self.root / 'state'),
            'XDG_RUNTIME_DIR': str(self.root / 'run'),
        }

    def tearDown(self):
        self.temporary.cleanup()

    def _write_config(self, content):
        path = Path(self.env['XDG_CONFIG_HOME']) / 'aaas' / 'config.toml'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def test_defaults_follow_alternate_xdg_roots(self):
        config = aaas_config.resolve_config(env=self.env)
        self.assertEqual(config.workspace, Path(self.env['XDG_DATA_HOME']) / 'aaas/workspace')
        self.assertEqual(config.rootfs, config.workspace / 'rootfs_m1b1')
        self.assertEqual(config.cache, Path(self.env['XDG_CACHE_HOME']) / 'aaas')
        self.assertEqual(config.state, Path(self.env['XDG_STATE_HOME']) / 'aaas')
        self.assertEqual(config.runtime, Path(self.env['XDG_RUNTIME_DIR']) / 'aaas')
        self.assertNotIn(self.env['HOME'], str(config.workspace))
        self.assertNotIn('/run/media/', str(config.workspace))

    def test_precedence_cli_then_environment_then_config_then_installation(self):
        runtime_data = Path(self.env['XDG_DATA_HOME']) / 'aaas'
        runtime_data.mkdir(parents=True)
        (runtime_data / 'installation.json').write_text(json.dumps({
            'profile': 'android16-ranchu-x86_64',
            'paths': {'workspace': str(self.root / 'installed-workspace')},
        }))
        self._write_config('[paths]\nworkspace = "' + str(self.root / 'configured')
                           + '"\n[runtime]\nidle_timeout_seconds = 90\n')
        base = aaas_config.resolve_config(env=self.env)
        self.assertEqual(base.workspace, self.root / 'configured')
        self.assertEqual(base.idle_timeout_seconds, 90)
        env = dict(self.env, AAAS_WORKSPACE=str(self.root / 'environment'))
        overridden = aaas_config.resolve_config(env=env)
        self.assertEqual(overridden.workspace, self.root / 'environment')
        explicit = aaas_config.resolve_config(
            env=env, cli={'workspace': str(self.root / 'argument')})
        self.assertEqual(explicit.workspace, self.root / 'argument')
        empty = dict(self.env)
        (Path(empty['XDG_CONFIG_HOME']) / 'aaas/config.toml').unlink()
        from_config = aaas_config.resolve_config(env=empty)
        self.assertEqual(from_config.workspace, self.root / 'installed-workspace')

    def test_invalid_relative_xdg_and_workspace_paths_are_rejected(self):
        with self.assertRaisesRegex(aaas_config.ConfigurationError, 'XDG_DATA_HOME'):
            aaas_config.resolve_config(env=dict(self.env, XDG_DATA_HOME='relative'))
        self._write_config('[paths]\nworkspace = "relative/path"\n')
        with self.assertRaisesRegex(aaas_config.ConfigurationError, 'workspace must be absolute'):
            aaas_config.resolve_config(env=self.env)

    def test_profile_backend_and_resource_settings_are_validated(self):
        self._write_config('[installation]\nprofile = "android-17"\n')
        with self.assertRaisesRegex(aaas_config.ConfigurationError, 'unsupported Android profile'):
            aaas_config.resolve_config(env=self.env)
        self._write_config('[graphics]\nbackend = "unknown"\n')
        with self.assertRaisesRegex(aaas_config.ConfigurationError, 'unsupported graphics backend'):
            aaas_config.resolve_config(env=self.env)
        with self.assertRaisesRegex(aaas_config.ConfigurationError, '1 to 3600'):
            aaas_config.resolve_config(env=self.env,
                                       cli={'idle_timeout_seconds': 3601})

    def test_environment_feature_overrides_and_default_template(self):
        config = aaas_config.resolve_config(env=dict(self.env, AAAS_AUDIO='yes'))
        self.assertTrue(config.audio)
        self.assertTrue(config.clipboard)
        self.assertIn('[paths]', config.toml_defaults())
        self.assertIn('profile = "android16-ranchu-x86_64"', config.toml_defaults())
        self.assertIn('resource_limit = "none"', config.toml_defaults())

    def test_resource_limit_uses_supported_runtime_policy_names(self):
        enabled = aaas_config.resolve_config(env=self.env,
                                             cli={'resource_limit': 'cgroup'})
        self.assertEqual(enabled.resource_limit, 'cgroup')
        with self.assertRaisesRegex(aaas_config.ConfigurationError, 'resource_limit'):
            aaas_config.resolve_config(env=self.env,
                                       cli={'resource_limit': 'unbounded'})

    def test_malformed_installation_manifest_fails_closed(self):
        manifest = Path(self.env['XDG_DATA_HOME']) / 'aaas/installation.json'
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{')
        with self.assertRaisesRegex(aaas_config.ConfigurationError,
                                    'cannot read installation manifest'):
            aaas_config.resolve_config(env=self.env)


if __name__ == '__main__':
    unittest.main()
