"""Explicit, restricted execution policy for the historical M4 diagnostic image."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import platform

import aaas_bundle
import aaas_bwrap
import android_workspace

REQUIRED_ROOTFS_MOUNTPOINTS = ('linkerconfig', 'debug_ramdisk')
REQUIRED_HOST_TOOLS = ('bwrap', 'unshare', 'keytool', 'java', 'javac', 'make',
                       'clang++', 'setfacl', 'getfacl', 'ip', 'mount')


class DeveloperRuntimeError(RuntimeError):
    pass


def _read_installation(config):
    try:
        value = json.loads(config.installation_manifest.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise DeveloperRuntimeError(f'no valid local developer installation: {error}') from error
    if value.get('classification') != 'LOCAL_DEVELOPMENT_DIAGNOSTIC':
        raise DeveloperRuntimeError('selected installation is not a local diagnostic bundle')
    if Path(value.get('paths', {}).get('rootfs', '')).resolve() != config.rootfs.resolve():
        raise DeveloperRuntimeError('configured rootfs does not match installation metadata')
    return value


def runtime_root(config):
    """Return the selected installation's verified payload root."""
    record = _read_installation(config)
    runtime = Path(record['paths']['runtime']).resolve(strict=True)
    if not runtime.is_dir() or runtime.is_symlink():
        raise DeveloperRuntimeError('installed runtime payload root is missing or unsafe')
    return runtime


def enroll_owned_installation(config):
    """Enroll installer-staged files only after exact bundle payload comparison."""
    record = _read_installation(config)
    runtime = Path(record['paths']['runtime']).resolve(strict=True)
    install_root = runtime.parent
    result = aaas_bundle.enroll_installer_workspace(install_root, config.workspace)
    record['workspace_enrollment'] = 'PASS'
    record['workspace_id'] = result['workspace_id']
    record['userdata'] = 'fresh installation-local backing initialized'
    (install_root / 'installation.json').write_text(
        json.dumps(record, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary = config.installation_manifest.with_name(
        config.installation_manifest.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n',
                         encoding='utf-8')
    os.chmod(temporary, 0o600)
    os.replace(temporary, config.installation_manifest)
    return result


def ensure_signing_key(location: Path, legacy_key: Path | None = None):
    """Create or verify the per-install helper signer outside the release bundle.

    ``location`` is the installation's persistent XDG state directory.  Keeping
    this identity there preserves APK update compatibility across immutable
    runtime updates while keeping private material out of workspace artifacts.
    """
    key = location / 'signing/storage-probe.keystore'
    key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    def validate(candidate):
        if candidate.is_symlink():
            raise DeveloperRuntimeError('refusing symlinked development signing keystore')
        if candidate.exists():
            if (not candidate.is_file() or candidate.stat().st_uid != os.getuid()
                    or candidate.stat().st_mode & 0o077):
                raise DeveloperRuntimeError(
                    'development signing keystore has unsafe ownership or mode')
            check = subprocess.run(
                ['keytool', '-list', '-keystore', str(candidate), '-storepass', 'android',
                 '-alias', 'storage-probe'], capture_output=True, text=True, timeout=10)
            if check.returncode:
                raise DeveloperRuntimeError('existing development signing keystore is invalid')

    if not key.exists() and legacy_key is not None and Path(legacy_key).exists():
        legacy_key = Path(legacy_key)
        validate(legacy_key)
        temporary_copy = key.with_name(f'.{key.name}.{os.getpid()}.migrate')
        shutil.copy2(legacy_key, temporary_copy)
        os.chmod(temporary_copy, 0o600)
        os.replace(temporary_copy, key)
    if key.is_symlink():
        raise DeveloperRuntimeError('refusing symlinked development signing keystore')
    if key.exists():
        validate(key)
        return key
    temporary = key.with_name(f'.{key.name}.{os.getpid()}.tmp')
    try:
        subprocess.run([
            'keytool', '-genkeypair', '-noprompt', '-storetype', 'PKCS12',
            '-keystore', str(temporary), '-storepass', 'android', '-keypass', 'android',
            '-alias', 'storage-probe', '-keyalg', 'RSA', '-keysize', '2048',
            '-validity', '3650', '-dname', 'CN=AaaS Local Diagnostic Installation',
        ], capture_output=True, text=True, check=True, timeout=30)
        os.chmod(temporary, 0o600)
        os.replace(temporary, key)
    except (OSError, subprocess.SubprocessError) as error:
        temporary.unlink(missing_ok=True)
        raise DeveloperRuntimeError(f'cannot create installation-local signing key: {error}') from error
    return key


def _check_host(config, runtime_root):
    checks = {'operating_system': platform.system(),
              'architecture': platform.machine()}
    for tool in REQUIRED_HOST_TOOLS:
        if tool != 'bwrap':
            checks[tool] = shutil.which(tool)
    try:
        checks['bwrap'] = str(aaas_bwrap.resolve_bwrap(allow_trace_wrapper=False))
    except aaas_bwrap.BubblewrapError as error:
        checks['bwrap'] = None
        checks['bwrap_error'] = str(error)
    checks['wayland_display'] = os.environ.get('WAYLAND_DISPLAY')
    checks['desktop'] = os.environ.get('XDG_CURRENT_DESKTOP', '')
    checks['kwin'] = ('SUPPORTED' if 'KDE' in checks['desktop'].upper()
                      or shutil.which('kwin_wayland') else None)
    try:
        uid_range, gid_range = __import__('aaas_idmap').current_ranges()
        checks['subordinate_uid_range'] = [uid_range.start, uid_range.length]
        checks['subordinate_gid_range'] = [gid_range.start, gid_range.length]
    except Exception as error:
        checks['id_mapping_error'] = str(error)
    unshare = shutil.which('unshare')
    checks['user_namespace'] = False
    checks['binderfs'] = False
    if unshare:
        try:
            checks['user_namespace'] = subprocess.run(
                [unshare, '--user', '--map-root-user', 'true'],
                capture_output=True, timeout=5).returncode == 0
            probe = ('set -eu; d=$(mktemp -d); trap \'umount "$d" 2>/dev/null || true; '
                     'rmdir "$d"\' EXIT; mount -t binder binder "$d"; umount "$d"')
            checks['binderfs'] = subprocess.run(
                [unshare, '--user', '--map-root-user', '--mount', 'sh', '-c', probe],
                capture_output=True, timeout=8).returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
    bwrap = checks.get('bwrap')
    if bwrap:
        try:
            help_text = subprocess.run([bwrap, '--help'], capture_output=True,
                                       text=True, timeout=3).stdout
            checks['network_namespace_support'] = '--unshare-net' in help_text
        except (OSError, subprocess.SubprocessError):
            checks['network_namespace_support'] = False
    try:
        checks['drm_render_node'] = str(__import__('aaas_graphics').discover_render_node())
    except Exception as error:
        checks['drm_render_node_error'] = str(error)
    checks['runner'] = str(runtime_root / 'scripts/run_aaas.py')
    checks['presenter'] = str(runtime_root / 'experiments/m1a/build/wayland-host-presenter')
    return checks


def verify(config, *, check_runner=True):
    report = {
        'installation_integrity': 'FAIL', 'development_profile': 'DIAGNOSTIC_LEGACY',
        'development_runtime_dependencies': 'FAIL',
        'selinux_enforcement': 'UNAVAILABLE', 'known_selinux_shim': 'UNKNOWN',
        'runtime_security': 'NOT_APPROVED', 'production_launch': 'BLOCKED',
        'development_launch': 'BLOCKED', 'checks': {},
    }
    record = _read_installation(config)
    runtime_root = Path(record['paths']['runtime']).resolve(strict=True)
    if not runtime_root.is_dir() or runtime_root.is_symlink():
        raise DeveloperRuntimeError('installed runtime payload root is missing or unsafe')
    install_root = runtime_root.parent
    integrity = aaas_bundle.verify_installation(install_root)
    report['checks']['bundle'] = integrity
    report['installation_integrity'] = 'PASS'
    manifest = json.loads((install_root / 'bundle-manifest.json').read_text(encoding='utf-8'))
    expected = {item['path']: item for item in manifest['artifacts']}
    shim_paths = ('rootfs/system/lib64/libselinux_shim.so',
                  'rootfs/vendor/lib64/libselinux_shim.so')
    shim_results = {}
    for relative in shim_paths:
        path = install_root / relative
        entry = expected.get(relative)
        shim_results[relative] = bool(path.is_file() and entry and
                                      hashlib.sha256(path.read_bytes()).hexdigest() == entry.get('sha256'))
    init_rc = config.rootfs / 'system/etc/init/servicemanager.rc'
    preload = init_rc.is_file() and '/system/lib64/libselinux_shim.so' in init_rc.read_text(
        encoding='utf-8', errors='replace')
    report['checks']['legacy_shims'] = {'files': shim_results, 'preload_configured': preload}
    report['known_selinux_shim'] = 'PRESENT' if all(shim_results.values()) and preload else 'INVALID'
    mountpoints = {}
    for name in REQUIRED_ROOTFS_MOUNTPOINTS:
        path = config.rootfs / name
        mountpoints[name] = path.is_dir() and not path.is_symlink()
    report['checks']['rootfs_mountpoints'] = mountpoints
    report['checks']['host'] = _check_host(config, runtime_root)
    try:
        workspace_check = android_workspace.check(config.workspace)
        report['checks']['workspace'] = workspace_check
    except Exception as error:
        report['checks']['workspace'] = {'state': 'FAIL', 'detail': str(error)}
    host = report['checks']['host']
    missing = [name for name in REQUIRED_HOST_TOOLS if not host.get(name)]
    missing += [name for name in ('wayland_display', 'drm_render_node') if not host.get(name)]
    missing += [name for name in ('kwin', 'user_namespace', 'binderfs',
                                  'network_namespace_support') if not host.get(name)]
    missing += [name for name in ('subordinate_uid_range', 'subordinate_gid_range')
                if not host.get(name)]
    presenter = Path(host['presenter'])
    if not presenter.is_file():
        missing.append('native presenter')
    for relative, label in (
        ('experiments/m1c/input_adapter/build/aaas-input-adapter', 'native input adapter'),
        ('experiments/m4/clipboard/build/aaas-wayland-clipboard', 'Wayland clipboard bridge'),
        ('experiments/m1b/composer_aaas/Makefile', 'Composer build inputs'),
        ('experiments/perf/input_latency_probe/build_probe.py',
         'Storage helper manifest-generation dependency'),
    ):
        path = runtime_root / relative
        if not path.is_file():
            missing.append(f'{label}: {relative}')
    if report['known_selinux_shim'] != 'PRESENT':
        missing.append('verified historical SELinux diagnostic shim and activation config')
    missing.extend(f'Android init mountpoint: /{name}' for name, present in mountpoints.items()
                   if not present)
    key = config.workspace / 'tmp/m4-storage-probe/storage-probe.keystore'
    report['checks']['development_key'] = (
        'PRESENT_PRIVATE' if key.is_file() and not key.stat().st_mode & 0o077 else
        'MISSING')
    if not key.is_file():
        missing.append('installation-local helper signing key (run aaas dev setup)')
    for relative in (
        'sources/prebuilts-build-tools-qpr2/common/bin/dx',
        'sources/prebuilts-build-tools-qpr2/common/framework/dx.jar',
        'sources/prebuilts-build-tools-qpr2/linux-x86/bin/zipalign',
        'sources/prebuilts-build-tools-qpr2/linux-x86/lib64/libc++.so',
        'tmp/apktool_3.0.3.jar', 'tmp/apksig-8.9.1.jar',
    ):
        if not (config.workspace / relative).is_file():
            missing.append(f'required helper build input: {relative}')
    zipalign = (config.workspace /
                'sources/prebuilts-build-tools-qpr2/linux-x86/bin/zipalign')
    if zipalign.is_file():
        try:
            ldd = subprocess.run(['ldd', str(zipalign)], capture_output=True,
                                 text=True, timeout=5)
            if ldd.returncode or 'not found' in ldd.stdout:
                missing.append('zipalign native dependencies: ' +
                               (ldd.stdout + ldd.stderr).strip())
        except (OSError, subprocess.SubprocessError) as error:
            missing.append(f'cannot inspect zipalign native dependencies: {error}')
    if report['checks']['workspace'].get('health', {}).get('state') != 'HEALTHY_FOR_CONTROLLED_TESTING':
        missing.append('workspace health guard')
    if check_runner and not missing:
        try:
            runner_probe = (
                'import json,run_aaas; '
                'print(json.dumps(run_aaas.verify_requirements()))')
            env = dict(os.environ)
            env.update(AAAS_RUNTIME_ROOT=str(runtime_root),
                       AAAS_WORKSPACE=str(config.workspace),
                       AAAS_ROOTFS=str(config.rootfs),
                       PYTHONPATH=str(runtime_root / 'scripts'))
            probe = subprocess.run([__import__('sys').executable, '-c', runner_probe],
                                   env=env, capture_output=True, text=True,
                                   timeout=120)
            if probe.returncode:
                raise DeveloperRuntimeError(probe.stderr.strip() or probe.stdout.strip())
            paths = json.loads(probe.stdout)
            report['checks']['runner_artifacts'] = {'state': 'PASS', 'paths': paths}
        except Exception as error:
            report['checks']['runner_artifacts'] = {'state': 'FAIL', 'detail': str(error)}
            missing.append(f'production runner prerequisites: {error}')
    elif missing:
        report['checks']['runner_artifacts'] = {'state': 'NOT_RUN', 'reason': 'host/workspace prerequisites missing'}
    report['checks']['missing_dependencies'] = missing
    if not missing:
        report['development_runtime_dependencies'] = 'PASS'
        report['development_launch'] = 'PERMITTED'
    return report


def verify_storage(config):
    """Check only rootless Android storage prerequisites; no GUI checks/probes."""
    report = {'installation_integrity': 'FAIL', 'development_profile': 'DIAGNOSTIC_LEGACY',
              'storage_runtime_dependencies': 'FAIL', 'selinux_enforcement': 'UNAVAILABLE',
              'known_selinux_shim': 'UNKNOWN', 'runtime_security': 'NOT_APPROVED',
              'production_launch': 'BLOCKED', 'headless_storage_launch': 'BLOCKED',
              'checks': {}}
    record = _read_installation(config)
    runtime = runtime_root(config)
    install_root = runtime.parent
    integrity = aaas_bundle.verify_installation(install_root)
    report['checks']['bundle'] = integrity
    report['installation_integrity'] = 'PASS'
    manifest = json.loads((install_root / 'bundle-manifest.json').read_text(encoding='utf-8'))
    expected = {item['path']: item for item in manifest['artifacts']}
    shim_paths = ('rootfs/system/lib64/libselinux_shim.so',
                  'rootfs/vendor/lib64/libselinux_shim.so')
    shims = {relative: bool((install_root / relative).is_file()
                            and expected.get(relative)
                            and hashlib.sha256((install_root / relative).read_bytes()).hexdigest()
                            == expected[relative].get('sha256'))
             for relative in shim_paths}
    report['known_selinux_shim'] = 'PRESENT' if all(shims.values()) else 'INVALID'
    report['checks']['legacy_shims'] = shims
    report['checks']['host'] = _check_host(config, runtime)
    try:
        report['checks']['workspace'] = android_workspace.check(config.workspace)
    except Exception as error:
        report['checks']['workspace'] = {'health': {'state': 'FAIL'}, 'detail': str(error)}
    required = ('bwrap', 'unshare', 'mount', 'ip', 'setfacl', 'getfacl',
                'keytool', 'java', 'javac')
    missing = [name for name in required if not report['checks']['host'].get(name)]
    for relative in ('rootfs/system/bin/init', 'rootfs/system/bin/vold',
                     'runtime/scripts/run_aaas.py',
                     'workspace-artifacts/tmp/m4_storage_services_overlay.jar',
                     'workspace-artifacts/tmp/m1d_vdc_overlay/vdc',
                     'workspace-artifacts/tmp/storage-scan-helper/AaaSStorageScan.apk',
                     'workspace-artifacts/tmp/apktool_3.0.3.jar',
                     'workspace-artifacts/tmp/apksig-8.9.1.jar',
                     'workspace-artifacts/sources/prebuilts-build-tools-qpr2/common/bin/dx'):
        if not (install_root / relative).is_file():
            missing.append(relative)
    host = report['checks']['host']
    for name in ('user_namespace', 'binderfs', 'subordinate_uid_range',
                 'subordinate_gid_range', 'network_namespace_support'):
        if not host.get(name):
            missing.append(name)
    if report['known_selinux_shim'] != 'PRESENT':
        missing.append('hash-verified legacy diagnostic SELinux shim')
    workspace = report['checks']['workspace']
    if workspace.get('health', {}).get('state') != 'HEALTHY_FOR_CONTROLLED_TESTING':
        missing.append('workspace health guard')
    userdata = config.workspace / 'android-userdata/data'
    if userdata.is_symlink() or not userdata.is_dir():
        missing.append('installation-local persistent userdata directory')
    report['checks']['missing_dependencies'] = missing
    report['checks']['paths'] = {'workspace': str(config.workspace),
                                 'rootfs': str(config.rootfs),
                                 'runtime': str(runtime),
                                 'userdata': str(userdata),
                                 'host_wayland_used': False}
    if not missing:
        report['storage_runtime_dependencies'] = 'PASS'
        report['headless_storage_launch'] = 'PERMITTED'
    return report
