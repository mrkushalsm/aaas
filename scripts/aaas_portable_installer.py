#!/usr/bin/env python3
"""Install a verified portable AaaS local-development bundle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import aaas_bundle
import aaas_config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--installation', type=Path)
    parser.add_argument('--config-home', type=Path)
    parser.add_argument('--data-home', type=Path)
    parser.add_argument('--service-name', default='aaas-runtime.service')
    args = parser.parse_args(argv)
    bundle = Path(os.environ.get('AAAS_BUNDLE_PATH') or
                  Path(__file__).resolve().parents[2]).resolve(strict=True)
    verified = aaas_bundle.verify_bundle(bundle)
    xdg = aaas_config.xdg_paths()
    config_home = (args.config_home or xdg['config_home']).expanduser().absolute()
    data_home = (args.data_home or xdg['data_home']).expanduser().absolute()
    workspace = (args.workspace or data_home / 'aaas/workspace').expanduser().absolute()
    installation = (args.installation or
                    data_home / 'aaas/installations' / verified['bundle_id']).expanduser().absolute()
    result = aaas_bundle.install_bundle(
        bundle=bundle, workspace=workspace, install_root=installation,
        config_home=config_home, data_home=data_home, desktop_home=data_home)
    cli = installation / 'bin/aaas'
    env = dict(os.environ)
    env.update({'XDG_CONFIG_HOME': str(config_home), 'XDG_DATA_HOME': str(data_home),
                'AAAS_DESKTOP_DATA_HOME': str(data_home),
                'AAAS_LAUNCHER_PATH': str(cli),
                'AAAS_RUNTIME_SERVICE': args.service_name})
    for name in ('AAAS_WORKSPACE', 'AAAS_ROOTFS', 'AAAS_RUNTIME_ROOT', 'AAAS_PROFILE',
                 'PYTHONPATH'):
        env.pop(name, None)
    for command in (('dev', 'setup', '--json'), ('runtime', 'install-service', '--json')):
        completed = subprocess.run([str(cli), *command], env=env, capture_output=True,
                                   text=True, timeout=90)
        if completed.returncode:
            raise aaas_bundle.BundleError(
                f"installed profile setup failed ({' '.join(command)}): " +
                (completed.stderr or completed.stdout).strip())
    command_link = Path.home() / '.local/bin/aaas-portable'
    command_link.parent.mkdir(parents=True, exist_ok=True)
    link_created = False
    if not command_link.exists() and not command_link.is_symlink():
        command_link.symlink_to(cli)
        link_created = True
    result.update({'bundle_id': verified['bundle_id'], 'command': str(cli),
                   'command_link': str(command_link) if link_created else None,
                   'service': args.service_name,
                   'runtime_security': 'NOT_APPROVED_LOCAL_DEVELOPMENT'})
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (aaas_bundle.BundleError, aaas_config.ConfigurationError, OSError,
            subprocess.SubprocessError) as error:
        print(f'AaaS portable installation failed: {error}', file=sys.stderr)
        raise SystemExit(2)
