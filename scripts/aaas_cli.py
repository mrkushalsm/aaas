#!/usr/bin/env python3
"""Unified user-facing AaaS developer runtime command."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import platform
import signal
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import aaas_config
import aaas_profiles
import aaas_bundle
import aaas_graphics
import aaas_dev
import aaas_portable_installer


class CliError(RuntimeError):
    pass


def _emit(value, as_json=False):
    if as_json or isinstance(value, (dict, list)):
        print(json.dumps(value, indent=2, sort_keys=True, default=str))
    else:
        print(value)


def _run_script(script, *args, config=None, check=True, env_extra=None):
    config = config or aaas_config.resolve_config(repository=ROOT)
    env = dict(os.environ)
    env.update(AAAS_WORKSPACE=str(config.workspace), AAAS_ROOTFS=str(config.rootfs),
               AAAS_PROFILE=config.profile,
               AAAS_HELPER_KEYSTORE=str(config.state / 'signing/storage-probe.keystore'),
               AAAS_IDLE_TIMEOUT_SECONDS=str(config.idle_timeout_seconds),
               AAAS_AUDIO='1' if config.audio else '0',
               PYTHONPATH=str(ROOT / 'scripts') + os.pathsep + env.get('PYTHONPATH', ''))
    if env_extra:
        env.update(env_extra)
    process = subprocess.Popen(
        [sys.executable, str(ROOT / 'scripts' / script), *map(str, args)],
        env=env, start_new_session=True)
    try:
        returncode = process.wait()
    except KeyboardInterrupt:
        # run_aaas owns the Android namespace and presenter children. Signal
        # their process group so an interrupted foreground launch cannot leave
        # init or the Wayland presenter running after its controller exits.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        return 130
    if check and returncode:
        raise CliError(f'{script} exited with status {returncode}')
    return returncode


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
    try:
        render_node = str(aaas_graphics.discover_render_node())
        render_state = 'SUPPORTED'
    except aaas_graphics.GraphicsDeviceError as error:
        render_node = str(error)
        render_state = 'MISSING_DEPENDENCY'
    add('drm_render_node', render_state, render_node)
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
    update = commands.add_parser('update', help='stage and verify a portable runtime update')
    update.add_argument('bundle', type=Path)
    rollback = commands.add_parser('rollback', help='restore the previous verified runtime bundle')
    uninstall = commands.add_parser('uninstall', help='remove AaaS binaries while preserving user data')
    uninstall.add_argument('--remove-user-data', action='store_true',
                           help='also remove the enrolled workspace and Android userdata')
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
    app_list = app_commands.add_parser('list')
    app_list.add_argument('--refresh', action='store_true',
                          help='query Android and update desktop entries and icons')
    launch = app_commands.add_parser('launch'); launch.add_argument('package')
    app_commands.add_parser('running', help='show currently running Android app windows')
    close_app = app_commands.add_parser('close', help='close one running app window by slot')
    close_app.add_argument('slot', type=int)
    install = app_commands.add_parser('install'); install.add_argument('apk', type=Path)
    uninstall = app_commands.add_parser('uninstall'); uninstall.add_argument('package')
    runtime = json_flag(commands.add_parser('runtime', help='manage the persistent user runtime'))
    runtime_commands = runtime.add_subparsers(dest='runtime_command', required=True)
    json_flag(runtime_commands.add_parser('install-service',
                                         help='install the systemd user service'))
    json_flag(runtime_commands.add_parser('start', help='start Android as a persistent user service'))
    json_flag(runtime_commands.add_parser('status', help='show persistent runtime readiness'))
    json_flag(runtime_commands.add_parser('stop', help='stop the persistent user service'))
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
    bundle = json_flag(commands.add_parser('bundle', help='create and install restricted local development bundles'))
    bundle_commands = bundle.add_subparsers(dest='bundle_command', required=True)
    create_bundle = bundle_commands.add_parser('create', help='copy the current diagnostic runtime into a local bundle')
    create_bundle.add_argument('--profile', default=aaas_bundle.PROFILE)
    create_bundle.add_argument('--local-development', action='store_true', required=True,
                               help='acknowledge this bundle is diagnostic-only and security-unapproved')
    create_bundle.add_argument('--output', type=Path)
    inspect_bundle = bundle_commands.add_parser('inspect', help='show bundle profile and trust status')
    inspect_bundle.add_argument('path', type=Path)
    verify_bundle = bundle_commands.add_parser('verify', help='verify every bundle entry and SHA-256')
    verify_bundle.add_argument('path', type=Path)
    install_bundle = bundle_commands.add_parser('install', help='install a verified bundle into new isolated paths')
    install_bundle.add_argument('path', type=Path)
    install_bundle.add_argument('--workspace', type=Path, required=True)
    install_bundle.add_argument('--installation', type=Path, required=True)
    install_bundle.add_argument('--config-home', type=Path)
    install_bundle.add_argument('--data-home', type=Path)
    json_flag(create_bundle); json_flag(inspect_bundle); json_flag(verify_bundle)
    json_flag(install_bundle)
    dev = commands.add_parser('dev', help='explicitly run the historical M4 diagnostic profile')
    dev_commands = dev.add_subparsers(dest='dev_command', required=True)
    for name in ('setup', 'verify', 'status', 'stop'):
        json_flag(dev_commands.add_parser(name))
    dev_start = json_flag(dev_commands.add_parser('start'))
    dev_start.add_argument('--audio', action='store_true')
    dev_start.add_argument('--app', action='append', default=[],
                           help='Android package to launch; may be repeated')
    dev_start.add_argument('--app2',
                           help='launch a second Android app in an independent window')
    dev_start.add_argument('--idle-timeout-seconds', type=int,
                           help='override the configured idle shutdown for this session')
    dev_start.add_argument('--max-apps', type=int, default=16,
                           help='maximum simultaneous Android windows (default: 16)')
    dev_install = json_flag(dev_commands.add_parser(
        'install', help='install a local APK in the restricted headless development runtime'))
    dev_install.add_argument('apk', type=Path)
    dev_storage = dev_commands.add_parser(
        'storage', help='run shared-storage verification without host display presentation')
    dev_storage_commands = dev_storage.add_subparsers(dest='storage_command', required=True)
    json_flag(dev_storage_commands.add_parser('verify'))
    json_flag(dev_storage_commands.add_parser('start'))
    dev_logs = json_flag(dev_commands.add_parser('logs'))
    dev_logs.add_argument('--lines', type=int, default=100)
    return parser


def _runtime_unit_path(config=None):
    # systemd's unit search path is fixed when the user manager starts. A
    # profile-specific XDG_CONFIG_HOME on the CLI must not redirect the unit
    # into a directory the manager does not search.
    try:
        clean_env = dict(os.environ)
        clean_env.pop('XDG_CONFIG_HOME', None)
        result = subprocess.run(['systemd-path', 'user-configuration'],
                                env=clean_env, capture_output=True, text=True,
                                timeout=3)
        config_home = Path(result.stdout.strip()) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        config_home = None
    if not config_home or not config_home.is_absolute():
        config_home = Path.home() / '.config'
    service_name = os.environ.get('AAAS_RUNTIME_SERVICE', 'aaas-runtime.service')
    if (not service_name.endswith('.service') or '/' in service_name or
            not all(character.isalnum() or character in '_.@-' for character in service_name)):
        raise CliError('AAAS_RUNTIME_SERVICE must be a valid user service unit name')
    return config_home / 'systemd/user' / service_name


def _runtime_systemctl(*args, check=True):
    result = subprocess.run(['systemctl', '--user', *args], text=True,
                            capture_output=True, timeout=30)
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise CliError(f"systemctl --user {' '.join(args)} failed: {detail}")
    return result


def _installed_root(config):
    root = config.rootfs.parent
    if root.is_symlink() or not (root / 'installation.json').is_file():
        raise CliError('this command requires a verified portable bundle installation')
    try:
        report = aaas_bundle.verify_installation(root)
    except Exception as error:
        raise CliError(f'installed runtime integrity verification failed: {error}') from error
    if report.get('integrity') != 'PASS':
        raise CliError('installed runtime integrity verification failed')
    return root


def _release_state_path(config):
    return config.state / 'release-lifecycle.json'


def _write_installation_record(config, root, *, bundle_id=None):
    path = config.installation_manifest
    path.parent.mkdir(parents=True, exist_ok=True)
    record = json.loads((root / 'installation.json').read_text(encoding='utf-8'))
    record['paths'] = dict(record.get('paths', {}))
    record['paths'].update({'rootfs': str(root / 'rootfs'),
                            'runtime': str(root / 'runtime'),
                            'workspace': str(config.workspace),
                            'workspace_artifacts': str(root / 'workspace-artifacts')})
    if bundle_id:
        record['bundle_id'] = bundle_id
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _save_release_state(config, previous):
    path = _release_state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps({'schema': 1, 'previous': str(previous)},
                                    sort_keys=True) + '\n', encoding='utf-8')
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _runtime_import_desktop_environment():
    names = ('WAYLAND_DISPLAY', 'DISPLAY', 'XDG_RUNTIME_DIR',
             'DBUS_SESSION_BUS_ADDRESS', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME',
             'XDG_CACHE_HOME', 'XDG_STATE_HOME')
    present = [name for name in names if os.environ.get(name)]
    if present:
        _runtime_systemctl('import-environment', *present)


def _runtime_windows_are_idle(windows):
    return all(item.get('state') == 'CLOSED' and
               item.get('presenter_pid') is None and
               item.get('display_id') is None for item in windows)


def _install_runtime_service(config):
    unit = _runtime_unit_path(config)
    unit.parent.mkdir(parents=True, exist_ok=True)
    if unit.exists() and not unit.is_symlink():
        backup = unit.with_name(unit.name + '.aaas-backup')
        if not backup.exists():
            shutil.copy2(unit, backup)
    script = ROOT / 'scripts/aaas_runtime_service.py'
    python = Path(sys.executable).resolve()
    xdg = aaas_config.xdg_paths()

    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'

    content = ('[Unit]\nDescription=AaaS persistent Android runtime\n'
               'After=graphical-session.target\nPartOf=graphical-session.target\n'
               'StartLimitIntervalSec=60\nStartLimitBurst=3\n\n'
               '[Service]\nType=simple\n'
               f'ExecStart={quote(python)} {quote(script)} run\n'
               'Environment=AAAS_DEV_COMPAT=1\n'
               f'Environment=AAAS_WORKSPACE={quote(config.workspace)}\n'
               f'Environment=AAAS_ROOTFS={quote(config.rootfs)}\n'
               f'Environment=AAAS_RUNTIME_ROOT={quote(ROOT)}\n'
               f'Environment=AAAS_HELPER_KEYSTORE={quote(config.state / "signing/storage-probe.keystore")}\n'
               f'Environment=XDG_CONFIG_HOME={quote(xdg["config_home"])}\n'
               f'Environment=XDG_DATA_HOME={quote(xdg["data_home"])}\n'
               f'Environment=XDG_CACHE_HOME={quote(xdg["cache_home"].parent)}\n'
               f'Environment=XDG_STATE_HOME={quote(xdg["state_home"].parent)}\n'
               f'Environment=AAAS_DESKTOP_DATA_HOME={quote(os.environ.get("AAAS_DESKTOP_DATA_HOME", str(xdg["data_home"]))) }\n'
               f'Environment=AAAS_LAUNCHER_PATH={quote(str(ROOT.parent / "bin/aaas"))}\n'
               'Environment=AAAS_AUDIO=' + ('1' if config.audio else '0') + '\n'
               'PassEnvironment=WAYLAND_DISPLAY DISPLAY XDG_RUNTIME_DIR '
               'DBUS_SESSION_BUS_ADDRESS XDG_CONFIG_HOME XDG_DATA_HOME '
               'XDG_CACHE_HOME XDG_STATE_HOME\n'
               'Restart=on-failure\nRestartSec=10s\nTimeoutStartSec=250s\n'
               'TimeoutStopSec=45s\nKillMode=mixed\n\n'
               '[Install]\nWantedBy=default.target\n')
    native_bridge_bundle = config.workspace / 'tmp/m3_native_bridge/digitalis'
    if (not native_bridge_bundle.is_symlink() and
            (native_bridge_bundle / 'SHA256SUMS').is_file()):
        content = content.replace(
            'Environment=AAAS_DEV_COMPAT=1\n',
            'Environment=AAAS_DEV_COMPAT=1\n'
            f'Environment=AAAS_NATIVE_BRIDGE_BUNDLE={quote(native_bridge_bundle)}\n',
            1)
    temporary = unit.with_suffix('.service.tmp')
    temporary.write_text(content, encoding='utf-8')
    temporary.chmod(0o600)
    os.replace(temporary, unit)
    _runtime_systemctl('daemon-reload')
    return unit


def _runtime_start(config):
    service_name = _runtime_unit_path(config).name
    if not _runtime_unit_path(config).is_file():
        _install_runtime_service(config)
    _runtime_import_desktop_environment()
    _runtime_systemctl('start', service_name)
    deadline = time.monotonic() + 250
    while time.monotonic() < deadline:
        if _status(config)['runtime']['state'] == 'RUNNING':
            try:
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'scripts/aaasctl.py'), 'list'],
                    env={**os.environ, 'AAAS_WORKSPACE': str(config.workspace)},
                    capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    parsed = json.loads(result.stdout)
                    windows = parsed.get('windows', [])
                    if (parsed.get('state') == 'RUNNING' and
                            _runtime_windows_are_idle(windows)):
                        return parsed
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        active = _runtime_systemctl('is-active', service_name, check=False)
        if active.returncode:
            raise CliError('AaaS service stopped before Android became ready; inspect '
                           f'`journalctl --user -u {service_name}`')
        time.sleep(.5)
    raise CliError('AaaS user service did not report readiness within 250 seconds')


def _refresh_installed_catalog(config):
    result = _run_script('aaas_desktop.py', 'catalog', 'refresh',
                         config=config, check=False)
    if result:
        print('AaaS: Android is ready; application-menu refresh failed. '
              'Retry with `aaas apps list --refresh`.', file=sys.stderr)


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
        if args.command == 'update':
            root = _installed_root(config)
            candidate = aaas_bundle.verify_bundle(args.bundle)
            stage = aaas_bundle.stage_installation_update(
                bundle=args.bundle, installation=root)
            try:
                _runtime_systemctl('stop', _runtime_unit_path(config).name, check=False)
                previous = aaas_bundle.activate_staged_update(stage=stage,
                                                              installation=root)
                _write_installation_record(config, root, bundle_id=candidate['bundle_id'])
                try:
                    ready = _runtime_start(config)
                except Exception:
                    _runtime_systemctl('stop', _runtime_unit_path(config).name, check=False)
                    failed = aaas_bundle.restore_previous_installation(
                        installation=root, previous=previous)
                    _write_installation_record(config, root)
                    _save_release_state(config, failed)
                    try:
                        _runtime_start(config)
                    except Exception as recovery_error:
                        raise CliError('update failed and previous release was restored, '
                                       f'but its service did not recover: {recovery_error}')
                    raise
                _save_release_state(config, previous)
                _refresh_installed_catalog(config)
                _emit({'updated': True, 'bundle_id': candidate['bundle_id'],
                       'installation': str(root), 'previous_release': str(previous),
                       'runtime': ready.get('state', 'RUNNING')}, json_output)
                return 0
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        if args.command == 'rollback':
            root = _installed_root(config)
            state_path = _release_state_path(config)
            try:
                previous = Path(json.loads(state_path.read_text(encoding='utf-8'))['previous'])
            except (OSError, KeyError, json.JSONDecodeError) as error:
                raise CliError('no recorded previous release is available for rollback') from error
            if previous.parent.resolve() != root.parent.resolve() or not previous.name.startswith(
                    f'.{root.name}.'):
                raise CliError('rollback metadata points outside the installation release family')
            _runtime_systemctl('stop', _runtime_unit_path(config).name, check=False)
            failed = aaas_bundle.restore_previous_installation(
                installation=root, previous=previous)
            _write_installation_record(config, root)
            _save_release_state(config, failed)
            try:
                ready = _runtime_start(config)
            except Exception as error:
                _runtime_systemctl('stop', _runtime_unit_path(config).name, check=False)
                restored = aaas_bundle.restore_previous_installation(
                    installation=root, previous=failed)
                _write_installation_record(config, root)
                _save_release_state(config, restored)
                raise CliError(f'rollback failed to start; the prior running release was '
                               f'restored: {error}') from error
            _refresh_installed_catalog(config)
            _emit({'rolled_back': True, 'installation': str(root),
                   'retained_release': str(failed), 'runtime': ready.get('state', 'RUNNING')},
                  json_output)
            return 0
        if args.command == 'uninstall':
            root = _installed_root(config)
            workspace_removal = False
            if args.remove_user_data:
                import android_workspace
                import aaas_userdata
                check = android_workspace.check(config.workspace)
                if check.get('health') not in ('HEALTHY', 'HEALTHY_FOR_CONTROLLED_TESTING'):
                    raise CliError('preserving the workspace: enrolled health check failed')
                aaas_userdata.prepare_userdata_directory(config.workspace)
                workspace_removal = True
            service_unit = _runtime_unit_path(config)
            _runtime_systemctl('stop', service_unit.name, check=False)
            backups = (*root.parent.glob(f'.{root.name}.previous-*'),
                       *root.parent.glob(f'.{root.name}.rolled-back-*'))
            for candidate in backups:
                try:
                    aaas_bundle.verify_installation(candidate)
                except Exception as error:
                    raise CliError(
                        f'refusing to remove unverified previous release {candidate}: {error}')
                aaas_portable_installer.clear_android_rootfs_for_uninstall(candidate)
            aaas_portable_installer.clear_android_rootfs_for_uninstall(root)
            if service_unit.exists():
                contents = service_unit.read_text(encoding='utf-8', errors='replace')
                if ('Description=AaaS persistent Android runtime' not in contents or
                        f'Environment=AAAS_WORKSPACE="{config.workspace}"' not in contents or
                        f'Environment=AAAS_ROOTFS="{config.rootfs}"' not in contents):
                    raise CliError(f'refusing to remove unowned service unit: {service_unit}')
                service_unit.unlink()
                backup = service_unit.with_name(service_unit.name + '.aaas-backup')
                if backup.is_file():
                    os.replace(backup, service_unit)
                _runtime_systemctl('daemon-reload')
            alias = Path.home() / '.local/bin/aaas-portable'
            if alias.is_symlink():
                try:
                    alias.resolve(strict=False).relative_to(root)
                except ValueError:
                    pass
                else:
                    alias.unlink()
            app_dir = config.runtime_data.parent / 'applications'
            for entry in app_dir.glob('aaas-*.desktop') if app_dir.is_dir() else ():
                try:
                    content = entry.read_text(encoding='utf-8')
                except OSError:
                    continue
                if 'X-AaaS-Package=' in content and 'Exec=' in content:
                    entry.unlink()
            for backup in backups:
                shutil.rmtree(backup)
            shutil.rmtree(root)
            config.installation_manifest.unlink(missing_ok=True)
            _release_state_path(config).unlink(missing_ok=True)
            if workspace_removal:
                shutil.rmtree(config.workspace / 'android-userdata')
            _emit({'uninstalled': True, 'installation_removed': str(root),
                   'workspace_preserved': True,
                   'userdata_removed': workspace_removal}, json_output)
            return 0
        if args.command == 'runtime':
            if args.runtime_command == 'install-service':
                path = _install_runtime_service(config)
                _emit({'unit': str(path), 'installed': True,
                       'security_warning': 'Android SELinux enforcement unavailable; '
                                           'local trusted development only'}, json_output)
                return 0
            if args.runtime_command == 'start':
                result = _runtime_start(config)
                _refresh_installed_catalog(config)
                _emit({'service': _runtime_unit_path(config).name, 'state': 'RUNNING',
                       'windows': result.get('windows', [])}, json_output)
                return 0
            if args.runtime_command == 'status':
                service = _runtime_systemctl('show', _runtime_unit_path(config).name,
                                             '--property=ActiveState,SubState,MainPID',
                                             check=False)
                _emit({'service': service.stdout.strip() if service.returncode == 0 else 'not-installed',
                       **_status(config)}, json_output)
                return 0
            if _runtime_unit_path(config).is_file():
                _runtime_systemctl('stop', _runtime_unit_path(config).name, check=False)
            else:
                _run_script('aaasctl.py', 'stop', config=config, check=False)
            return 0
        if args.command == 'dev':
            if (args.dev_command == 'start' and args.idle_timeout_seconds is not None
                    and not 1 <= args.idle_timeout_seconds <= 3600):
                raise CliError('--idle-timeout-seconds must be from 1 to 3600')
            if args.dev_command == 'storage':
                if args.storage_command == 'verify':
                    result = aaas_dev.verify_storage(config)
                    _emit(result, json_output)
                    return 0 if result['headless_storage_launch'] == 'PERMITTED' else 2
                result = aaas_dev.verify_storage(config)
                if result['headless_storage_launch'] != 'PERMITTED':
                    _emit(result, True)
                    raise CliError('headless storage prerequisites are incomplete; no session started')
                print('AaaS headless Android storage session', flush=True)
                print('Host Wayland presenter: disabled', flush=True)
                print('Android SELinux enforcement: unavailable', flush=True)
                print('Runtime security approval: not granted', flush=True)
                return _run_script(
                    'run_aaas.py', '--headless-storage', '--startup-timeout', '180',
                    '--idle-timeout-seconds', config.idle_timeout_seconds,
                    '--app', 'com.android.settings', config=config,
                    env_extra={'AAAS_DEV_COMPAT': '1', 'AAAS_HEADLESS_STORAGE': '1',
                               'AAAS_RUNTIME_ROOT': str(aaas_dev.runtime_root(config))})
            if args.dev_command == 'setup':
                enrolled = aaas_dev.enroll_owned_installation(config)
                key = aaas_dev.ensure_signing_key(
                    config.state, config.workspace / 'tmp/m4-storage-probe/storage-probe.keystore')
                _emit({'development_profile': 'DIAGNOSTIC_LEGACY',
                       'workspace_enrollment': enrolled,
                       'signing_key': str(key),
                       'key_mode': oct(key.stat().st_mode & 0o777),
                       'runtime_security': 'NOT_APPROVED',
                       'production_launch': 'BLOCKED'}, json_output)
                return 0
            if args.dev_command == 'verify':
                result = aaas_dev.verify(config)
                _emit(result, json_output)
                return 0 if result['development_launch'] == 'PERMITTED' else 2
            if args.dev_command == 'status':
                result = _status(config)
                result.update({'development_profile': 'DIAGNOSTIC_LEGACY',
                               'runtime_security': 'NOT_APPROVED',
                               'selinux_enforcement': 'UNAVAILABLE'})
                _emit(result, json_output)
                return 0
            if args.dev_command == 'install':
                apk_arg = args.apk.expanduser()
                if apk_arg.is_symlink():
                    raise CliError('developer APK install refuses a symbolic link')
                apk = apk_arg.resolve(strict=True)
                if not apk.is_file() or apk.suffix.lower() != '.apk':
                    raise CliError('developer install requires a readable regular .apk file')
                if not os.access(apk, os.R_OK):
                    raise CliError('developer APK is not readable')
                if _status(config)['runtime']['state'] != 'STOPPED':
                    raise CliError('developer APK installation requires a stopped AaaS session')
                result = aaas_dev.verify_storage(config)
                if result['headless_storage_launch'] != 'PERMITTED':
                    _emit(result, True)
                    raise CliError('headless developer runtime prerequisites are incomplete')
                print('Installing local APK in the restricted headless development profile',
                      flush=True)
                print('Android SELinux enforcement: unavailable; security approval not granted',
                      flush=True)
                print('Only trusted development APKs are supported', flush=True)
                install_status = _run_script(
                    'run_aaas.py', '--headless-storage', '--install-apk', apk,
                    '--startup-timeout', '180', '--idle-timeout-seconds',
                    config.idle_timeout_seconds, '--app', 'com.android.settings',
                    config=config,
                    env_extra={'AAAS_DEV_COMPAT': '1', 'AAAS_HEADLESS_STORAGE': '1',
                               'AAAS_RUNTIME_ROOT': str(aaas_dev.runtime_root(config))})
                if install_status == 0:
                    catalog_status = _run_script('aaas_desktop.py', 'catalog', 'refresh',
                                                 config=config, check=False)
                    if catalog_status:
                        print('APK installed, but desktop catalog refresh failed; '
                              'run `aaas apps list --refresh` after the next Android start.',
                              file=sys.stderr)
                return install_status
            if args.dev_command == 'logs':
                if not 1 <= args.lines <= 10000:
                    raise CliError('--lines must be between 1 and 10000')
                sessions = sorted((p for p in (config.workspace / 'tmp').glob(
                                      'm1b84_session_*') if p.is_dir() and
                                   (p / 'android.log').is_file()),
                                  key=lambda p: p.stat().st_mtime, reverse=True)
                if not sessions:
                    raise CliError('no AaaS developer session logs found')
                logs = sessions[0] / 'android.log'
                print(''.join(logs.read_text(errors='replace').splitlines(keepends=True)[-args.lines:]),
                      end='')
                return 0
            if args.dev_command == 'stop':
                return _run_script('aaasctl.py', 'stop', config=config,
                                   env_extra={'AAAS_DEV_COMPAT': '1'})
            result = aaas_dev.verify(config)
            if result['development_launch'] != 'PERMITTED':
                _emit(result, True)
                raise CliError('developer runtime prerequisites are incomplete; no session started')
            print('AaaS development compatibility runtime', flush=True)
            print('Android SELinux enforcement: unavailable', flush=True)
            print('Legacy compatibility shim: enabled', flush=True)
            print('Runtime security approval: not granted', flush=True)
            print('Only trusted development workloads are supported', flush=True)
            selected_apps = args.app or ['com.android.settings']
            command = ['--startup-timeout', '120', '--idle-timeout-seconds',
                       str(args.idle_timeout_seconds or config.idle_timeout_seconds),
                       '--max-apps', str(args.max_apps),
                       '--experimental-virtual-display',
                       '--app', selected_apps[0]]
            if len(selected_apps) > 1:
                command.extend(('--app2', selected_apps[1]))
            for package in selected_apps[2:]:
                command.extend(('--app-extra', package))
            if args.app2:
                if len(selected_apps) > 1:
                    raise CliError('use repeated --app or --app2, not both')
                command.extend(('--app2', args.app2))
            if config.resource_limit:
                command.extend(('--memory-policy', config.resource_limit))
            if args.audio:
                command.append('--audio')
            return _run_script('run_aaas.py', *command, config=config,
                               env_extra={'AAAS_DEV_COMPAT': '1',
                                          'AAAS_IP': result['checks']['host']['ip'],
                                          'AAAS_RUNTIME_ROOT': str(
                                              aaas_dev.runtime_root(config))})
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
        if args.command == 'bundle':
            if args.bundle_command == 'create':
                if args.profile != aaas_bundle.PROFILE:
                    raise CliError(f'unsupported bundle profile: {args.profile}')
                workspace_info = __import__('android_workspace').check(config.workspace)
                output = (args.output.expanduser().absolute() if args.output else
                          config.workspace / 'bundles' / f'{aaas_bundle.PROFILE}-local-dev')
                try:
                    output.resolve(strict=False).relative_to(config.workspace.resolve())
                except ValueError as error:
                    raise CliError('bundle output must remain inside the enrolled workspace') from error
                if _status(config)['runtime']['state'] != 'STOPPED':
                    raise CliError('bundle creation requires all AaaS sessions to be stopped')
                result = aaas_bundle.create_bundle(
                    repo=ROOT, rootfs=config.workspace / 'rootfs_m1b1', output=output,
                    workspace=config.workspace,
                    preflight=lambda: __import__('android_workspace').check(config.workspace))
                verification = result['verification']
                summary = {'bundle': str(output), 'bundle_id': result['bundle_id'],
                           'profile': result['profile'],
                           'artifact_count': result['artifact_count'],
                           'bundle_bytes': sum(item.get('size', 0)
                                               for item in result['artifacts']),
                           'installation_integrity': 'PASS',
                           'runtime_closure': verification['runtime_closure'],
                           'runtime_security': 'NOT_APPROVED',
                           'general_runtime_start': 'BLOCKED',
                           'workspace_health': workspace_info['health']}
                _emit(summary, json_output)
                return 0
            if args.bundle_command == 'inspect':
                result = aaas_bundle.inspect_bundle(args.path)
                _emit({'bundle_id': result['bundle_id'], 'profile': result['profile'],
                       'classification': result['classification'],
                       'artifact_count': result['artifact_count'],
                       'authenticity': result['authenticity'],
                       'installation_integrity': result['installation_integrity'],
                       'runtime_closure': result['runtime_closure'],
                       'runtime_security': result['security']['runtime_security']}, json_output)
                return 0
            if args.bundle_command == 'verify':
                if (args.path / 'bundle-manifest.json').is_file():
                    result = aaas_bundle.verify_installation(args.path)
                else:
                    result = aaas_bundle.verify_bundle(args.path)
                _emit(result, json_output)
                return 0
            xdg = aaas_config.xdg_paths()
            result = aaas_bundle.install_bundle(
                bundle=args.path, workspace=args.workspace,
                install_root=args.installation,
                config_home=args.config_home or xdg['config_home'],
                data_home=args.data_home or xdg['data_home'],
                desktop_home=args.data_home or xdg['data_home'])
            # Provision the per-install helper key and user service as part of
            # installation. This key is private mutable workspace data and is
            # deliberately outside the signed/hashed immutable bundle.
            install_cli = Path(result['installation']) / 'bin/aaas'
            install_env = dict(os.environ)
            install_env.update({
                'XDG_CONFIG_HOME': str(args.config_home or xdg['config_home']),
                'XDG_DATA_HOME': str(args.data_home or xdg['data_home']),
                'XDG_CACHE_HOME': str(xdg['cache_home'].parent),
                'XDG_STATE_HOME': str(xdg['state_home'].parent),
                'AAAS_DESKTOP_DATA_HOME': str(args.data_home or xdg['data_home']),
                'AAAS_LAUNCHER_PATH': str(install_cli),
            })
            for override in ('AAAS_WORKSPACE', 'AAAS_ROOTFS',
                             'AAAS_RUNTIME_ROOT', 'AAAS_PROFILE'):
                install_env.pop(override, None)
            setup = subprocess.run([str(install_cli), 'dev', 'setup', '--json'],
                                   env=install_env, capture_output=True, text=True,
                                   timeout=60)
            if setup.returncode:
                raise CliError('installed development profile provisioning failed: ' +
                               (setup.stderr or setup.stdout).strip())
            # Do not replace another command. The versioned command remains
            # directly available under the installation even when this alias
            # is already owned by another package.
            command_link = Path.home() / '.local/bin/aaas-portable'
            command_link.parent.mkdir(parents=True, exist_ok=True)
            if not command_link.exists() and not command_link.is_symlink():
                command_link.symlink_to(install_cli)
            service = subprocess.run([str(install_cli), 'runtime',
                                      'install-service', '--json'],
                                     env=install_env, capture_output=True, text=True,
                                     timeout=60)
            if service.returncode:
                raise CliError('installed systemd user service setup failed: ' +
                               (service.stderr or service.stdout).strip())
            result['development_profile_provisioning'] = 'PASS'
            result['user_service'] = json.loads(service.stdout)
            result['command'] = str(command_link if command_link.is_symlink()
                                    else install_cli)
            _emit(result, json_output)
            return 0
        if args.command == 'apps':
            if args.apps_command == 'list':
                if args.refresh:
                    return _run_script('aaas_desktop.py', 'catalog', 'refresh', config=config)
                return _run_script('aaas_desktop.py', 'catalog', 'list', config=config)
            if args.apps_command == 'running':
                return _run_script('aaasctl.py', 'list', config=config)
            if args.apps_command == 'close':
                return _run_script('aaasctl.py', 'close', args.slot, config=config)
            if args.apps_command == 'launch':
                if (_runtime_unit_path(config).is_file() and
                        _status(config)['runtime']['state'] == 'STOPPED'):
                    _runtime_start(config)
                return _run_script('aaas_desktop.py', 'launch', '--package', args.package,
                                   config=config)
            if args.apps_command == 'install':
                apk = args.apk.expanduser().absolute()
                if apk.is_symlink() or not apk.is_file() or apk.suffix.lower() != '.apk':
                    raise CliError('apps install requires a regular .apk file')
                print('WARNING: AaaS development runtime; Android SELinux enforcement is '
                      'unavailable. Install only APKs you trust.', file=sys.stderr)
                if (_runtime_unit_path(config).is_file() and
                        _status(config)['runtime']['state'] == 'STOPPED'):
                    _runtime_start(config)
                install_status = _run_script('aaasctl.py', 'install-apk', apk,
                                             config=config)
                if install_status == 0:
                    catalog_status = _run_script('aaas_desktop.py', 'catalog', 'refresh',
                                                 config=config, check=False)
                    if catalog_status:
                        print('APK installed, but desktop catalog refresh failed; '
                              'run `aaas apps list --refresh` after the next Android start.',
                              file=sys.stderr)
                return install_status
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
            sessions = sorted((p for p in (config.workspace / 'tmp').glob(
                                  'm1b84_session_*') if p.is_dir() and
                               (p / 'android.log').is_file()),
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
