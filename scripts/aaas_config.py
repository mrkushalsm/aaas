#!/usr/bin/env python3
"""Resolve AaaS user configuration and installation paths.

Precedence is explicit argument, AAAS_* environment override, user TOML,
installation manifest, then XDG-derived defaults. Paths are always resolved
as user data; this module never creates directories or elevates privileges.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tomllib


class ConfigurationError(ValueError):
    """Configuration is malformed or unsafe to use."""


def _xdg(env, name, fallback):
    value = env.get(name)
    path = Path(value).expanduser() if value else Path(fallback).expanduser()
    if not path.is_absolute():
        raise ConfigurationError(f'{name} must be an absolute path: {path}')
    return path


def xdg_paths(env=None):
    env = os.environ if env is None else env
    home = Path(env.get('HOME') or Path.home()).expanduser()
    if not home.is_absolute():
        raise ConfigurationError('HOME must be an absolute path')
    config = _xdg(env, 'XDG_CONFIG_HOME', home / '.config')
    data = _xdg(env, 'XDG_DATA_HOME', home / '.local/share')
    cache = _xdg(env, 'XDG_CACHE_HOME', home / '.cache')
    state = _xdg(env, 'XDG_STATE_HOME', home / '.local/state')
    runtime_value = env.get('XDG_RUNTIME_DIR')
    runtime = (Path(runtime_value).expanduser() if runtime_value else
               Path('/tmp') / f'aaas-{os.getuid()}')
    if not runtime.is_absolute():
        raise ConfigurationError('XDG_RUNTIME_DIR must be an absolute path')
    return {'home': home, 'config_home': config, 'data_home': data,
            'cache_home': cache, 'state_home': state, 'runtime_home': runtime}


def _load_toml(path):
    try:
        with path.open('rb') as stream:
            value = tomllib.load(stream)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f'cannot read configuration {path}: {error}') from error
    if not isinstance(value, dict):
        raise ConfigurationError(f'configuration root must be a table: {path}')
    return value


def _load_installation(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(f'cannot read installation manifest {path}: {error}') from error
    if not isinstance(value, dict):
        raise ConfigurationError(f'installation manifest root must be an object: {path}')
    return value


def _absolute_path(value, key):
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise ConfigurationError(f'{key} must be a non-empty path')
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigurationError(f'{key} must be absolute: {value}')
    return path


@dataclass(frozen=True)
class AaasConfig:
    repository: Path
    config_file: Path
    installation_manifest: Path
    workspace: Path
    runtime_data: Path
    cache: Path
    state: Path
    runtime: Path
    rootfs: Path
    profile: str
    idle_timeout_seconds: int
    audio: bool
    clipboard: bool
    notifications: bool
    graphics_backend: str
    resource_limit: str | None

    def toml_defaults(self):
        """Return a portable first-run config; caller chooses when to write it."""
        return (
            '# AaaS user configuration. Paths use XDG defaults when omitted.\n'
            '[paths]\n'
            f'workspace = {json.dumps(str(self.workspace))}\n'
            '\n[installation]\n'
            f'profile = {json.dumps(self.profile)}\n'
            '\n[runtime]\n'
            f'idle_timeout_seconds = {self.idle_timeout_seconds}\n'
            f'resource_limit = {json.dumps(self.resource_limit or "none")}\n'
            '\n[features]\n'
            f'audio = {str(self.audio).lower()}\n'
            f'clipboard = {str(self.clipboard).lower()}\n'
            f'notifications = {str(self.notifications).lower()}\n'
            '\n[graphics]\n'
            f'backend = {json.dumps(self.graphics_backend)}\n'
        )


def resolve_config(*, repository=None, env=None, cli=None):
    """Resolve settings with the documented precedence and validate values."""
    env = os.environ if env is None else env
    cli = {} if cli is None else dict(cli)
    xdg = xdg_paths(env)
    repository = Path(repository or Path(__file__).resolve().parents[1]).resolve()
    config_file = xdg['config_home'] / 'aaas' / 'config.toml'
    runtime_data = xdg['data_home'] / 'aaas'
    installation_path = runtime_data / 'installation.json'
    user_config = _load_toml(config_file)
    installation = _load_installation(installation_path)

    def table(value, name):
        if not isinstance(value, dict):
            raise ConfigurationError(f'{name} must be a table/object')
        return value

    paths = table(user_config.get('paths', {}), 'paths')
    install = table(user_config.get('installation', {}), 'installation')
    runtime = table(user_config.get('runtime', {}), 'runtime')
    features = table(user_config.get('features', {}), 'features')
    graphics = table(user_config.get('graphics', {}), 'graphics')
    installed_paths = table(installation.get('paths', {}), 'installation paths')
    installed_profile = installation.get('profile')

    defaults = {
        'workspace': xdg['data_home'] / 'aaas' / 'workspace',
        'rootfs': None,
        'profile': 'android16-ranchu-x86_64',
        'idle_timeout_seconds': 60,
        'audio': False,
        'clipboard': True,
        'notifications': True,
        'graphics_backend': 'kwin-wayland',
        'resource_limit': None,
    }

    def choose(key, env_name, config_value, installed_value=None):
        if key in cli and cli[key] is not None:
            return cli[key]
        if env.get(env_name):
            return env[env_name]
        if config_value is not None:
            return config_value
        if installed_value is not None:
            return installed_value
        return defaults[key]

    workspace_raw = choose('workspace', 'AAAS_WORKSPACE', paths.get('workspace'),
                           installed_paths.get('workspace'))
    workspace = _absolute_path(workspace_raw, 'workspace')
    rootfs_raw = choose('rootfs', 'AAAS_ROOTFS', paths.get('rootfs'),
                        installed_paths.get('rootfs'))
    rootfs = (_absolute_path(rootfs_raw, 'rootfs') if rootfs_raw else
              workspace / 'rootfs_m1b1')
    profile = choose('profile', 'AAAS_PROFILE', install.get('profile'), installed_profile)
    if profile != 'android16-ranchu-x86_64':
        raise ConfigurationError(f'unsupported Android profile: {profile}')
    idle = choose('idle_timeout_seconds', 'AAAS_IDLE_TIMEOUT_SECONDS',
                  runtime.get('idle_timeout_seconds'))
    if isinstance(idle, bool):
        raise ConfigurationError('idle_timeout_seconds must be an integer from 1 to 3600')
    try:
        idle = int(idle)
    except (TypeError, ValueError) as error:
        raise ConfigurationError('idle_timeout_seconds must be an integer from 1 to 3600') from error
    if not 1 <= idle <= 3600:
        raise ConfigurationError('idle_timeout_seconds must be from 1 to 3600')

    def boolean(key, env_name, config_value):
        value = choose(key, env_name, config_value)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ('1', 'true', 'yes', 'on'):
            return True
        if isinstance(value, str) and value.lower() in ('0', 'false', 'no', 'off'):
            return False
        raise ConfigurationError(f'{key} must be a boolean')

    def xdg_child(home, name):
        return home / 'aaas'

    audio = boolean('audio', 'AAAS_AUDIO', features.get('audio', defaults['audio']))
    clipboard = boolean('clipboard', 'AAAS_CLIPBOARD',
                        features.get('clipboard', defaults['clipboard']))
    notifications = boolean('notifications', 'AAAS_NOTIFICATIONS',
                             features.get('notifications', defaults['notifications']))
    backend = choose('graphics_backend', 'AAAS_GRAPHICS_BACKEND',
                     graphics.get('backend'))
    if backend != 'kwin-wayland':
        raise ConfigurationError(f'unsupported graphics backend: {backend}')
    resource_limit = choose('resource_limit', 'AAAS_RESOURCE_LIMIT',
                            runtime.get('resource_limit'))
    if resource_limit not in (None, 'none', 'cgroup'):
        raise ConfigurationError('resource_limit must be "none" or "cgroup"')
    return AaasConfig(
        repository=repository,
        config_file=config_file,
        installation_manifest=installation_path,
        workspace=workspace,
        runtime_data=runtime_data,
        cache=xdg_child(xdg['cache_home'], 'aaas'),
        state=xdg_child(xdg['state_home'], 'aaas'),
        runtime=xdg_child(xdg['runtime_home'], 'aaas'),
        rootfs=rootfs,
        profile=profile,
        idle_timeout_seconds=idle,
        audio=audio,
        clipboard=clipboard,
        notifications=notifications,
        graphics_backend=backend,
        resource_limit=resource_limit,
    )
