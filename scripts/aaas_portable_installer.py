#!/usr/bin/env python3
"""Install a verified portable AaaS local-development bundle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys

import aaas_bundle
import aaas_config


def clear_android_rootfs_for_uninstall(installation):
    """Remove subordinate-owned Android files from the immutable rootfs only.

    The Android rootfs is an installed artifact and may contain files owned by
    the rootless container's subordinate IDs. Userdata is a sibling workspace
    and is never opened by this helper. A short-lived user namespace maps the
    caller plus its configured subordinate ID ranges, then makes directories
    traversable and removes only children of the verified installation rootfs.
    """
    root = Path(installation).resolve(strict=True)
    rootfs = root / 'rootfs'
    if not rootfs.exists():
        return False
    if not rootfs.is_dir() or rootfs.is_symlink():
        raise aaas_bundle.BundleError('refusing unexpected Android rootfs object')
    try:
        with os.scandir(rootfs) as entries:
            next(entries)
    except StopIteration:
        return False
    except PermissionError:
        pass
    unshare = shutil.which('unshare')
    if not unshare:
        raise aaas_bundle.BundleError(
            'rootless user namespaces are unavailable to clean Android rootfs')
    username = pwd.getpwuid(os.getuid()).pw_name

    def subordinate_map(filename, option):
        try:
            rows = Path(filename).read_text(encoding='ascii').splitlines()
        except OSError:
            rows = []
        for row in rows:
            fields = row.split(':')
            if len(fields) != 3 or fields[0] not in (username, str(os.getuid())):
                continue
            start, count = int(fields[1]), int(fields[2])
            if count > 0:
                return [f'{option}=0:{os.getuid()}:1',
                        f'{option}=1:{start}:{min(count, 65536)}']
        raise aaas_bundle.BundleError(
            f'{filename} has no subordinate ID range; Android rootfs preserved')

    maps = (subordinate_map('/etc/subuid', '--map-users') +
            subordinate_map('/etc/subgid', '--map-groups'))
    parent_fd = os.open(rootfs, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    script = r'''import os, stat
fd=int(os.environ['AAAS_ROOTFS_FD']); os.fchdir(fd)
def remove_dir(path):
    os.chmod(path, 0o700, follow_symlinks=False)
    for entry in os.scandir(path):
        child=os.path.join(path, entry.name)
        if entry.is_dir(follow_symlinks=False): remove_dir(child)
        else: os.unlink(child)
    os.rmdir(path)
for entry in os.scandir('.'):
    if entry.is_dir(follow_symlinks=False): remove_dir(entry.name)
    else: os.unlink(entry.name)
'''
    env = dict(os.environ, AAAS_ROOTFS_FD=str(parent_fd))
    try:
        result = subprocess.run(
            [unshare, '--user', *maps, '--setgroups', 'allow',
             sys.executable, '-c', script],
            env=env, pass_fds=(parent_fd,), capture_output=True, text=True,
            timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        raise aaas_bundle.BundleError(
            f'cannot safely map Android rootfs ownership for uninstall: {error}') from error
    finally:
        os.close(parent_fd)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-500:]
        raise aaas_bundle.BundleError(
            f'cannot safely clean Android rootfs; installation preserved: {detail}')
    return True


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
    if installation.exists():
        existing = aaas_bundle.verify_installation(installation)
        if existing.get('bundle_id') != verified.get('bundle_id'):
            raise aaas_bundle.BundleError(
                'destination already contains a different release; choose a new prefix')
        result = {'installation': str(installation), 'workspace': str(workspace),
                  'installation_integrity': 'PASS', 'resumed_existing_install': True}
    else:
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
