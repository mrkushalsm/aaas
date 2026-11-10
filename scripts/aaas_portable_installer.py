#!/usr/bin/env python3
"""Install a verified portable AaaS local-development bundle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import aaas_bundle
import aaas_config


def clear_rootfs_cache_for_uninstall(installation):
    """Remove Android's subordinate-owned ephemeral /cache before uninstall.

    Rootless Android can change the installed rootfs cache directory's owner
    to a subordinate UID. The user still owns the rootfs parent, but cannot
    traverse that directory with ordinary permissions. Use a short-lived
    user namespace mapping only for this exact disposable cache directory;
    never apply it to userdata or arbitrary install paths.
    """
    root = Path(installation).resolve(strict=True)
    cache = root / 'rootfs' / 'cache'
    try:
        metadata = cache.lstat()
    except FileNotFoundError:
        return False
    if not cache.is_dir() or cache.is_symlink():
        raise aaas_bundle.BundleError('refusing unexpected Android rootfs cache object')
    if os.access(cache, os.R_OK | os.W_OK | os.X_OK):
        shutil.rmtree(cache)
        return True

    uid, gid = metadata.st_uid, metadata.st_gid
    if uid == 0 or uid == 65534 or gid in (0, 65534):
        raise aaas_bundle.BundleError(
            'rootfs cache has unmapped ownership; preserve it and use an administrator cleanup')
    unshare = shutil.which('unshare')
    if not unshare:
        raise aaas_bundle.BundleError(
            'rootless user namespaces are unavailable to clean Android rootfs cache')
    user_maps = [f'--map-users=0:{os.getuid()}:1']
    if uid != os.getuid():
        user_maps.append(f'--map-users={uid}:{uid}:1')
    group_maps = [f'--map-groups=0:{os.getgid()}:1']
    if gid != os.getgid():
        group_maps.append(f'--map-groups={gid}:{gid}:1')
    parent_fd = os.open(cache.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    script = (
        'import os, shutil, stat; fd=int(os.environ["AAAS_CACHE_PARENT_FD"]); '
        f'uid={uid}; gid={gid}; os.setgroups(sorted(set((0, gid)))); '
        'os.setgid(gid); os.setuid(uid); os.fchdir(fd); '
        '[(shutil.rmtree("cache/"+e.name) if e.is_dir(follow_symlinks=False) '
        'else os.unlink("cache/"+e.name)) for e in os.scandir("cache")]')
    env = dict(os.environ, AAAS_CACHE_PARENT_FD=str(parent_fd))
    try:
        result = subprocess.run(
            [unshare, '--user', *user_maps, *group_maps, '--setgroups', 'allow',
             sys.executable, '-c', script], env=env, pass_fds=(parent_fd,),
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        raise aaas_bundle.BundleError(
            f'cannot safely map Android cache ownership for uninstall: {error}') from error
    finally:
        os.close(parent_fd)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-400:]
        raise aaas_bundle.BundleError(
            f'cannot safely clean Android rootfs cache; preserved installation: {detail}')
    try:
        cache.rmdir()
    except OSError as error:
        raise aaas_bundle.BundleError(
            f'Android rootfs cache remains after cleanup; preserved installation: {error}') from error
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
