#!/usr/bin/env python3
"""Unified user-facing AaaS developer runtime command."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import aaas_config
import aaas_profiles


class CliError(RuntimeError):
    pass


def _emit(value, as_json=False):
    if as_json or isinstance(value, (dict, list)):
        print(json.dumps(value, indent=2, sort_keys=True, default=str))
    else:
        print(value)


def _run_script(script, *args, config=None, check=True):
    config = config or aaas_config.resolve_config(repository=ROOT)
    env = dict(os.environ)
    env.update(AAAS_WORKSPACE=str(config.workspace), AAAS_ROOTFS=str(config.rootfs),
               AAAS_PROFILE=config.profile,
               AAAS_IDLE_TIMEOUT_SECONDS=str(config.idle_timeout_seconds),
               AAAS_AUDIO='1' if config.audio else '0',
               PYTHONPATH=str(ROOT / 'scripts') + os.pathsep + env.get('PYTHONPATH', ''))
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *map(str, args)],
                            env=env, check=False)
    if check and result.returncode:
        raise CliError(f'{script} exited with status {result.returncode}')
    return result.returncode


def _status(config):
    root = config.workspace / 'tmp'
    sessions = sorted(root.glob('m1b84_session_*/status'),
                      key=lambda path: path.stat().st_mtime, reverse=True)
    active = None
    lock_path = root / '.aaas_session.lock'
    locked = False
    if lock_path.exists():
        with lock_path.open('r+') as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                locked = True
    for path in sessions:
        try:
            state = path.read_text(encoding='ascii').strip()
        except OSError:
            continue
        if locked and state in {'STARTING', 'PREPARING', 'STARTING_PRESENTER',
                                'RUNNING', 'STOPPING'}:
            active = {'state': state, 'session': str(path.parent),
                      'updated': path.stat().st_mtime}
            break
    return {'runtime': active or {'state': 'STOPPED'},
            'profile': config.profile, 'workspace': str(config.workspace),
            'rootfs': str(config.rootfs)}


def _doctor(config):
    checks = []

    def add(name, state, detail, mandatory=True):
        checks.append({'name': name, 'state': state, 'mandatory': mandatory,
                       'detail': detail})

    add('operating_system', 'SUPPORTED' if sys.platform.startswith('linux') else 'UNSUPPORTED_HOST',
        platform.platform())
    add('architecture', 'SUPPORTED' if platform.machine() in ('x86_64', 'amd64') else 'UNSUPPORTED_HOST',
        platform.machine())
    wayland = bool(os.environ.get('WAYLAND_DISPLAY'))
    compositor = os.environ.get('XDG_CURRENT_DESKTOP', '')
    add('wayland_session', 'SUPPORTED' if wayland else 'MISSING_PERMISSION',
        f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', 'unset')}; desktop={compositor or 'unknown'}")
    add('kwin_wayland', 'SUPPORTED' if 'KDE' in compositor.upper() or shutil.which('kwin_wayland')
        else 'UNVERIFIED_CONFIGURATION', 'KWin detected by session name or executable')
    unshare = shutil.which('unshare')
    if unshare:
        try:
            probe = subprocess.run([unshare, '--user', '--map-root-user', 'true'],
                                   capture_output=True, timeout=5)
            userns = probe.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            userns = False
    else:
        userns = False
    add('user_namespaces', 'SUPPORTED' if userns else 'MISSING_PERMISSION',
        'unshare user namespace probe')
    binder_available = 'nodev\tbinder' in Path('/proc/filesystems').read_text(errors='replace')
    binderfs_ok = False
    binder_detail = 'binder filesystem is not registered in /proc/filesystems'
    if binder_available and unshare:
        probe = ("set -eu; d=$(mktemp -d); trap 'umount \"$d\" 2>/dev/null || true; "
                 "rmdir \"$d\"' EXIT; mount -t binder binder \"$d\"; umount \"$d\"")
        try:
            result = subprocess.run([unshare, '--user', '--map-root-user', '--mount',
                                     'sh', '-c', probe], capture_output=True, text=True,
                                    timeout=8)
            binderfs_ok = result.returncode == 0
            binder_detail = ('unprivileged binderfs mount succeeded' if binderfs_ok else
                             (result.stderr.strip() or 'unprivileged binderfs mount failed'))
        except (OSError, subprocess.TimeoutExpired) as error:
            binder_detail = str(error)
    add('binderfs', 'SUPPORTED' if binderfs_ok else 'MISSING_PERMISSION',
        binder_detail)
    fuse_path = Path('/dev/fuse')
    add('fuse', 'SUPPORTED' if fuse_path.exists() and os.access(fuse_path, os.R_OK | os.W_OK)
        else 'MISSING_DEPENDENCY', str(fuse_path), mandatory=False)
    audio_service = False
    audio_detail = 'no active PipeWire/PulseAudio-compatible endpoint detected'
    if shutil.which('pw-cli'):
        try:
            probe = subprocess.run(['pw-cli', 'info', '0'], capture_output=True,
                                   text=True, timeout=3)
            audio_service = probe.returncode == 0
            if audio_service:
                audio_detail = 'PipeWire server responds to pw-cli'
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not audio_service and shutil.which('pactl'):
        try:
            probe = subprocess.run(['pactl', 'info'], capture_output=True,
                                   text=True, timeout=3)
            audio_service = probe.returncode == 0
            if audio_service:
                audio_detail = 'PulseAudio-compatible server responds to pactl'
        except (OSError, subprocess.TimeoutExpired):
            pass
    add('pipewire', 'SUPPORTED' if audio_service else 'MISSING_DEPENDENCY',
        audio_detail, mandatory=False)
    wayland_info = shutil.which('wayland-info')
    add('wayland_protocols', 'SUPPORTED' if wayland and wayland_info else
        'UNVERIFIED_CONFIGURATION',
        str(wayland_info) if wayland_info else 'wayland-info unavailable; protocol discovery unverified',
        mandatory=False)
    vulkaninfo = shutil.which('vulkaninfo')
    add('graphics_api', 'UNVERIFIED_CONFIGURATION',
        f'vulkaninfo available at {vulkaninfo}; GPU API details require runtime query'
        if vulkaninfo else 'Vulkan/GLES driver discovery is not available from doctor',
        mandatory=False)
    add('dmabuf_import', 'UNVERIFIED_CONFIGURATION',
        'DMA-BUF format/modifier import is verified only by the live presenter acceptance',
        mandatory=False)
    cgroup_v2 = Path('/sys/fs/cgroup/cgroup.controllers').is_file()
    add('cgroups_v2', 'SUPPORTED' if cgroup_v2 else 'UNVERIFIED_CONFIGURATION',
        'unified cgroup v2 detected' if cgroup_v2 else 'unified cgroup v2 not detected',
        mandatory=False)
    add('build_tools', 'SUPPORTED' if all(shutil.which(tool) for tool in ('make', 'cc'))
        else 'MISSING_DEPENDENCY', 'make and C compiler required by native artifact builders',
        mandatory=False)
    add('memory', 'SUPPORTED' if _available_memory_bytes() >= 4 * (1 << 30) else 'UNVERIFIED_CONFIGURATION',
        f'{_available_memory_bytes() // (1 << 30)} GiB available', mandatory=False)
    add('rootfs', 'SUPPORTED' if config.rootfs.is_dir() else 'MISSING_DEPENDENCY',
        str(config.rootfs))
    status = 'PASS' if all(c['state'] == 'SUPPORTED' or not c['mandatory'] for c in checks) else 'FAIL'
    return {'status': status, 'host': {'system': platform.system(),
            'release': platform.release(), 'machine': platform.machine()}, 'checks': checks}


def _available_memory_bytes():
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return 0


def _verify(config):
    result = {'profile': config.profile, 'workspace': str(config.workspace),
              'rootfs': str(config.rootfs), 'checks': {}}
    if not config.workspace.exists():
        result['checks']['workspace'] = {'state': 'MISSING', 'detail': 'run aaas setup'}
    else:
        try:
            sys.path.insert(0, str(ROOT / 'scripts'))
            import android_workspace
            result['checks']['workspace'] = {'state': 'PASS',
                'detail': android_workspace.check(config.workspace)}
        except Exception as error:
            result['checks']['workspace'] = {'state': 'FAIL', 'detail': str(error)}
    if config.rootfs.is_dir():
        try:
            result['checks']['image'] = aaas_profiles.inspect_rootfs(config.rootfs)
        except Exception as error:
            result['checks']['image'] = {'compatibility': 'FAIL', 'detail': str(error)}
    else:
        result['checks']['image'] = {'compatibility': 'MISSING',
                                     'detail': 'Android runtime image is not provisioned'}
    result['ready'] = (result['checks']['workspace'].get('state') == 'PASS'
                       and result['checks']['image'].get('compatibility') == 'MATCH'
                       and result['checks']['image'].get('provenance') == 'VERIFIED'
                       and result['checks']['image'].get('trust_classification') in
                       ('SECURITY_VALIDATED', 'DISTRIBUTABLE')
                       and result['checks']['image'].get('provisionable') is True
                       and result['checks']['image'].get('security', {}).get(
                           'enforcement') == 'VERIFIED')
    return result


def _save_config(config, workspace):
    target = config.config_file
    if target.exists():
        raise CliError(f'configuration already exists at {target}; setup will not overwrite it')
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = config.toml_defaults().replace(
        f'workspace = {json.dumps(str(config.workspace))}',
        f'workspace = {json.dumps(str(workspace))}')
    temporary = target.with_name(target.name + f'.{os.getpid()}.tmp')
    temporary.write_text(payload, encoding='utf-8')
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return target


def _parser():
    parser = argparse.ArgumentParser(prog='aaas', description=__doc__)
    parser.add_argument('--json', action='store_true', help='print machine-readable JSON')
    parser.add_argument('--version', action='version', version='AaaS developer runtime (repository build)')
    commands = parser.add_subparsers(dest='command')
    def json_flag(command):
        command.add_argument('--json', action='store_true', dest='json_local',
                             help='print machine-readable JSON')
        return command

    help_command = commands.add_parser('help', help='show command help')
    help_command.add_argument('topic', nargs='?')
    json_flag(commands.add_parser('doctor', help='diagnose host compatibility without downloads'))
    setup = commands.add_parser('setup', help='configure a workspace and inspect provisioning prerequisites')
    setup.add_argument('--workspace', type=Path)
    setup.add_argument('--adopt-existing', action='store_true')
    setup.add_argument('--install-command', action='store_true',
                       help='install a user-local ~/.local/bin/aaas symlink')
    for name in ('status', 'verify', 'start', 'stop', 'restart', 'logs', 'version'):
        sub = commands.add_parser(name)
        if name in ('status', 'verify', 'logs', 'version'):
            json_flag(sub)
        if name == 'start':
            sub.add_argument('--audio', action='store_true')
        if name == 'logs':
            sub.add_argument('--lines', type=int, default=100)
    apps = json_flag(commands.add_parser('apps', help='list and launch Android applications'))
    app_commands = apps.add_subparsers(dest='apps_command', required=True)
    app_commands.add_parser('list')
    launch = app_commands.add_parser('launch'); launch.add_argument('package')
    install = app_commands.add_parser('install'); install.add_argument('apk', type=Path)
    uninstall = app_commands.add_parser('uninstall'); uninstall.add_argument('package')
    images = json_flag(commands.add_parser('images', help='inspect supported Android profiles and images'))
    image_commands = images.add_subparsers(dest='images_command', required=True)
    image_commands.add_parser('list')
    inspect = image_commands.add_parser('inspect'); inspect.add_argument('path', type=Path)
    build = image_commands.add_parser('build', help='assemble a verified SDK image into an incomplete rootfs candidate')
    build.add_argument('profile')
    build.add_argument('--image', type=Path,
                       help='use an explicitly located copy of the profile image archive')
    build.add_argument('--dry-run', action='store_true',
                       help='check workspace capacity and print the assembly plan')
    debug = commands.add_parser('debug', help='run read-only runtime diagnostics')
    debug_commands = debug.add_subparsers(dest='debug_command', required=True)
    boot = debug_commands.add_parser(
        'boot', help='preflight a reconstructed candidate; never launches Android')
    boot.add_argument('--candidate', type=Path, required=True)
    json_flag(boot)
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == 'help':
        if args.topic is None:
            parser.print_help()
        else:
            action = next(item for item in parser._actions
                          if isinstance(item, argparse._SubParsersAction))
            target = action.choices.get(args.topic)
            if target is None:
                parser.error(f'unknown help topic: {args.topic}')
            target.print_help()
        return 0
    try:
        cli = {}
        if args.command == 'setup' and args.workspace:
            cli['workspace'] = str(args.workspace.expanduser().absolute())
        config = aaas_config.resolve_config(repository=ROOT, cli=cli)
        json_output = getattr(args, 'json', False) or getattr(args, 'json_local', False)
        if args.command == 'doctor':
            result = _doctor(config)
            _emit(result if json_output else '\n'.join(
                f"{item['state']:24} {item['name']}: {item['detail']}"
                for item in result['checks']), json_output)
            return 0 if result['status'] == 'PASS' else 2
        if args.command == 'setup':
            workspace = config.workspace
            workspace.parent.mkdir(parents=True, exist_ok=True)
            import android_workspace
            marker = workspace / android_workspace.MARKER
            if marker.exists():
                enrolled = android_workspace.check(workspace)
            else:
                enrolled = android_workspace.initialize(
                    workspace, adopt=args.adopt_existing)
            conf_path = (config.config_file if config.config_file.exists()
                         else _save_config(config, workspace))
            verify = _verify(config)
            if args.install_command:
                bindir = aaas_config.xdg_paths()['home'] / '.local/bin'
                bindir.mkdir(parents=True, exist_ok=True)
                link = bindir / 'aaas'
                target = ROOT / 'aaas'
                if link.is_symlink() and link.resolve() == target.resolve():
                    pass
                elif link.exists() or link.is_symlink():
                    raise CliError(f'refusing to replace existing command: {link}')
                else:
                    link.symlink_to(target)
            result = {'workspace': enrolled, 'config': str(conf_path),
                      'installation_ready': verify['ready'], 'verification': verify,
                      'provisioning': 'BLOCKED' if not verify['ready'] else 'READY'}
            _emit(result, json_output)
            if not verify['ready']:
                print('aaas setup: workspace is configured, but no automatically provisionable '
                      'Android runtime is available; see the image profile provisioning note.',
                      file=sys.stderr)
                return 2
            return 0
        if args.command == 'status':
            _emit(_status(config), json_output); return 0
        if args.command == 'verify':
            result = _verify(config); _emit(result, json_output); return 0 if result['ready'] else 2
        if args.command == 'version':
            result = {'version': 'repository build', 'revision': _revision(),
                      'profile': config.profile, 'workspace': str(config.workspace)}
            _emit(result, json_output); return 0
        if args.command == 'images':
            if args.images_command == 'list':
                _emit(list(aaas_profiles.profiles().values()), json_output); return 0
            if args.images_command == 'build':
                command = ['--workspace', config.workspace, '--profile', args.profile]
                if args.image:
                    command.extend(('--image', args.image.expanduser().absolute()))
                if args.dry_run:
                    command.append('--dry-run')
                return _run_script('assemble_android_rootfs.py', *command,
                                   config=config)
            path = args.path
            is_rootfs = path.is_dir()
            result = (aaas_profiles.inspect_rootfs(path) if is_rootfs
                      else aaas_profiles.inspect_archive(path))
            _emit(result, json_output)
            if is_rootfs:
                return 0 if (result['compatibility'] == 'MATCH'
                             and result['provenance'] == 'VERIFIED'
                             and result['provisionable']
                             and result.get('security', {}).get(
                                 'enforcement') == 'VERIFIED') else 2
            return 0 if (result.get('declared_match')
                         and result.get('runtime_compatibility') == 'VERIFIED') else 2
        if args.command == 'debug' and args.debug_command == 'boot':
            import aaas_boot
            result = aaas_boot.inspect_candidate(args.candidate, config.workspace)
            _emit(result, json_output)
            return 0 if result['outcome'] == 'PREFLIGHT_ONLY' else 2
        if args.command == 'apps':
            if args.apps_command == 'list':
                return _run_script('aaas_desktop.py', 'catalog', 'list', config=config)
            if args.apps_command == 'launch':
                return _run_script('aaas_desktop.py', 'launch', '--package', args.package,
                                   config=config)
            if args.apps_command == 'install':
                apk = args.apk.expanduser().resolve(strict=True)
                if not apk.is_file() or apk.is_symlink() or apk.suffix.lower() != '.apk':
                    raise CliError('apps install requires a regular .apk file')
                verification = _verify(config)
                if not verification['ready']:
                    _emit(verification, True)
                    raise CliError('runtime artifacts are missing, unverified, or not reproducible')
                return _run_script('run_aaas.py', '--install-apk', apk,
                                   '--app', 'com.android.settings', config=config)
            package = args.package
            if not package.startswith('org.aaas.'):
                raise CliError('safe uninstall is currently limited to controlled org.aaas packages')
            verification = _verify(config)
            if not verification['ready']:
                _emit(verification, True)
                raise CliError('runtime artifacts are missing, unverified, or not reproducible')
            return _run_script('run_aaas.py', '--uninstall-package', package,
                               '--app', 'com.android.settings', config=config)
        if args.command == 'logs':
            if not 1 <= args.lines <= 10000:
                raise CliError('--lines must be between 1 and 10000')
            sessions = sorted((config.workspace / 'tmp').glob('m1b84_session_*'),
                              key=lambda p: p.stat().st_mtime, reverse=True)
            if not sessions:
                raise CliError('no AaaS session logs found')
            logs = sessions[0] / 'android.log'
            print(''.join(logs.read_text(errors='replace').splitlines(keepends=True)[-args.lines:]),
                  end='')
            return 0
        if args.command == 'stop':
            return _run_script('aaasctl.py', 'stop', config=config)
        if args.command in ('start', 'restart'):
            if args.command == 'restart':
                _run_script('aaasctl.py', 'stop', config=config, check=False)
                time.sleep(.5)
            verification = _verify(config)
            if not verification['ready']:
                _emit(verification, True)
                raise CliError('runtime artifacts are missing, unverified, or not reproducible')
            command = ['--idle-timeout-seconds', config.idle_timeout_seconds,
                       '--app', 'com.android.settings']
            if config.resource_limit:
                command.extend(('--memory-policy', config.resource_limit))
            if config.audio or getattr(args, 'audio', False):
                command.append('--audio')
            return _run_script('run_aaas.py', *command, config=config)
    except (aaas_config.ConfigurationError, aaas_profiles.ProfileError,
            CliError, OSError, RuntimeError, ValueError) as error:
        print(f'aaas: {error}', file=sys.stderr)
        return 2
    parser.error(f'unsupported command: {args.command}')


def _revision():
    try:
        return subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'],
                              capture_output=True, text=True, check=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


if __name__ == '__main__':
    raise SystemExit(main())
