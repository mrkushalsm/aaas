#!/usr/bin/env python3
"""Create and verify a restricted, relocatable local AaaS runtime bundle.

Bundles preserve the historical diagnostic rootfs for controlled development
only. Integrity is independent from runtime security approval.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sqlite3
import subprocess
import sys
import stat
import tempfile
import uuid
import shlex

import android_workspace

GIB = 1 << 30
MIN_FREE_RESERVE = 20 * GIB
INSTALL_ROOTFS_MOUNTPOINTS = ('data', 'metadata', 'cache', 'storage', 'mnt', 'dev',
                              'proc', 'sys', 'tmp', 'linkerconfig', 'debug_ramdisk')

SCHEMA = 1
PROFILE = 'android16-ranchu-x86_64'
SECURITY = {
    'classification': 'DIAGNOSTIC_ONLY',
    'runtime_security': 'NOT_APPROVED',
    'general_runtime_start': 'BLOCKED',
    'untrusted_apks': 'NOT_APPROVED',
    'known_bypass_artifacts': [
        'rootfs/system/lib64/libselinux_shim.so',
        'rootfs/vendor/lib64/libselinux_shim.so',
    ],
    'limitations': [
        'The source diagnostic rootfs includes known SELinux authorization-success shims.',
        'The host does not provide verified Android SELinux policy enforcement.',
        'APEX activation and the diagnostic image security model are not approved for untrusted APKs.',
    ],
}

# Android mutable state, host-owned mount points, logs and probe data are never
# carried from the diagnostic rootfs. The runtime creates fresh instances.
EXCLUDED_TOP = {
    'data', 'metadata', 'cache', 'storage', 'mnt', 'dev', 'proc', 'sys', 'tmp',
    'lost+found', 'tombstone_export', 'aaas_diag', 'aaas_diag_output',
    'aaas_diag_request', 'aaas_appdata_output', 'aaas_appdata_request',
    'aaas_session_logcat', 'aaas_session_commands', 'aaas_session_status',
    'continuous_logcat.log', 'data_composer.log', 'data_allocator.log',
    'data_logcat.log', 'data_sf_strace.log', 'egl_test_result.log',
    'egl_test_trace.log', 'keystore_ioctl_strace.log', 'm1e_arch_probe.log',
    'aaas_native_exec.log', 'aaas_input_adapter.log',
    'aaas_vdisplay_input_adapter.log', 'aaas_vdisplay2_input_adapter.log',
    'aaas_ime_capture.png', 'aaas_ime_output', 'aaas_ime_request',
    'aaas_restorecon_trace',
}
ROOTFS_TOP = {
    'system', 'system_ext', 'product', 'vendor', 'vendor_dlkm', 'system_dlkm',
    'odm', 'odm_dlkm', 'apex', 'bootstrap-apex', 'second_stage_resources',
    'usr', 'init.environ.rc', 'fstab.default', 'fstab.ranchu', 'init', 'bin',
    'etc', 'lib64', 'd', 'sdcard', 'adb_keys', 'bugreports',
}
RUNTIME_DIRS = ('scripts', 'manifests', 'patches', 'experiments/m1a',
                'experiments/m1b/composer_aaas', 'experiments/m1c/input_adapter',
                'experiments/m1e/display_broker', 'experiments/m3', 'experiments/m4')
EXTRA_BINARIES = {
    'experiments/m1a/build/wayland-host-presenter',
    'experiments/m1c/input_adapter/build/aaas-input-adapter',
    'experiments/m4/clipboard/build/aaas-wayland-clipboard',
}
RUNTIME_FILES = (
    'experiments/m1b/selinux_xattr_compat.c',
    'experiments/perf/input_latency_probe/build_probe.py',
    'scripts/build_android_selinux_xattr_compat.py',
    'scripts/aaas_portable_installer.py',
    # The enrolled external workspace policy hashes this recovery record. Keep
    # the evidence beside the installed runtime so checkout-free verification
    # can validate the same attestation without relaxing the health guard.
    'docs/storage/ext4-controlled-recovery-followup-2026-11-10.md',
)
WORKSPACE_FILES = (
    'tmp/aaas-ethernet-compat/aaas_ethernet_connectivity_overlay.apk',
    'tmp/aaas-ethernet-compat/aaas_service-connectivity.jar',
    'tmp/aaas-ethernet-compat/aaas_NetworkStack.apk',
    'tmp/aaas-ethernet-compat/aaas_ethernet_connectivity_overlay.json',
    'tmp/m1b84_composer_portrait_720x1280',
    'tmp/android.hardware.graphics.composer3-service.aaas',
    'tmp/android.hardware.graphics.allocator-service.aaas',
    'tmp/m1e_composer_vdisplay_experimental', 'tmp/m1e_composer_two_output',
    'tmp/m1e_composer_two_output.json',
    'tmp/m1e_aaas_display_broker.dex', 'tmp/m1e_services_alarm_fallback.jar',
    'tmp/m1e_services_alarm_fallback.json', 'tmp/m1e_framework_transition_input.jar',
    'tmp/m1e_framework_transition_input.json',
    'tmp/m1e_swiftshader_fixed_notrace_v2.so',
    'tmp/m1e_swiftshader_fixed_notrace_v2.so.manifest.json',
    'tmp/m1b83_lmkd_vmstats_diagnostic', 'tmp/m1b85_lmkd_source_built',
    'tmp/m1b8_service-ranging.rebuilt2.jar',
    'tmp/m1b81_networkstats_uid_diagnostic.so',
    'tmp/m1b81_meminfo_gpu_diagnostic.so',
    'tmp/m1b8_services_battery_mobile_diagnostic.jar',
    'tmp/m1b81_libkeystore_sid_uid1000_rebuild.so',
    'tmp/m1b81_libhwsm_sid_probe_rebuilt.so', 'tmp/m1d_vdc_overlay/vdc',
    'tmp/m4_storage_services_overlay.jar', 'tmp/m4_storage_services_overlay.json',
    'tmp/apktool_3.0.3.jar', 'tmp/apksig-8.9.1.jar',
    'tmp/slirp4netns', 'tmp/slirp4netns.build.json',
    'tmp/clipboard-ime/AaasClipboard.apk',
    'tmp/m4-notifications/AaasNotifications.apk',
    'tmp/storage-scan-helper/AaaSStorageScan.apk',
    'tmp/m4-audio/audio.primary.aaas.so',
    'tmp/m4-audio/audio.primary.aaas.so.manifest.json',
    'tmp/m4-audio/libaaas-audio-ashmem.so',
    'tmp/m4-audio/libaaas-audio-factory-compat.so',
    'tmp/m4-audio/init.ranchu.rc', 'tmp/m4-audio/mediaextractor.rc',
    'tmp/m4-audio/mediaextractor.policy',
    'tmp/m4-audio/pristine-system/audioserver',
    'tmp/m4-audio/pristine-system/libaudiohal.so',
    'tmp/m4-audio/pristine-system/manifest.json',
    'tmp/partitions/system.raw.img',
    'tmp/m3_native_bridge/AaasM3NativeBridge.apk',
)
WORKSPACE_TREES = ('tmp/m3_native_bridge/digitalis', 'toolchain/libc++')
BUILD_TOOLS = ('sources/prebuilts-build-tools-qpr2/common/bin/dx',
               'sources/prebuilts-build-tools-qpr2/common/framework/dx.jar',
               'sources/prebuilts-build-tools-qpr2/linux-x86/bin/zipalign',
               'sources/prebuilts-build-tools-qpr2/linux-x86/lib64/libc++.so')


class BundleError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ('..', '.') for part in path.parts):
        raise BundleError(f'unsafe bundle path: {value!r}')
    return path


def _copy_tree(source: Path, dest: Path, *, exclude_top=False):
    source = source.resolve(strict=True)
    if source.is_symlink() or not source.is_dir():
        raise BundleError(f'expected a real directory: {source}')
    for current, dirs, files in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        rel = current_path.relative_to(source)
        dirs[:] = [d for d in dirs if d != '__pycache__']
        files = [f for f in files if not f.endswith('.pyc')]
        if exclude_top and rel == Path('.'):
            dirs[:] = sorted(d for d in dirs if d in ROOTFS_TOP and d not in EXCLUDED_TOP)
            files = [f for f in files if f in ROOTFS_TOP and f not in EXCLUDED_TOP]
        else:
            dirs.sort()
        out_dir = dest / rel
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copystat(current_path, out_dir, follow_symlinks=False)
        for name in sorted(dirs + files):
            src = current_path / name
            target = out_dir / name
            if src.is_symlink():
                link = os.readlink(src)
                target.symlink_to(link)
                try:
                    shutil.copystat(src, target, follow_symlinks=False)
                except OSError:
                    pass
            elif src.is_dir():
                target.mkdir(exist_ok=True)
                shutil.copystat(src, target, follow_symlinks=False)
            elif src.is_file():
                shutil.copy2(src, target, follow_symlinks=False)
            else:
                # Socket/device/FIFO entries are session state, never bundle data.
                continue


def _copy_selected_runtime(repo: Path, workspace: Path, dest: Path):
    for relative in RUNTIME_DIRS:
        source = repo / relative
        if source.is_dir():
            _copy_tree(source, dest / relative)
    for relative in EXTRA_BINARIES:
        source = repo / relative
        if source.is_file() and not source.is_symlink():
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for relative in RUNTIME_FILES:
        source = repo / relative
        if source.is_file() and not source.is_symlink():
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    # Keep the original configuration and profile records with the runtime.
    for relative in ('manifests/android-profiles.json',):
        source = repo / relative
        if source.is_file():
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    artifacts = dest.parent / 'workspace-artifacts'
    artifacts.mkdir(parents=True, exist_ok=True)
    for relative in WORKSPACE_FILES + BUILD_TOOLS:
        source = workspace / relative
        if not source.is_file() or source.is_symlink():
            continue
        target = artifacts / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for relative in WORKSPACE_TREES:
        source = workspace / relative
        if source.is_dir() and not source.is_symlink():
            _copy_tree(source, artifacts / relative)


def _copy_rootfs_mapped(source: Path, destination: Path):
    """Copy Android-owned mode-restricted files through the runner's ID map."""
    destination.mkdir(parents=True, exist_ok=True)
    command = ['unshare', '--user', '--map-root-user', '--map-auto',
               sys.executable, str(Path(__file__).resolve()),
               '--copy-rootfs', str(source), str(destination)]
    try:
        subprocess.run(command, check=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as error:
        raise BundleError(f'cannot copy protected Android rootfs in mapped user namespace: {error}') from error
def _inventory(root: Path):
    records = []
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs.sort(); files.sort()
        for name in list(dirs) + files:
            path = current_path / name
            rel = path.relative_to(root).as_posix()
            mode = stat.S_IMODE(path.lstat().st_mode)
            if path.is_symlink():
                records.append({'path': rel, 'type': 'symlink', 'mode': mode,
                                'target': os.readlink(path)})
            elif path.is_file():
                records.append({'path': rel, 'type': 'file', 'mode': mode,
                                'size': path.stat().st_size, 'sha256': _sha(path)})
            elif path.is_dir():
                records.append({'path': rel, 'type': 'directory', 'mode': mode})
    return records


def _runtime_closure_report(root: Path):
    """Check the packaged inputs used to regenerate runtime helper artifacts.

    Host interfaces and the per-install signer are intentionally external:
    the former are capability-checked on the target host, and the latter is
    created in private XDG state by the installed CLI.
    """
    required = (
        'runtime/scripts/run_aaas.py',
        'runtime/scripts/aaas_dev.py',
        'runtime/scripts/build_m4_audio_overlays.py',
        'runtime/experiments/m4/audio/build_audio_hal.py',
        'runtime/experiments/m4/audio/build_ashmem_compat.py',
        'runtime/experiments/m4/audio/build_factory_compat.py',
        'runtime/experiments/m4/storage_scan_helper/build_scan_helper.py',
        'runtime/experiments/m4/clipboard/build_clipboard_ime.py',
        'runtime/experiments/m4/notifications/build_listener.py',
        'workspace-artifacts/tmp/apktool_3.0.3.jar',
        'workspace-artifacts/tmp/apksig-8.9.1.jar',
        'workspace-artifacts/sources/prebuilts-build-tools-qpr2/common/bin/dx',
        'workspace-artifacts/sources/prebuilts-build-tools-qpr2/linux-x86/bin/zipalign',
        'workspace-artifacts/tmp/partitions/system.raw.img',
        'rootfs/system/framework/framework-res.apk',
        'workspace-artifacts/tmp/m4-audio/audio.primary.aaas.so',
        'workspace-artifacts/tmp/m4-audio/libaaas-audio-ashmem.so',
        'workspace-artifacts/tmp/m4-audio/libaaas-audio-factory-compat.so',
        'workspace-artifacts/tmp/slirp4netns',
        'workspace-artifacts/tmp/slirp4netns.build.json',
        'workspace-artifacts/toolchain/libc++/usr/include/c++/v1/vector',
    )
    required += tuple('workspace-artifacts/' + path for path in WORKSPACE_FILES
                      if path.startswith('tmp/aaas-ethernet-compat/'))
    missing = [relative for relative in required
               if not (root / relative).is_file()]
    slirp_binary = root / 'workspace-artifacts/tmp/slirp4netns'
    slirp_record = root / 'workspace-artifacts/tmp/slirp4netns.build.json'
    if slirp_binary.is_file() and slirp_record.is_file():
        try:
            record = json.loads(slirp_record.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            record = {}
        actual_hash = _sha(slirp_binary)
        if (record.get('commit') != '944fa94090e1fd1312232cbc0e6b43585553d824'
                or record.get('binary_sha256') != actual_hash):
            missing.append('slirp4netns pinned build provenance/hash verification')
    dev_source = root / 'runtime/scripts/aaas_dev.py'
    cli_source = root / 'runtime/scripts/aaas_cli.py'
    runner_source = root / 'runtime/scripts/run_aaas.py'
    signing_ready = all(path.is_file() and token in path.read_text(errors='replace')
                        for path, token in (
                            (dev_source, 'ensure_signing_key'),
                            (cli_source, 'AAAS_HELPER_KEYSTORE'),
                            (runner_source, 'AAAS_HELPER_KEYSTORE')))
    if not signing_ready:
        missing.append('per-install helper signing flow (XDG state provisioning)')
    return {
        'status': 'PASS' if not missing else 'PARTIAL',
        'checked_inputs': len(required),
        'missing_inputs': missing,
        'helper_apk_builds': 'rebuildable from packaged source and pinned tools',
        'audio_overlay': 're-extracted from packaged Android system image by declared script',
        'android_network_helper': 'slirp4netns built from pinned upstream commit and hash-verified',
        'signing': 'per-install identity generated in private XDG state; key excluded from bundle',
        'external_capabilities': [
            'Java/Javac/keytool, make, clang++, readelf, guestmount, Wayland, Binder, DRM, PipeWire and libslirp runtime libraries are host-provided and preflight-checked',
        ],
        'reproducibility_limitations': [
            'Android base/diagnostic rootfs is a recorded historical image input, not rebuilt from AOSP source',
        ],
    }


def _filesystem_probe(parent: Path):
    parent.mkdir(parents=True, exist_ok=True)
    if not os.access(parent, os.W_OK | os.X_OK):
        raise BundleError(f'installation filesystem is not writable: {parent}')
    with tempfile.TemporaryDirectory(prefix='.aaas-bundle-probe-', dir=parent) as td:
        root = Path(td)
        a = root / 'a'; b = root / 'b'; link = root / 'symlink'
        a.write_bytes(b'probe'); a.chmod(0o700)
        os.link(a, b)
        link.symlink_to('a')
        temp = root / 'atomic.tmp'; target = root / 'atomic'
        temp.write_text('old'); os.replace(temp, target)
        db = sqlite3.connect(root / 'probe.sqlite')
        try:
            db.execute('create table probe (id integer primary key)')
            db.execute('insert into probe values (1)')
        finally:
            db.close()
        if not (b.stat().st_ino == a.stat().st_ino and link.read_bytes() == b'probe'
                and target.read_text() == 'old'):
            raise BundleError(f'installation filesystem semantics failed: {parent}')
        try:
            os.setxattr(a, 'user.aaas_probe', b'ok')
            xattrs = os.getxattr(a, 'user.aaas_probe') == b'ok'
        except OSError:
            xattrs = False
        setfacl = shutil.which('setfacl')
        getfacl = shutil.which('getfacl')
        acl = False
        if setfacl and getfacl:
            grant = subprocess.run([setfacl, '-m', 'u:65534:r--', str(a)],
                                   capture_output=True, check=False)
            read = subprocess.run([getfacl, '-n', str(a)], capture_output=True,
                                  text=True, check=False)
            acl = grant.returncode == 0 and read.returncode == 0 and 'user:65534:r--' in read.stdout
        if not (xattrs and acl):
            raise BundleError(f'installation filesystem lacks required user xattr/ACL support: {parent}')
    fs_type = subprocess.run(['findmnt', '-T', str(parent), '-n', '-o', 'FSTYPE'],
                             capture_output=True, text=True, check=False).stdout.strip()
    return {'path': str(parent), 'hard_links': True, 'symlinks': True,
            'atomic_rename': True, 'sqlite': True, 'user_xattrs': xattrs,
            'numeric_acl': acl,
            'filesystem': fs_type or 'unknown'}


def _filesystem_available_bytes(path: Path) -> int:
    """Return bytes available to an unprivileged caller, excluding ext4 reserve."""
    value = os.statvfs(path)
    return value.f_bavail * (value.f_frsize or value.f_bsize)


def create_bundle(*, repo: Path, rootfs: Path, output: Path, workspace: Path,
                  preflight=None):
    repo = repo.resolve(strict=True)
    rootfs = rootfs.resolve(strict=True)
    workspace = workspace.resolve(strict=True)
    output = output.expanduser().absolute()
    if not (rootfs == workspace / 'rootfs_m1b1'):
        raise BundleError('local-development bundle source must be the selected rootfs_m1b1')
    if output.exists() or output.is_symlink():
        raise BundleError(f'refusing to replace existing bundle path: {output}')
    if output == rootfs or rootfs in output.parents:
        raise BundleError('bundle output cannot be inside the protected diagnostic rootfs')
    if preflight:
        preflight()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_name(f'.{output.name}.staging-{uuid.uuid4().hex}')
    published = False
    try:
        (stage / 'rootfs').mkdir(parents=True)
        _copy_rootfs_mapped(rootfs, stage / 'rootfs')
        if not (stage / 'rootfs/system/lib64/libaaas-selinux-xattr-compat.so').is_file():
            raise BundleError('diagnostic runtime is missing its Android SELinux xattr compatibility preload')
        for relative in ('system/lib64/libselinux_shim.so',
                         'vendor/lib64/libselinux_shim.so'):
            if not (stage / 'rootfs' / relative).is_file():
                raise BundleError(f'diagnostic security classification mismatch; expected bypass artifact absent: {relative}')
        service_rc = stage / 'rootfs/system/etc/init/servicemanager.rc'
        try:
            init_text = service_rc.read_text(encoding='utf-8', errors='replace')
        except OSError as error:
            raise BundleError(f'cannot inspect diagnostic SELinux shim activation: {error}') from error
        if '/system/lib64/libselinux_shim.so' not in init_text:
            raise BundleError('diagnostic SELinux preload activation was not found; refusing this bundle profile')
        # Preserve the selected Android root layout as symlinks/empty mountpoints.
        # Top-level rootfs symlinks are included by _copy_tree; excluded mutable
        # directories remain absent until installation creates fresh ones.
        _copy_selected_runtime(repo, workspace, stage / 'runtime')
        installer = stage / 'install.py'
        installer.write_text(
            '#!/usr/bin/env python3\n'
            'import os, sys\n'
            'from pathlib import Path\n'
            'sys.dont_write_bytecode = True\n'
            'bundle = Path(__file__).resolve().parent\n'
            'os.environ["AAAS_BUNDLE_PATH"] = str(bundle)\n'
            'sys.path.insert(0, str(bundle / "runtime/scripts"))\n'
            'from aaas_portable_installer import main\n'
            'raise SystemExit(main())\n', encoding='utf-8')
        installer.chmod(0o755)
        install_shell = stage / 'install'
        install_shell.write_text(
            '#!/bin/sh\nset -eu\n'
            'SELF=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
            'exec python3 "$SELF/install.py" "$@"\n', encoding='utf-8')
        install_shell.chmod(0o755)
        inventory = _inventory(stage)
        for record in inventory:
            if record['path'] in ('install', 'install.py'):
                record['scope'] = 'bundle-installer'
        try:
            source_revision = subprocess.run(
                ['git', '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True,
                text=True, check=True, timeout=3).stdout.strip()
            tracked_files = set(subprocess.run(
                ['git', '-C', str(repo), 'ls-files'], capture_output=True,
                text=True, check=True, timeout=5).stdout.splitlines())
            source_tree_dirty = bool(subprocess.run(
                ['git', '-C', str(repo), 'status', '--porcelain'], capture_output=True,
                text=True, check=True, timeout=5).stdout.strip())
        except (OSError, subprocess.SubprocessError):
            source_revision = 'unavailable'
            tracked_files = set()
            source_tree_dirty = None
        provenance_records = []
        for entry in inventory:
            path = entry['path']
            if entry['type'] != 'file' or not (
                    entry.get('mode', 0) & 0o111 or path.endswith(('.so', '.apk'))):
                continue
            if path in ('install', 'install.py'):
                provenance = 'AaaS bundle installer generated by the release builder'
                source = f'AaaS scripts/aaas_bundle.py at revision {source_revision}; worktree_dirty={source_tree_dirty}'
                role = 'AaaS portable bundle installer'
            elif path.startswith('runtime/'):
                source_relative = path.removeprefix('runtime/')
                if source_relative in tracked_files:
                    provenance = 'AaaS source checkout; revision recorded'
                    source = f'AaaS repository revision {source_revision}'
                else:
                    provenance = 'UNVERIFIED_PROVENANCE'
                    source = 'untracked local runtime artifact included in the working M4 closure'
                role = 'host runtime code or executable'
            elif path == 'workspace-artifacts/tmp/partitions/system.raw.img':
                provenance = 'EXTRACTED_FROM_RECORDED_ANDROID_SDK_IMAGE'
                source = 'Android SDK system partition, Android 16 BE2A.250530.026.D1'
                role = 'audio compatibility overlay input'
            elif path == 'rootfs/system/lib64/libaaas-selinux-xattr-compat.so':
                provenance = 'GENERATED_FROM_AAAS_SOURCE'
                source = ('experiments/m1b/selinux_xattr_compat.c via '
                          'scripts/build_android_selinux_xattr_compat.py')
                role = 'Android x86_64 diagnostic SELinux label compatibility preload'
            elif path.startswith('workspace-artifacts/'):
                provenance = 'UNVERIFIED_PROVENANCE'
                source = 'retained historical M4 generated workspace artifact'
                role = 'Android compatibility overlay, helper, or host integration artifact'
            else:
                provenance = 'UNVERIFIED_PROVENANCE'
                source = 'historical modified M4 diagnostic rootfs based on Android 16 SDK image'
                role = 'Android platform executable, library, or app'
            provenance_records.append({
                'path': path, 'sha256': entry.get('sha256'),
                'architecture': ('Android x86_64 or ARM64 payload; per-file ABI is not resolved'
                                 if path.endswith('.apk') else
                                 'host x86_64' if path.startswith('runtime/experiments/')
                                 else 'Android x86_64 unless otherwise indicated by artifact'),
                'destination': path, 'role': role, 'provenance': provenance,
                'source_identity': source, 'license_review': 'NOT_REVIEWED_FOR_DISTRIBUTION',
            })
        manifest = {
            'schema': SCHEMA,
            'bundle_id': uuid.uuid4().hex,
            'profile': PROFILE,
            'android': {'release': '16', 'api_level': 36, 'abi': 'x86_64',
                        'build_id': 'BE2A.250530.026.D1',
                        'source_kind': 'historical M4 diagnostic runtime rootfs',
                        'source_rootfs': 'rootfs_m1b1 (local input; not source reproducible)'},
            'host_architecture': platform.machine(),
            'authenticity': 'NOT_ESTABLISHED; local unsigned development bundle',
            'classification': 'LOCAL_DEVELOPMENT_DIAGNOSTIC',
            'installation_integrity': 'PASS',
            'security': SECURITY,
            'artifact_count': len(inventory),
            'artifacts': inventory,
            'provenance': {
                'rootfs': 'UNVERIFIED_PROVENANCE',
                'source_repository_revision': source_revision,
                'source_tree_dirty_at_capture': source_tree_dirty,
                'executable_library_provenance': provenance_records,
                'historical_modified_android_binaries': 'UNVERIFIED_PROVENANCE',
                'SELinux shim presence': 'KNOWN_DIAGNOSTIC_LIMITATION',
                'source_repository': 'AaaS source files copied from current checkout',
                'limitations': [
                    'This is a local relocation bundle, not a reproducible image build.',
                    'Rootfs modifications and several binary inputs have no verified source revision.',
                    'Host build caches and all persistent Android/user data are excluded.',
                    'Required external/workspace generated runtime artifacts may remain unresolved.',
                ],
            },
            'runtime_closure': {
                **_runtime_closure_report(stage),
                'checker': 'aaas-runtime-inputs-v1',
                'packaged_workspace_artifacts': sum(
                    entry['path'].startswith('workspace-artifacts/') for entry in inventory),
            },
            'metadata_capabilities': {
                'file_modes': 'preserved', 'symlinks': 'preserved',
                'xattrs': 'copystat best-effort; SELinux labels are not portable',
                'ownership': 'installing user owns host files; Android UID mapping is namespace-local',
                'hardlinks': 'not guaranteed',
            },
        }
        manifest_path = stage / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n',
                                 encoding='utf-8')
        manifest_path.chmod(0o644)
        os.replace(stage, output)
        published = True
        result = inspect_bundle(output)
        result['verification'] = verify_bundle(output)
        result['integrity'] = 'PASS'
        result['runtime_security'] = 'NOT_APPROVED'
        return result
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        if published and output.exists():
            shutil.rmtree(output)
        raise


def inspect_bundle(bundle: Path):
    bundle = bundle.expanduser().resolve(strict=True)
    manifest_path = bundle / 'manifest.json'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise BundleError(f'invalid bundle manifest: {error}') from error
    if manifest.get('schema') != SCHEMA or manifest.get('profile') != PROFILE:
        raise BundleError('unsupported bundle schema or profile')
    return manifest


def verify_bundle(bundle: Path):
    bundle = bundle.expanduser().resolve(strict=True)
    manifest_path = bundle / 'manifest.json'
    manifest = inspect_bundle(bundle)
    if manifest.get('host_architecture') != platform.machine():
        raise BundleError(f"host architecture mismatch: bundle={manifest.get('host_architecture')} host={platform.machine()}")
    expected = {entry['path']: entry for entry in manifest.get('artifacts', [])}
    if len(expected) != manifest.get('artifact_count'):
        raise BundleError('manifest artifact count is inconsistent')
    seen = set()
    for relative, record in expected.items():
        rel = _safe_relative(relative)
        path = bundle / rel
        parent = bundle
        for component in rel.parts[:-1]:
            parent = parent / component
            if parent.is_symlink():
                raise BundleError(f'artifact parent escapes through symlink: {relative}')
        if not path.exists() and not path.is_symlink():
            raise BundleError(f'missing bundle artifact: {relative}')
        mode = stat.S_IMODE(path.lstat().st_mode)
        if mode != record.get('mode'):
            raise BundleError(f'mode mismatch: {relative}')
        if record['type'] == 'symlink':
            if not path.is_symlink() or os.readlink(path) != record.get('target'):
                raise BundleError(f'symlink mismatch: {relative}')
        elif record['type'] == 'file':
            if path.is_symlink() or not path.is_file() or path.stat().st_size != record.get('size'):
                raise BundleError(f'file type/size mismatch: {relative}')
            if _sha(path) != record.get('sha256'):
                raise BundleError(f'hash mismatch: {relative}')
        elif record['type'] == 'directory':
            if path.is_symlink() or not path.is_dir():
                raise BundleError(f'directory mismatch: {relative}')
        else:
            raise BundleError(f'unknown artifact type: {record["type"]}')
        seen.add(relative)
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*')
              if p != manifest_path}
    if actual != seen:
        extras = sorted(actual - seen)
        raise BundleError(f'unmanifested bundle entries present: {extras[:5]}')
    closure = manifest.get('runtime_closure', {})
    if closure.get('checker') == 'aaas-runtime-inputs-v1':
        checked_closure = _runtime_closure_report(bundle)
        if checked_closure['status'] != closure.get('status') or \
                checked_closure['missing_inputs'] != closure.get('missing_inputs'):
            raise BundleError('runtime closure report does not match packaged build inputs')
    return {'bundle': str(bundle), 'bundle_id': manifest['bundle_id'],
            'integrity': 'PASS', 'artifact_count': len(expected),
            'installation_integrity': 'PASS', 'runtime_closure': manifest['runtime_closure'],
            'runtime_security': 'NOT_APPROVED', 'general_runtime_start': 'BLOCKED'}


def verify_installation(installation: Path):
    installation = installation.expanduser().resolve(strict=True)
    manifest_path = installation / 'bundle-manifest.json'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise BundleError(f'installation bundle manifest is invalid: {error}') from error
    closure = manifest.get('runtime_closure', {})
    checked_closure = _runtime_closure_report(installation)
    if (closure.get('checker') == 'aaas-runtime-inputs-v1' and
            (checked_closure['status'] != closure.get('status') or
             checked_closure['missing_inputs'] != closure.get('missing_inputs'))):
        raise BundleError('installed runtime closure report does not match installed inputs')
    checked = 0
    for record in manifest.get('artifacts', []):
        if record.get('scope') == 'bundle-installer':
            continue
        rel = _safe_relative(record['path'])
        path = installation / rel
        parent = installation
        for component in rel.parts[:-1]:
            parent /= component
            if parent.is_symlink():
                raise BundleError(f'installation path escapes through symlink: {record["path"]}')
        if not path.exists() and not path.is_symlink():
            raise BundleError(f'installation artifact missing: {record["path"]}')
        if stat.S_IMODE(path.lstat().st_mode) != record.get('mode'):
            raise BundleError(f'installation artifact mode mismatch: {record["path"]}')
        if record['type'] == 'symlink':
            if not path.is_symlink() or os.readlink(path) != record.get('target'):
                raise BundleError(f'installation symlink mismatch: {record["path"]}')
        elif record['type'] == 'file':
            if path.is_symlink() or not path.is_file() or path.stat().st_size != record.get('size'):
                raise BundleError(f'installation file size/type mismatch: {record["path"]}')
            if _sha(path) != record.get('sha256'):
                raise BundleError(f'installation hash mismatch: {record["path"]}')
        elif record['type'] == 'directory':
            if path.is_symlink() or not path.is_dir():
                raise BundleError(f'installation directory mismatch: {record["path"]}')
        else:
            raise BundleError(f'installation manifest has unknown type: {record["type"]}')
        checked += 1
    return {'installation': str(installation), 'integrity': 'PASS',
            'artifact_count': checked, 'bundle_id': manifest.get('bundle_id'),
            'runtime_closure': closure.get('status', 'PARTIAL'),
            'runtime_security': 'NOT_APPROVED', 'general_runtime_start': 'BLOCKED'}


def refresh_runtime_file(*, bundle: Path, installation: Path, source: Path,
                         relative: str):
    """Atomically refresh one reviewed runtime source file without recopying images.

    The same relative artifact must be present in a verified bundle and its
    installation. Bundle identity is preserved; only the artifact digest and
    size are updated. This is intended for small runtime-script fixes.
    """
    bundle = Path(bundle).expanduser().resolve(strict=True)
    installation = Path(installation).expanduser().resolve(strict=True)
    source = Path(source).expanduser().resolve(strict=True)
    rel = _safe_relative(relative)
    if not relative.startswith('runtime/'):
        raise BundleError('refresh is limited to runtime artifacts')
    if source.is_symlink() or not source.is_file():
        raise BundleError('refresh source must be a regular file')
    bundle_report = verify_bundle(bundle)
    install_report = verify_installation(installation)
    if bundle_report['bundle_id'] != install_report.get('bundle_id'):
        raise BundleError('bundle and installation identities do not match')
    bundle_path = bundle / rel
    install_path = installation / rel
    if bundle_path.is_symlink() or install_path.is_symlink():
        raise BundleError('refusing to refresh a symlinked runtime artifact')
    bundle_manifest_path = bundle / 'manifest.json'
    install_manifest_path = installation / 'bundle-manifest.json'
    bundle_manifest = inspect_bundle(bundle)
    install_manifest = json.loads(install_manifest_path.read_text(encoding='utf-8'))
    bundle_entries = {item['path']: item for item in bundle_manifest['artifacts']}
    install_entries = {item['path']: item for item in install_manifest['artifacts']}
    key = rel.as_posix()
    if key not in bundle_entries or key not in install_entries:
        raise BundleError(f'runtime artifact is not declared in both manifests: {key}')
    if bundle_entries[key] != install_entries[key]:
        raise BundleError(f'bundle and installation artifact records differ: {key}')
    if not bundle_path.is_file() or not install_path.is_file():
        raise BundleError(f'runtime artifact is missing: {key}')
    source_hash = _sha(source)
    source_mode = stat.S_IMODE(source.stat().st_mode)
    entry = dict(bundle_entries[key])
    entry.update({'type': 'file', 'mode': source_mode,
                  'size': source.stat().st_size, 'sha256': source_hash})
    bundle_manifest['artifacts'] = [entry if item['path'] == key else item
                                    for item in bundle_manifest['artifacts']]
    install_manifest['artifacts'] = [entry if item['path'] == key else item
                                     for item in install_manifest['artifacts']]
    # Stage both payload copies and preserve the old bytes for rollback. No
    # rootfs or userdata files are copied or rewritten.
    targets = (bundle_path, install_path)
    staged = []
    backups = []
    staged_manifests = []
    manifest_backups = []
    def refresh_temp(parent, prefix):
        descriptor, name = tempfile.mkstemp(prefix=prefix, dir=parent)
        os.close(descriptor)
        return Path(name)
    try:
        for target, stage_parent in zip(targets, (bundle.parent, installation.parent)):
            temporary = refresh_temp(stage_parent, '.aaas-refresh-')
            shutil.copy2(source, temporary)
            staged.append((temporary, target))
            backup = refresh_temp(stage_parent, '.aaas-refresh-backup-')
            shutil.copy2(target, backup)
            backups.append((backup, target))
        for path, stage_parent in zip((bundle_manifest_path, install_manifest_path),
                                      (bundle.parent, installation.parent)):
            backup = refresh_temp(stage_parent, '.aaas-refresh-manifest-backup-')
            shutil.copy2(path, backup)
            manifest_backups.append((backup, path))
        for path, value, stage_parent in (
                (bundle_manifest_path, bundle_manifest, bundle.parent),
                (install_manifest_path, install_manifest, installation.parent)):
            temporary = refresh_temp(stage_parent, '.aaas-refresh-manifest-')
            temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n',
                                 encoding='utf-8')
            staged_manifests.append((temporary, path))
        for temporary, target in staged:
            os.replace(temporary, target)
        for temporary, target in staged_manifests:
            os.replace(temporary, target)
        if verify_bundle(bundle)['integrity'] != 'PASS' or \
                verify_installation(installation)['integrity'] != 'PASS':
            raise BundleError('refreshed artifact failed post-install integrity verification')
    except Exception:
        for backup, target in manifest_backups:
            if backup.exists():
                os.replace(backup, target)
        for backup, target in backups:
            if backup.exists():
                os.replace(backup, target)
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        for temporary, _ in staged_manifests:
            temporary.unlink(missing_ok=True)
        for backup, _ in backups:
            backup.unlink(missing_ok=True)
        for backup, _ in manifest_backups:
            backup.unlink(missing_ok=True)
    return {'bundle': str(bundle), 'installation': str(installation),
            'artifact': key, 'sha256': source_hash,
            'bundle_integrity': verify_bundle(bundle)['integrity'],
            'installation_integrity': verify_installation(installation)['integrity']}


def enroll_installer_workspace(installation: Path, workspace: Path):
    """Enroll only a workspace whose staged payload exactly matches this install."""
    installation = Path(installation).resolve(strict=True)
    workspace = Path(workspace).resolve(strict=True)
    record = json.loads((installation / 'installation.json').read_text(encoding='utf-8'))
    if (record.get('classification') != 'LOCAL_DEVELOPMENT_DIAGNOSTIC'
            or Path(record.get('paths', {}).get('workspace', '')).resolve() != workspace):
        raise BundleError('workspace is not owned by this diagnostic installation')
    if verify_installation(installation).get('integrity') != 'PASS':
        raise BundleError('installation integrity check failed before workspace enrollment')
    import android_workspace
    import aaas_userdata
    marker = workspace / android_workspace.MARKER
    if marker.is_file():
        enrolled = android_workspace.check(workspace)
        marker_data = json.loads(marker.read_text(encoding='utf-8'))
        recorded_id = record.get('workspace_id')
        if recorded_id and marker_data.get('workspace_id') != recorded_id:
            raise BundleError('workspace identity does not match installation record')
    else:
        source = installation / 'workspace-artifacts'
        allowed_top = {'tmp', 'sources', 'toolchain'}
        actual_top = {item.name for item in workspace.iterdir()}
        if not actual_top.issubset(allowed_top):
            raise BundleError('workspace contains data outside installer-staged artifacts')
        for base in allowed_top:
            expected = source / base
            actual = workspace / base
            if expected.exists() != actual.exists():
                raise BundleError(f'installer workspace payload mismatch: {base}')
            if expected.exists() and _inventory(expected) != _inventory(actual):
                raise BundleError(f'installer workspace payload was changed: {base}')
        enrolled = android_workspace.initialize(workspace, adopt=True)
    userdata = aaas_userdata.prepare_userdata_directory(workspace)
    marker_data = json.loads(marker.read_text(encoding='utf-8'))
    return {'workspace': str(workspace), 'enrollment': 'PASS',
            'workspace_id': marker_data.get('workspace_id'),
            'health': enrolled.get('health'), 'userdata': str(userdata),
            'userdata_state': 'fresh; no source user data copied'}


def install_bundle(*, bundle: Path, workspace: Path, install_root: Path,
                   config_home: Path, data_home: Path, desktop_home: Path | None = None):
    verified = verify_bundle(bundle)
    bundle = bundle.expanduser().resolve(strict=True)
    workspace = workspace.expanduser().absolute()
    install_root = install_root.expanduser().absolute()
    config_home = config_home.expanduser().absolute()
    data_home = data_home.expanduser().absolute()
    desktop_home = (Path(desktop_home).expanduser().absolute() if desktop_home else
                    Path.home() / '.local/share')
    for path in (workspace, install_root, config_home, data_home):
        if not path.is_absolute():
            raise BundleError(f'installation path must be absolute: {path}')
    if install_root.exists() or install_root.is_symlink():
        raise BundleError(f'refusing to replace existing installation: {install_root}')
    if install_root == bundle or bundle in install_root.parents:
        raise BundleError('installation destination must be separate from bundle')
    reuse_workspace = workspace.exists() and any(workspace.iterdir())
    if reuse_workspace:
        marker = workspace / android_workspace.MARKER
        if not marker.is_file():
            raise BundleError('workspace must be empty or an enrolled AaaS workspace; '
                              'refusing to adopt or alter existing data')
        try:
            android_workspace.check(workspace)
            import aaas_userdata
            aaas_userdata.prepare_userdata_directory(workspace)
        except Exception as error:
            raise BundleError(f'existing AaaS workspace failed preservation checks: {error}') from error
    cfg = config_home / 'aaas' / 'config.toml'
    installed_data_manifest = data_home / 'aaas' / 'installation.json'
    reuse_config = cfg.exists() and not cfg.is_symlink()
    if cfg.is_symlink():
        raise BundleError(f'refusing symlinked config: {cfg}')
    if reuse_config:
        try:
            import tomllib
            existing_config = tomllib.loads(cfg.read_text(encoding='utf-8'))
            paths = existing_config.get('paths', {})
            if (Path(paths.get('workspace', '')).expanduser().absolute() != workspace or
                    Path(paths.get('rootfs', '')).expanduser().absolute() != install_root / 'rootfs'):
                raise BundleError('existing user config targets different AaaS data; preserve it and choose new XDG paths')
        except (OSError, ValueError) as error:
            if isinstance(error, BundleError):
                raise
            raise BundleError(f'existing AaaS config is not reusable: {error}') from error
    reuse_data_manifest = installed_data_manifest.exists() and not installed_data_manifest.is_symlink()
    if installed_data_manifest.is_symlink():
        raise BundleError('refusing symlinked installation metadata')
    old_data_manifest = None
    old_data_manifest_bytes = None
    if reuse_data_manifest:
        try:
            old_data_manifest_bytes = installed_data_manifest.read_bytes()
            old_data_manifest = json.loads(old_data_manifest_bytes)
            if (old_data_manifest.get('classification') != 'LOCAL_DEVELOPMENT_DIAGNOSTIC' or
                    Path(old_data_manifest.get('paths', {}).get('workspace', '')).absolute() != workspace):
                raise BundleError('existing installation metadata belongs to different user data')
        except (OSError, json.JSONDecodeError) as error:
            raise BundleError(f'existing installation metadata is not reusable: {error}') from error
    install_root.parent.mkdir(parents=True, exist_ok=True)
    install_probe = _filesystem_probe(install_root.parent)
    workspace_probe = _filesystem_probe(workspace.parent)
    manifest = inspect_bundle(bundle)
    install_bytes = sum(entry.get('size', 0) for entry in manifest['artifacts']
                        if entry['path'].startswith(('rootfs/', 'runtime/',
                                                     'workspace-artifacts/')))
    workspace_bytes = sum(entry.get('size', 0) for entry in manifest['artifacts']
                          if entry['path'].startswith('workspace-artifacts/'))
    install_device = os.stat(install_root.parent).st_dev
    workspace_device = os.stat(workspace.parent).st_dev
    root_device = os.stat('/').st_dev
    growth_by_device = {}
    paths_by_device = {}
    for path, device, growth in (
            (install_root.parent, install_device, install_bytes),
            (workspace.parent, workspace_device, workspace_bytes)):
        growth_by_device[device] = growth_by_device.get(device, 0) + growth
        paths_by_device.setdefault(device, path)
    workspace_reserve = android_workspace.DEFAULT_WORKSPACE_FREE_RESERVE_GIB * GIB
    for device, growth in growth_by_device.items():
        path = paths_by_device[device]
        # Apply the reserve to the filesystem receiving payload writes. A
        # release installed on a separate workspace does not consume root.
        if device == root_device:
            reserve_gib = int(os.environ.get('AAAS_ROOT_FREE_RESERVE_GIB', '20'))
        else:
            reserve_gib = int(os.environ.get(
                'AAAS_INSTALL_FREE_RESERVE_GIB',
                str(android_workspace.DEFAULT_WORKSPACE_FREE_RESERVE_GIB)))
        if not 0 <= reserve_gib <= 1024:
            raise BundleError('configured filesystem free-space reserve must be 0..1024 GiB')
        reserve = reserve_gib * GIB
        available = _filesystem_available_bytes(path)
        if available - growth < reserve:
            label = 'host root' if device == root_device else 'installation/workspace'
            raise BundleError(f'{label} target filesystem lacks payload plus configured reserve: '
                              f'free={available} predicted={growth} reserve={reserve}')
    stage = install_root.with_name(f'.{install_root.name}.staging-{uuid.uuid4().hex}')
    installed = config_written = data_written = workspace_created = False
    cfg_temp = data_temp = None
    try:
        shutil.copytree(bundle / 'runtime', stage / 'runtime', symlinks=True,
                        copy_function=shutil.copy2)
        shutil.copytree(bundle / 'workspace-artifacts', stage / 'workspace-artifacts',
                        symlinks=True, copy_function=shutil.copy2)
        shutil.copytree(bundle / 'rootfs', stage / 'rootfs', symlinks=True,
                        copy_function=shutil.copy2)
        shutil.copy2(bundle / 'manifest.json', stage / 'bundle-manifest.json')
        for name in INSTALL_ROOTFS_MOUNTPOINTS:
            (stage / 'rootfs' / name).mkdir(exist_ok=True)
        install_manifest = {
            'schema': 1, 'bundle_id': verified['bundle_id'], 'profile': PROFILE,
            'classification': 'LOCAL_DEVELOPMENT_DIAGNOSTIC',
            'paths': {'workspace': str(workspace), 'rootfs': str(install_root / 'rootfs'),
                      'runtime': str(install_root / 'runtime'),
                      'workspace_artifacts': str(install_root / 'workspace-artifacts')},
            'installation_integrity': 'PASS', 'runtime_security': 'NOT_APPROVED',
            'general_runtime_start': 'BLOCKED',
            'userdata': 'fresh path; not initialized or copied from source',
            'runtime_closure': manifest.get('runtime_closure', {}).get('status', 'PARTIAL'),
            'generated_rootfs_mountpoints': list(INSTALL_ROOTFS_MOUNTPOINTS),
        }
        (stage / 'installation.json').write_text(
            json.dumps(install_manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        bindir = stage / 'bin'
        bindir.mkdir()
        launcher = bindir / 'aaas'
        launcher.write_text(
            '#!/bin/sh\nset -eu\n'
            'SELF=$(readlink -f -- "$0")\n'
            'INSTALL_ROOT=$(dirname -- "$(dirname -- "$SELF")")\n'
            'unset AAAS_WORKSPACE AAAS_ROOTFS AAAS_RUNTIME_ROOT AAAS_PROFILE\n'
            f'export XDG_CONFIG_HOME={shlex.quote(str(config_home))}\n'
            f'export XDG_DATA_HOME={shlex.quote(str(data_home))}\n'
            f'export AAAS_DESKTOP_DATA_HOME={shlex.quote(str(desktop_home))}\n'
            'export AAAS_LAUNCHER_PATH="$INSTALL_ROOT/bin/aaas"\n'
            'exec python3 "$INSTALL_ROOT/runtime/scripts/aaas_cli.py" "$@"\n',
            encoding='utf-8')
        launcher.chmod(0o755)
        install_integrity = verify_installation(stage)
        install_manifest['installation_integrity'] = install_integrity['integrity']
        install_manifest['runtime_closure'] = manifest.get('runtime_closure', {}).get(
            'status', 'PARTIAL')
        (stage / 'installation.json').write_text(
            json.dumps(install_manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        stage.rename(install_root)
        installed = True
        # Keep configuration under the selected config root. No original path is
        # embedded in the runtime tree; all locations are installation-specific.
        cfg.parent.mkdir(parents=True, exist_ok=True)
        if not reuse_config:
            cfg_temp = cfg.with_name(cfg.name + f'.{os.getpid()}.tmp')
            cfg_temp.write_text(
                '[paths]\nworkspace = ' + json.dumps(str(workspace)) + '\nrootfs = ' +
                json.dumps(str(install_root / 'rootfs')) + '\n\n[installation]\nprofile = ' +
                json.dumps(PROFILE) + '\n', encoding='utf-8')
            cfg_temp.chmod(0o600)
            os.replace(cfg_temp, cfg)
            config_written = True
        installed_data_manifest.parent.mkdir(parents=True, exist_ok=True)
        data_temp = installed_data_manifest.with_name(
            installed_data_manifest.name + f'.{os.getpid()}.tmp')
        install_manifest['paths']['workspace'] = str(workspace)
        install_manifest['paths']['rootfs'] = str(install_root / 'rootfs')
        install_manifest['paths']['runtime'] = str(install_root / 'runtime')
        data_temp.write_text(json.dumps(install_manifest, indent=2, sort_keys=True) + '\n',
                             encoding='utf-8')
        os.replace(data_temp, installed_data_manifest)
        data_written = True
        # The destination was verified absent or empty before staging; from
        # this point onward this installation transaction owns its contents.
        workspace_created = not reuse_workspace
        workspace.mkdir(parents=True, exist_ok=True)
        if not reuse_workspace:
            for base in ('tmp', 'sources', 'toolchain'):
                staged_artifacts = install_root / 'workspace-artifacts' / base
                if staged_artifacts.is_dir():
                    shutil.copytree(staged_artifacts, workspace / base, dirs_exist_ok=True,
                                    symlinks=True, copy_function=shutil.copy2)
        workspace_enrollment = enroll_installer_workspace(install_root, workspace)
        install_manifest['workspace_enrollment'] = 'PASS'
        install_manifest['workspace_id'] = workspace_enrollment['workspace_id']
        install_manifest['userdata'] = 'fresh installation-local backing initialized'
        (install_root / 'installation.json').write_text(
            json.dumps(install_manifest, indent=2, sort_keys=True) + '\n',
            encoding='utf-8')
        installed_data_manifest.write_text(
            json.dumps(install_manifest, indent=2, sort_keys=True) + '\n',
            encoding='utf-8')
        data_home.mkdir(parents=True, exist_ok=True)
        return {'installation': str(install_root), 'workspace': str(workspace),
                'config': str(cfg), 'installation_integrity': 'PASS',
                'filesystem': {'installation': install_probe,
                               'workspace': workspace_probe},
                'verified_artifacts': install_integrity['artifact_count'],
                'runtime_security': 'NOT_APPROVED', 'general_runtime_start': 'BLOCKED',
                'runtime_closure': manifest.get('runtime_closure', {}).get(
                    'status', 'PARTIAL'), 'userdata': workspace_enrollment['userdata_state'],
                'workspace_enrollment': workspace_enrollment,
                'workspace_reused': reuse_workspace,
                'configuration_preserved': reuse_config,
                'installation_metadata_reused': reuse_data_manifest}
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        if cfg_temp and cfg_temp.exists():
            cfg_temp.unlink()
        if data_temp and data_temp.exists():
            data_temp.unlink()
        if config_written:
            cfg.unlink(missing_ok=True)
        if data_written:
            if reuse_data_manifest and old_data_manifest_bytes is not None:
                installed_data_manifest.write_bytes(old_data_manifest_bytes)
            else:
                installed_data_manifest.unlink(missing_ok=True)
        if installed and install_root.exists():
            shutil.rmtree(install_root)
        if workspace_created and workspace.exists():
            # Only remove a workspace created by this transaction when it
            # contains no files outside the staged payload and generated state.
            try:
                allowed = {'tmp', 'sources', 'images', 'out', 'cache', 'logs', 'mnt',
                           '.aaas-workspace.json', 'android-userdata'}
                if {item.name for item in workspace.iterdir()}.issubset(allowed):
                    shutil.rmtree(workspace)
            except (OSError, NameError):
                pass
        raise


def stage_installation_update(*, bundle: Path, installation: Path) -> Path:
    """Build a verified replacement beside an installation, preserving its data paths."""
    bundle = Path(bundle).expanduser().resolve(strict=True)
    installation = Path(installation).expanduser().resolve(strict=True)
    current = verify_installation(installation)
    incoming = verify_bundle(bundle)
    new_manifest = inspect_bundle(bundle)
    old_bundle_manifest = json.loads(
        (installation / 'bundle-manifest.json').read_text(encoding='utf-8'))
    old_manifest = json.loads((installation / 'installation.json').read_text(encoding='utf-8'))
    if new_manifest.get('profile') != old_manifest.get('profile'):
        raise BundleError('update Android profile is incompatible with this installation')
    old_build = old_bundle_manifest.get('android', {}).get('build_id')
    new_build = new_manifest.get('android', {}).get('build_id')
    if old_build and new_build and old_build != new_build:
        raise BundleError('update Android build differs; userdata compatibility is unverified')
    if current.get('bundle_id') != old_manifest.get('bundle_id'):
        raise BundleError('installation manifest and installed bundle identity differ')
    stage = installation.with_name(f'.{installation.name}.update-{uuid.uuid4().hex}')
    try:
        shutil.copytree(bundle / 'runtime', stage / 'runtime', symlinks=True,
                        copy_function=shutil.copy2)
        shutil.copytree(bundle / 'workspace-artifacts', stage / 'workspace-artifacts',
                        symlinks=True, copy_function=shutil.copy2)
        shutil.copytree(bundle / 'rootfs', stage / 'rootfs', symlinks=True,
                        copy_function=shutil.copy2)
        shutil.copy2(bundle / 'manifest.json', stage / 'bundle-manifest.json')
        shutil.copytree(installation / 'bin', stage / 'bin', symlinks=True,
                        copy_function=shutil.copy2)
        for name in INSTALL_ROOTFS_MOUNTPOINTS:
            (stage / 'rootfs' / name).mkdir(exist_ok=True)
        updated = dict(old_manifest)
        updated.update({'bundle_id': incoming['bundle_id'],
                        'installation_integrity': 'PASS',
                        'runtime_closure': new_manifest.get('runtime_closure', {}).get(
                            'status', 'PARTIAL'),
                        'update_from': current.get('bundle_id')})
        updated['paths'] = dict(old_manifest.get('paths', {}))
        updated['paths'].update({'rootfs': str(installation / 'rootfs'),
                                 'runtime': str(installation / 'runtime'),
                                 'workspace_artifacts': str(installation / 'workspace-artifacts')})
        (stage / 'installation.json').write_text(
            json.dumps(updated, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        report = verify_installation(stage)
        if report.get('integrity') != 'PASS':
            raise BundleError('staged update failed installation integrity verification')
        return stage
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def activate_staged_update(*, stage: Path, installation: Path) -> Path:
    """Swap immutable installation trees and retain the previous tree for rollback."""
    stage = Path(stage).resolve(strict=True)
    installation = Path(installation).resolve(strict=True)
    if stage.parent != installation.parent or stage == installation:
        raise BundleError('staged update must be a sibling of its installation')
    if verify_installation(stage).get('integrity') != 'PASS':
        raise BundleError('refusing to activate an unverified staged update')
    old = verify_installation(installation)
    previous = installation.with_name(f'.{installation.name}.previous-{old["bundle_id"]}')
    if previous.exists():
        raise BundleError(f'previous release already exists; preserve it before updating: {previous}')
    installation.rename(previous)
    try:
        stage.rename(installation)
        if verify_installation(installation).get('integrity') != 'PASS':
            raise BundleError('activated update failed integrity verification')
    except Exception:
        if installation.exists():
            failed = installation.with_name(f'.{installation.name}.failed-{uuid.uuid4().hex}')
            installation.rename(failed)
        previous.rename(installation)
        raise
    return previous


def restore_previous_installation(*, installation: Path, previous: Path) -> Path:
    """Restore a verified prior release without touching workspace userdata."""
    installation = Path(installation).resolve(strict=True)
    previous = Path(previous).resolve(strict=True)
    if previous.parent != installation.parent or previous == installation:
        raise BundleError('rollback tree must be a sibling of the current installation')
    current = verify_installation(installation)
    prior = verify_installation(previous)
    current_manifest = json.loads((installation / 'bundle-manifest.json').read_text())
    prior_bundle = json.loads((previous / 'bundle-manifest.json').read_text())
    current_build = current_manifest.get('android', {}).get('build_id')
    prior_build = prior_bundle.get('android', {}).get('build_id')
    if current_build and prior_build and current_build != prior_build:
        raise BundleError('rollback Android build is incompatible with current userdata')
    failed = installation.with_name(f'.{installation.name}.rolled-back-{current["bundle_id"]}')
    if failed.exists():
        failed = installation.with_name(failed.name + '-' + uuid.uuid4().hex)
    installation.rename(failed)
    try:
        previous.rename(installation)
        if verify_installation(installation).get('integrity') != 'PASS':
            raise BundleError('restored release failed integrity verification')
    except Exception:
        if installation.exists():
            installation.rename(previous)
        failed.rename(installation)
        raise
    return failed


if __name__ == '__main__' and len(sys.argv) == 4 and sys.argv[1] == '--copy-rootfs':
    _copy_tree(Path(sys.argv[2]), Path(sys.argv[3]), exclude_top=True)
