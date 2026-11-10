#!/usr/bin/env python3
"""Run an Android 16 application as a foreground AaaS session.

The M1B.8 framework runner has inherited, uncommitted experiments. This
launcher transforms a hash-checked copy rather than editing that runner.
"""

import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import signal
import shlex
import shutil
import stat
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aaas_config
import aaas_idmap
import aaas_cgroup
import aaas_bluetooth
import aaas_resources
import aaas_clipboard
import aaas_notifications
import aaas_storage
import aaas_control
import aaas_userdata
import android_workspace
import aaas_graphics


ROOT = Path(os.environ.get('AAAS_RUNTIME_ROOT',
                          str(Path(__file__).resolve().parent.parent))).resolve()
CONFIG = aaas_config.resolve_config(repository=ROOT)
WORKSPACE = CONFIG.workspace
ROOTFS = CONFIG.rootfs
DEFAULT_WORKSPACE = CONFIG.workspace

def configured_rootfs():
    # Keep legacy test and embedding callers that replace WORKSPACE coherent.
    if WORKSPACE != DEFAULT_WORKSPACE and ROOTFS == DEFAULT_WORKSPACE / 'rootfs_m1b1':
        return WORKSPACE / 'rootfs_m1b1'
    return ROOTFS
TMP = WORKSPACE / 'tmp'
RUNNER = Path(os.environ.get('AAAS_SESSION_RUNNER_BASE',
                             str(ROOT / 'scripts/aaas_session_runner_base.py'))).resolve()
PRESENTER = ROOT / 'experiments/m1a/build/wayland-host-presenter'
INPUT_ADAPTER = ROOT / 'experiments/m1c/input_adapter/build/aaas-input-adapter'
COMPOSER_PORTRAIT = TMP / 'm1b84_composer_portrait_720x1280'
COMPOSER_LANDSCAPE = TMP / 'android.hardware.graphics.composer3-service.aaas'
COMPOSER_VDISPLAY = TMP / 'm1e_composer_vdisplay_experimental'
COMPOSER_MULTI_OUTPUT = TMP / 'm1e_composer_two_output'
VDISPLAY_BROKER_DEX = TMP / 'm1e_aaas_display_broker.dex'
VDISPLAY_BROKER_RC = ROOT / 'experiments/m1e/display_broker/aaas-display-broker.rc'
VDISPLAY_SERVICES_OVERLAY = TMP / 'm1e_services_alarm_fallback.jar'
VDISPLAY_SERVICES_RECEIPT = TMP / 'm1e_services_alarm_fallback.json'
FRAMEWORK_TRANSITION_OVERLAY = TMP / 'm1e_framework_transition_input.jar'
FRAMEWORK_TRANSITION_RECEIPT = TMP / 'm1e_framework_transition_input.json'
APKTOOL = TMP / 'apktool_3.0.3.jar'
APKSIG = TMP / 'apksig-8.9.1.jar'
ANDROID_DX = WORKSPACE / 'sources/prebuilts-build-tools-qpr2/common/bin/dx'
ANDROID_ZIPALIGN = WORKSPACE / 'sources/prebuilts-build-tools-qpr2/linux-x86/bin/zipalign'
STORAGE_SCAN_KEYSTORE = TMP / 'm4-storage-probe/storage-probe.keystore'
STORAGE_SCAN_APK = TMP / 'storage-scan-helper/AaaSStorageScan.apk'
CLIPBOARD_APK = TMP / 'clipboard-ime/AaasClipboard.apk'
NOTIFICATION_APK = TMP / 'm4-notifications/AaasNotifications.apk'
CLIPBOARD_BRIDGE = ROOT / 'experiments/m4/clipboard/build/aaas-wayland-clipboard'
STORAGE_SERVICES_OVERLAY = TMP / 'm4_storage_services_overlay.jar'
STORAGE_SERVICES_RECEIPT = TMP / 'm4_storage_services_overlay.json'
FRAMEWORK_TRANSITION_BUILDER = ROOT / 'scripts/build_m1e_transition_input_overlay.py'
VDC_OVERLAY = TMP / 'm1d_vdc_overlay/vdc'
RUNNER_SHA256 = '6fabac989cb4ba26380668a68896499cee9e052b14d1acfa0e7ef488fb62694a'
SWIFTSHADER_RUNTIME_OVERLAY = TMP / 'm1e_swiftshader_fixed_notrace_v2.so'
SWIFTSHADER_RUNTIME_SHA256 = 'e42a0bd8dfe3e0eea6c3d6753f9f9fa254d348366847241ca3c7e4b9ac9affee'
SWIFTSHADER_RUNTIME_SOURCE_DIFF_SHA256 = '49c1ce42f0cb09dd69a81645c9a3bec91a390c958ac3d49ff2bd3edf4df86ece'
LMKD_DIAGNOSTIC_SHA256 = '9780759ba36e50d061064f05c77520809f3291edad6a43a1495e9d91f21d54bd'
LMKD_SOURCE_BUILT_SHA256 = 'a36135b6948342163186fe57acb9de0245fe00aeafcb9556c48a2e4c52f291ce'
COMPOSER_PORTRAIT_SHA256 = 'cd55e7418a469e84c839bfec287b1bce238a43daa28f50900acf3174c17e3a46'
VDC_OVERLAY_SHA256 = 'b91c93e100f3892880665f9b47630d1170dc1fce4ee3cf249ec8f20e583fd764'
DEFAULT_APP_PACKAGE = 'com.android.settings'
MEDIA_TEST_COMPONENTS = {
    'com.android.music': 'com.android.music/.AudioPreview',
}
APP_PACKAGE_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+')
SESSION_STATUS_VALUES = {'STARTING', 'RUNNING', 'STOPPING', 'STOPPED', 'FAILED'}
WORKSPACE_HEALTH_INTERVAL_SECONDS = 1.0


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mediaextractor_seccomp_supplement():
    """Return only the syscalls needed by the memfd ashmem compatibility shim."""
    return ('# AaaS session-local memfd-backed ashmem compatibility.\n'
            'memfd_create: 1\n'
            'ftruncate: 1\n'
            'fcntl: 1\n')


def clipboard_ime_restore_pending(path):
    """Return whether session cleanup has a saved IME choice to restore."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError:
        return False
    try:
        metadata = os.fstat(descriptor)
        return stat.S_ISREG(metadata.st_mode) and metadata.st_size > 0
    except OSError:
        return False
    finally:
        os.close(descriptor)


def validate_native_bridge_bundle(path):
    bundle = Path(path).resolve(strict=True)
    try:
        bundle.relative_to(TMP.resolve())
    except ValueError as error:
        raise ValueError('Native Bridge bundle must be inside the AaaS workspace tmp directory') from error
    sums = bundle / 'SHA256SUMS'
    if not sums.is_file():
        raise ValueError(f'Native Bridge bundle has no SHA256SUMS: {bundle}')
    entries = []
    for line in sums.read_text().splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'([0-9a-fA-F]{64})  (.+)', line)
        if not match:
            raise ValueError(f'invalid Native Bridge checksum line: {line!r}')
        digest, relative = match.groups()
        relpath = Path(relative)
        if relpath.is_absolute() or '..' in relpath.parts or not relative.startswith('system/'):
            raise ValueError(f'unsafe Native Bridge artifact path: {relative}')
        artifact = (bundle / relpath).resolve(strict=True)
        if not artifact.is_file() or bundle not in artifact.parents:
            raise ValueError(f'invalid Native Bridge artifact: {relative}')
        if sha256(artifact) != digest.lower():
            raise ValueError(f'Native Bridge checksum mismatch: {relative}')
        entries.append((relpath, artifact))
    if len(entries) != 74:
        raise ValueError(f'expected 74 pinned Native Bridge artifacts, found {len(entries)}')
    for required in ('system/lib64/libberberis_arm64.so',
                     'system/lib64/libberberis_exec_region.so',
                     'system/etc/ld.config.arm64.txt',
                     'system/lib64/arm64/libc.so'):
        if not any(str(relative) == required for relative, _ in entries):
            raise ValueError(f'Native Bridge bundle is missing {required}')
    return bundle, entries


def prepare_native_bridge_overlay(bundle, entries, session, arm64_first=False,
                                  native_exec=False, native_exec_library_apk=None):
    rootfs_system = configured_rootfs() / 'system'
    overlay_system = session / 'native_bridge_overlay/system'
    for subtree in ('bin', 'etc', 'lib64'):
        shutil.copytree(rootfs_system / subtree, overlay_system / subtree,
                        symlinks=True, copy_function=os.link)
    for relative, source in entries:
        parts = relative.parts
        target = overlay_system.joinpath(*parts[1:])
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            target.unlink()
        shutil.copy2(source, target)
        if (len(parts) == 3 and parts[0] == 'system' and parts[1] == 'bin'
                and parts[2] in {'berberis_program_runner_arm64',
                                 'berberis_program_runner_binfmt_misc_arm64'}):
            target.chmod(target.stat().st_mode | 0o111)

    executable_wrapper = None
    if native_exec:
        executable_wrapper = overlay_system / 'bin/aaas_berberis_exec_wrapper_arm64'
        executable_wrapper.write_text(
            '#!/system/bin/sh\n'
            '# Keep app ARM64 library paths away from the x86_64 runner linker.\n'
            'printf "LD_LIBRARY_PATH=%s\\nprogram=%s\\n" '
            '"$LD_LIBRARY_PATH" "$1" >> /aaas_native_exec.log\n'
            'LD_LIBRARY_PATH="/system/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
            'export LD_LIBRARY_PATH\n'
            'echo "=== ARM64 executable dispatch ===" >> /aaas_native_exec.log\n'
            'exec /system/bin/berberis_program_runner_binfmt_misc_arm64 "$@" '
            '2>>/aaas_native_exec.log\n')
        executable_wrapper.chmod(0o755)
        guest_linker_config = overlay_system / 'etc/ld.config.arm64.txt'
        linker_text = guest_linker_config.read_text()
        permitted_marker = (
            'namespace.default.permitted.paths += /system/${LIB}/arm64/bootstrap')
        if permitted_marker not in linker_text:
            raise ValueError('ARM64 guest linker config lacks expected permitted path')
        app_library_permission = 'namespace.default.permitted.paths += /data/app'
        if app_library_permission not in linker_text:
            linker_text = linker_text.replace(
                permitted_marker, permitted_marker + '\n' + app_library_permission)
            guest_linker_config.write_text(linker_text)
        for name in ('arm64_exe', 'arm64_dyn'):
            registration = overlay_system / 'etc/binfmt_misc' / name
            if not registration.is_file():
                raise ValueError(f'Native Bridge bundle is missing binfmt registration {name}')
            registration_text = registration.read_text()
            expected = '/system/bin/berberis_program_runner_binfmt_misc_arm64'
            if expected not in registration_text:
                raise ValueError(f'unrecognized ARM64 binfmt registration {name}')
            registration.write_text(registration_text.replace(
                expected, '/system/bin/aaas_berberis_exec_wrapper_arm64'))

    native_exec_library = None
    if native_exec_library_apk is not None:
        if not native_exec:
            raise ValueError('native executable libraries require native executable mode')
        apk_path = Path(native_exec_library_apk).resolve(strict=True)
        with zipfile.ZipFile(apk_path) as apk:
            try:
                library = apk.read('lib/arm64-v8a/libc++_shared.so')
            except KeyError as error:
                raise ValueError('native executable APK lacks arm64-v8a/libc++_shared.so') from error
        if not library.startswith(b'\x7fELF') or library[18:20] != (183).to_bytes(2, 'little'):
            raise ValueError('native executable libc++_shared.so is not AArch64 ELF')
        native_exec_library = overlay_system / 'lib64/arm64/libc++_shared.so'
        if native_exec_library.exists():
            raise ValueError('guest ARM64 system already contains libc++_shared.so')
        native_exec_library.write_bytes(library)
        native_exec_library.chmod(0o644)

    original_props = rootfs_system / 'build.prop'
    text = original_props.read_text()
    abi_order = 'arm64-v8a,x86_64' if arm64_first else 'x86_64,arm64-v8a'
    overrides = {
        'ro.dalvik.vm.native.bridge': 'libberberis_arm64.so',
        'ro.dalvik.vm.isa.arm64': 'x86_64',
        'ro.enable.native.bridge.exec': '1' if native_exec else '0',
        'ro.product.cpu.abilist': abi_order,
        'ro.product.cpu.abilist64': abi_order,
        'ro.system.product.cpu.abilist': abi_order,
        'ro.system.product.cpu.abilist64': abi_order,
    }
    for name, value in overrides.items():
        pattern = re.compile(rf'^{re.escape(name)}=.*$', re.MULTILINE)
        text, count = pattern.subn(f'{name}={value}', text)
        if count == 0:
            text += f'\n{name}={value}\n'
    props = overlay_system / 'build.prop'
    props.write_text(text)
    provenance = {
        'bundle': str(bundle),
        'manifest_sha256': sha256(bundle / 'MANIFEST.txt'),
        'checksum_manifest_sha256': sha256(bundle / 'SHA256SUMS'),
        'artifacts': {str(relative): sha256(source) for relative, source in entries},
        'properties': overrides,
        'executable_mode_repairs': {
            name: oct((overlay_system / name).stat().st_mode & 0o777)
            for name in ('bin/berberis_program_runner_arm64',
                         'bin/berberis_program_runner_binfmt_misc_arm64')
            if (overlay_system / name).is_file()
        },
        'executable_wrapper': ({
            'path': '/system/bin/aaas_berberis_exec_wrapper_arm64',
            'mode': oct(executable_wrapper.stat().st_mode & 0o777),
            'behavior': 'prefix /system/lib64 before app LD_LIBRARY_PATH for host runner',
        } if executable_wrapper else None),
        'guest_linker_permitted_path': '/data/app' if native_exec else None,
        'guest_exec_library': ({
            'source_apk_sha256': sha256(native_exec_library_apk),
            'target': '/system/lib64/arm64/libc++_shared.so',
            'sha256': sha256(native_exec_library),
            'scope': 'diagnostic session overlay only',
        } if native_exec_library else None),
        'integration': 'session-local hard-link merge; Android base image unchanged',
    }
    provenance_path = Path(session) / 'native-bridge-config.json'
    provenance_path.write_text(json.dumps(provenance, indent=2) + '\n')
    provenance_path.chmod(0o600)
    return session / 'native_bridge_overlay'


def prepare_diagnostic_apk_native_libraries(apk_path, session, overlay_name):
    """Stage APK native libraries in the preinstalled system-app layout.

    System APKs are not installed into /data/app, so Android cannot extract
    compressed JNI libraries during PackageManager installation. Preserve the
    original APK and provide a session-local, read-only library directory.
    """
    abi_directories = {
        'arm64-v8a': 'arm64',
        'armeabi-v7a': 'arm',
        'x86': 'x86',
        'x86_64': 'x86_64',
    }
    root = Path(session) / 'diagnostic-apk-native-libs' / overlay_name
    libraries = []
    total_size = 0
    with zipfile.ZipFile(apk_path) as apk:
        seen = set()
        for info in apk.infolist():
            if info.is_dir() or not info.filename.startswith('lib/') or not info.filename.endswith('.so'):
                continue
            parts = Path(info.filename).parts
            if (len(parts) != 3 or parts[0] != 'lib' or '..' in parts
                    or parts[1] not in abi_directories or not parts[2]
                    or '/' in parts[2] or '\\' in parts[2]):
                raise ValueError(f'unsafe or unsupported APK native-library path: {info.filename}')
            if info.filename in seen:
                raise ValueError(f'duplicate APK native-library entry: {info.filename}')
            seen.add(info.filename)
            total_size += info.file_size
            if total_size > 1024 * 1024 * 1024:
                raise ValueError('APK native libraries exceed the 1 GiB session extraction limit')
            data = apk.read(info)
            if len(data) < 20 or data[:4] != b'\x7fELF':
                raise ValueError(f'APK native library is not ELF: {info.filename}')
            elf_class, elf_data = data[4], data[5]
            machine = int.from_bytes(data[18:20], 'little' if elf_data == 1 else 'big')
            expected = {
                'arm64-v8a': (2, 183),
                'armeabi-v7a': (1, 40),
                'x86': (1, 3),
                'x86_64': (2, 62),
            }[parts[1]]
            if (elf_class, machine) != expected:
                raise ValueError(f'APK library ABI/ELF mismatch: {info.filename}')
            directory = root / abi_directories[parts[1]]
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / parts[2]
            target.write_bytes(data)
            target.chmod(0o755)
            libraries.append({
                'apk_entry': info.filename,
                'staged_path': str(target),
                'size_bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest(),
                'elf_class': elf_class,
                'elf_machine': machine,
            })
    manifest = {
        'source_apk': str(Path(apk_path).resolve()),
        'source_apk_sha256': sha256(apk_path),
        'overlay_name': overlay_name,
        'staging': 'session-local extracted libraries; source APK remains read-only and unchanged',
        'libraries': libraries,
    }
    (Path(session) / f'{overlay_name}-native-libraries.json').write_text(
        json.dumps(manifest, indent=2) + '\n')
    return root if libraries else None, manifest


def write_status_sentinel(path, value):
    """Update the bind-mounted session status file without replacing its inode."""
    if value not in SESSION_STATUS_VALUES:
        raise ValueError(f'invalid session status: {value}')
    with Path(path).open('w') as stream:
        stream.write(value + '\n')
        stream.flush()


def finalize_status_sentinel(path, failed):
    """Publish a terminal status only after session cleanup has completed."""
    value = 'FAILED' if failed else 'STOPPED'
    write_status_sentinel(path, value)
    return value


def read_presenter_slot_state(ipc, slot):
    """Read optional UI state; headless Android sessions have no presenter files."""
    try:
        return (Path(ipc) / f'app{slot}_state').read_text().strip()
    except FileNotFoundError:
        return 'NOT_PRESENT'


def read_presenter_display_id(ipc, slot):
    path = Path(ipc) / ('vdisplay_id' if slot == 1 else f'vdisplay{slot}_id')
    try:
        value = path.read_text().strip()
        return int(value) if value.isdecimal() else None
    except (OSError, ValueError):
        return None


def classify_session_failure(commands_log):
    """Classify only an emitted framework-death record, never script text."""
    try:
        contents = Path(commands_log).read_text()
    except OSError:
        return 'runtime_or_control_failure'
    if re.search(r'^AAAS_FRAMEWORK_DEATH service=surfaceflinger(?:\s|$)',
                 contents, re.MULTILINE):
        return 'surfaceflinger_died'
    return 'runtime_or_control_failure'


def request_tombstone_capture(ipc, timeout=10.0):
    """Ask the in-session Android watcher to export stable tombstones."""
    ipc = Path(ipc)
    request = ipc / 'tombstone_capture_request'
    ack = ipc / 'tombstone_capture_ack'
    temporary = request.with_name(request.name + '.tmp')
    temporary.write_text('stop\n')
    os.replace(temporary, request)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if ack.read_text().strip() == 'complete':
                return 'complete'
        except OSError:
            pass
        time.sleep(.05)
    return 'timeout'


def write_crash_artifact_manifest(session, tombstone_dir, capture_status,
                                  graphics_provenance=None):
    """Hash only exported crash artifacts and explicitly record missing data."""
    session = Path(session)
    tombstone_dir = Path(tombstone_dir)
    files = []
    if tombstone_dir.is_dir():
        for path in sorted(tombstone_dir.iterdir()):
            if path.name.startswith('.') or not path.is_file() or path.is_symlink():
                continue
            digest = hashlib.sha256()
            size = 0
            with path.open('rb') as stream:
                while True:
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    size += len(block)
                    digest.update(block)
            files.append({'name': path.name, 'size_bytes': size,
                          'sha256': digest.hexdigest()})
    if files:
        artifact_state = 'captured'
    elif capture_status == 'complete':
        artifact_state = 'missing'
    else:
        artifact_state = 'not_exported'
    related_logs = []
    for relative in ('logcat.log', 'commands.log', 'android.log', 'presenter.log',
                     'virtual-presenter.log', 'virtual-presenter2.log',
                     'ipc/display_broker.log', 'runtime-graphics-provenance.json'):
        path = session / relative
        if not path.is_file() or path.is_symlink():
            continue
        digest = hashlib.sha256()
        size = 0
        with path.open('rb') as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                digest.update(block)
        related_logs.append({'path': str(path), 'size_bytes': size,
                             'sha256': digest.hexdigest()})
    presenter_terminal = []
    for relative in ('presenter.log', 'virtual-presenter.log',
                     'virtual-presenter2.log'):
        path = session / relative
        summary = None
        if path.is_file() and not path.is_symlink():
            try:
                for line in reversed(path.read_text(errors='replace').splitlines()):
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if record.get('event') == 'summary':
                        summary = record
                        break
            except OSError:
                pass
        presenter_terminal.append({
            'log': relative,
            'state': 'summary_observed' if summary is not None else 'unknown',
            'summary': summary,
        })
    manifest = {
        'capture_status': capture_status,
        'artifact_state': artifact_state,
        'export_directory': str(tombstone_dir),
        'files': files,
        'related_logs': related_logs,
        'presenter_terminal_ownership': presenter_terminal,
        'graphics_provenance': graphics_provenance or {},
    }
    target = session / 'crash-artifact-manifest.json'
    target.write_text(json.dumps(manifest, indent=2) + '\n')
    target.chmod(0o600)
    return manifest


def collect_graphics_provenance(paths):
    """Record the selected userspace graphics binaries without changing them."""
    result = {'swiftshader_source_revision': None, 'binaries': {}}
    source = WORKSPACE / 'sources/swiftshader'
    try:
        revision = subprocess.run(
            ['git', '-C', str(source), 'rev-parse', 'HEAD'],
            check=True, capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        result['swiftshader_source_revision'] = revision
        result['swiftshader_source_dirty_files'] = subprocess.run(
            ['git', '-C', str(source), 'status', '--short'],
            check=True, capture_output=True, text=True, timeout=2,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        result['swiftshader_source_revision'] = 'unavailable'
    for key in ('AAAS_VULKAN_OVERLAY', 'AAAS_COMPOSER_OVERLAY',
                'AAAS_SERVICES_JAR_OVERLAY', 'AAAS_FRAMEWORK_JAR_OVERLAY'):
        raw = paths.get(key)
        if not raw:
            continue
        path = Path(raw)
        if not path.is_file():
            result['binaries'][key] = {'path': str(path), 'status': 'missing'}
            continue
        identity = {'path': str(path), 'sha256': sha256(path),
                    'size_bytes': path.stat().st_size}
        if key == 'AAAS_VULKAN_OVERLAY':
            try:
                notes = subprocess.run(
                    ['readelf', '-n', str(path)], check=True, capture_output=True,
                    text=True, timeout=3,
                ).stdout
                identity['build_id'] = next(
                    (line.split('Build ID:', 1)[1].strip()
                     for line in notes.splitlines() if 'Build ID:' in line),
                    'not_found',
                )
            except (OSError, subprocess.SubprocessError):
                identity['build_id'] = 'unavailable'
        result['binaries'][key] = identity
    return result


def tombstone_matches_test_process(tombstone_dir, pid):
    """Require a real text tombstone for the disposable crashing child."""
    if not pid or not pid.isdigit():
        return False
    for path in Path(tombstone_dir).glob('tombstone_*'):
        if path.suffix == '.pb' or not path.is_file() or path.is_symlink():
            continue
        try:
            content = path.read_text(errors='replace')
        except OSError:
            continue
        if f'pid: {pid}' in content and ('SIGSEGV' in content or 'signal 11' in content):
            return True
    return False


def write_session_state(session, status_path, state):
    """Publish one state transition to both the journal and Android sentinel."""
    if state in SESSION_STATUS_VALUES:
        write_status_sentinel(status_path, state)
    with (Path(session) / 'state.jsonl').open('a') as stream:
        stream.write(json.dumps({'state': state, 'monotonic_ns': time.monotonic_ns()}) + '\n')


def write_session_control(path, value):
    """Atomically publish a bounded command in this private session directory."""
    path = Path(path)
    temporary = path.with_name(path.name + f'.tmp.{os.getpid()}')
    temporary.write_text(value.rstrip() + '\n')
    os.replace(temporary, path)


def terminate_process_group(process, timeout=8):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=timeout)
        return

    # Android init is PID 1 in the private namespace and ignores default
    # termination signals. The runner can exit while init remains, so reap any
    # surviving members of this unique session group after the bounded wait.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError(f'runner anchor count {source.count(old)}: {old[:80]!r}')
    return source.replace(old, new, 1)


def copy_tree_in_user_namespace(source, destination):
    """Copy root-owned Aconfig state without changing the Android rootfs."""
    source = Path(source)
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    ready = destination.parent / f'.{destination.name}.copy-ready'
    if ready.exists():
        raise RuntimeError(f'Aconfig copy rendezvous already exists: {ready}')
    os.mkfifo(ready, 0o600)
    command = (
        f'read ready < {shlex.quote(str(ready))}; '
        f'/usr/bin/cp -a {shlex.quote(str(source))}/. {shlex.quote(str(destination))}'
    )
    process = subprocess.Popen(
        ['unshare', '-U', '-m', '-f', '/bin/sh', '-c', command],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('rootless Aconfig copy namespace exited before mapping')
            try:
                if Path(f'/proc/{process.pid}/uid_map').read_text().strip():
                    break
            except FileNotFoundError:
                pass
            time.sleep(.01)
        else:
            raise TimeoutError('rootless Aconfig copy namespace mapping timed out')
        uid_map, gid_map, _uid_range, _gid_range = aaas_idmap.map_commands(process.pid)
        subprocess.run(uid_map, check=True)
        subprocess.run(gid_map, check=True)
        with ready.open('w') as stream:
            stream.write('go\n')
        _stdout, stderr = process.communicate(timeout=15)
        if process.returncode:
            raise RuntimeError(f'rootless Aconfig copy failed: {stderr.strip()}')
    except Exception:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                process.kill()
            process.wait(timeout=5)
        raise
    finally:
        ready.unlink(missing_ok=True)


def validate_app_package(package):
    if not isinstance(package, str) or not APP_PACKAGE_PATTERN.fullmatch(package):
        raise ValueError('app package must be a dotted Android application ID')
    return package


def parse_window_size(value):
    match = re.fullmatch(r'([0-9]+)x([0-9]+)', value or '')
    if not match:
        raise argparse.ArgumentTypeError('window size must be WIDTHxHEIGHT')
    width, height = map(int, match.groups())
    if min(width, height) < 64 or max(width, height) > 1920:
        raise argparse.ArgumentTypeError('window dimensions must be between 64 and 1920')
    return width, height


def initial_window_size(orientation, requested=None):
    if requested is not None:
        return requested
    return (420, 740) if orientation == 'portrait' else (740, 420)


def parse_display_size(value):
    match = re.fullmatch(r'([0-9]+)x([0-9]+)', value or '')
    if not match:
        raise argparse.ArgumentTypeError('display size must be WIDTHxHEIGHT')
    width, height = map(int, match.groups())
    if min(width, height) < 64 or max(width, height) > 1920:
        raise argparse.ArgumentTypeError('display dimensions must be between 64 and 1920')
    return width, height


def initial_display_size(orientation, requested=None):
    if requested is not None:
        return requested
    return (720, 1280) if orientation == 'portrait' else (1280, 720)


def presenter_geometry_args(window_size, display_size):
    """Keep host toplevel geometry separate from Android framebuffer geometry."""
    return ['--width', str(window_size[0]), '--height', str(window_size[1]),
            '--display-width', str(display_size[0]),
            '--display-height', str(display_size[1])]


def emulated_storage_mount_script(sm='/system/bin/sm', toybox='/system/bin/toybox',
                                  log_path='/aaas_session_commands',
                                  escape_fstring=True, wait_seconds=30):
    """Wait for Android's emulated volume and request one mount when present.

    StorageManager can publish the emulated volume after the framework's first
    readiness signal, especially on a fresh userdata directory. Do not issue
    `sm mount emulated;0` while there is no volume record: that is not a valid
    mount target and turns a startup race into a whole-runtime failure.
    """
    sm_cmd = shlex.quote(str(sm))
    toybox_cmd = shlex.quote(str(toybox))
    log_file = shlex.quote(str(log_path))
    attempts = max(1, int(wait_seconds) // 2 + 1)
    # Parse the fixed three-column `sm list-volumes` format with toybox
    # grep/cut. This avoids nested awk quoting through the generated `sh -c`
    # wrapper and preserves the state as emitted by Android.
    volume_filter = '"^emulated;0 "'
    return (
        '    AAAS_EMULATED_STATE=\n'
        '    AAAS_EMULATED_MOUNT_REQUESTED=0\n'
        '    AAAS_STORAGE_WAIT=0\n'
        f'    while [ "$AAAS_STORAGE_WAIT" -lt {attempts} ]; do\n'
        '      AAAS_VOLUME_LIST=$(' + sm_cmd + ' list-volumes all 2>> ' + log_file + ')\n'
        '      printf "%s\\n" "$AAAS_VOLUME_LIST" >> ' + log_file + '\n'
        '      AAAS_EMULATED_STATE=$(printf "%s\\n" "$AAAS_VOLUME_LIST" | ' +
        toybox_cmd + ' grep ' + volume_filter + ' | ' + toybox_cmd +
        ' cut -d " " -f 2)\n'
        '      [ "$AAAS_EMULATED_STATE" = mounted ] && break\n'
        '      if [ -n "$AAAS_EMULATED_STATE" ] && '
        '[ "$AAAS_EMULATED_MOUNT_REQUESTED" -eq 0 ]; then\n'
        '        ' + sm_cmd + ' mount "emulated;0" >> ' + log_file + ' 2>&1\n'
        '        AAAS_EMULATED_MOUNT_REQUESTED=1\n'
        '      fi\n'
        '      ' + toybox_cmd + ' sleep 2\n'
        '      AAAS_STORAGE_WAIT=$((AAAS_STORAGE_WAIT + 1))\n'
        '    done\n'
        '    if [ "$AAAS_EMULATED_STATE" = mounted ]; then\n'
        '      echo AAAS_EMULATED_STORAGE_ALREADY_MOUNTED >> ' + log_file + '\n'
        '    fi\n'
        '    AAAS_EMULATED_STATE=$(' + sm_cmd + ' list-volumes all | ' +
        toybox_cmd + ' tee -a ' + log_file + ' | ' +
        toybox_cmd + ' grep ' + volume_filter + ' | ' + toybox_cmd +
        ' cut -d " " -f 2)\n'
        '    if [ "$AAAS_EMULATED_STATE" != mounted ]; then\n'
        '      echo "AAAS_EMULATED_STORAGE_NOT_MOUNTED state=$AAAS_EMULATED_STATE" '
        '>> ' + log_file + '\n'
        '      exit 75\n'
        '    fi\n'
    )


def presenter_sync_args(environ=None):
    """Select the measured-safe release path for a controlled dev session."""
    env = os.environ if environ is None else environ
    return ['--implicit-sync'] if env.get('AAAS_PRESENTER_IMPLICIT_SYNC') == '1' else []


def parse_display_density(value):
    try:
        density = int(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError('display density must be an integer') from error
    if not 72 <= density <= 1000:
        raise argparse.ArgumentTypeError('display density must be between 72 and 1000')
    return density


def make_session_runner(session, desktop_ime=True, app_package=DEFAULT_APP_PACKAGE,
                        experimental_virtual_display=False, app_package2=None,
                        bluetooth_policy_dir=None, input_response_probe_apk=None,
                        input_response_probe_apk2=None,
                        native_bridge_overlay=None, capture_app_tombstones=False,
                        idle_timeout_seconds=60, shared_storage_dir=None,
                        diagnostic_storage_apk=None,
                        diagnostic_storage_open=False,
                        diagnostic_storage_relaunch=False, install_apk=None,
                        uninstall_package=None, assert_package_absent=None,
                        storage_scan_apk=None, persistent_userdata_dir=None,
                        native_bridge_exec=False, clipboard_apk=None,
                        notification_apk=None, audio_hal_overlay=None,
                        audio_hal_probe=None, audio_hal_factory_probe=None,
                        audio_server_overlay=None, audiohal_overlay=None,
                        audio_ashmem_shim=None, audio_factory_compat=None,
                        audio_codec_init=None, audio_mediaextractor_init=None,
                        audio_mediaextractor_seccomp=None,
                        audio_media_file=None, audio_playback_volume_test=False,
                        headless_storage=False, max_apps=16):
    if sha256(RUNNER) != RUNNER_SHA256:
        raise RuntimeError('inherited runtime runner changed; review the session transformation')
    if headless_storage and (experimental_virtual_display or app_package2 is not None
                             or audio_media_file is not None):
        raise ValueError('headless storage mode cannot use virtual displays or media playback')
    app_package = validate_app_package(app_package)
    for package, option in ((uninstall_package, '--uninstall-package'),
                            (assert_package_absent, '--assert-package-absent')):
        if package is not None:
            validate_app_package(package)
            if not package.startswith('org.aaas.'):
                raise ValueError(f'{option} is limited to controlled org.aaas packages')
    if uninstall_package is not None and assert_package_absent is not None:
        raise ValueError('use only one package lifecycle operation per session')
    if not isinstance(idle_timeout_seconds, int) or not 1 <= idle_timeout_seconds <= 3600:
        raise ValueError('idle timeout must be between 1 and 3600 seconds')
    if app_package2 is not None:
        app_package2 = validate_app_package(app_package2)
        if app_package2 == app_package:
            raise ValueError('app2 must differ from app')
        if not experimental_virtual_display:
            raise ValueError('app2 requires --experimental-virtual-display')
    input_response_probe_binds = ""
    native_bridge_binds = ""
    diagnostic_storage_apk_bind = ""
    storage_scan_apk_bind = ""
    clipboard_apk_bind = ""
    notification_apk_bind = ""
    audio_hal_bind = ""
    audio_mediaextractor_bind = ""
    audio_hal_probe_bind = ""
    if audio_hal_probe is not None:
        audio_probe = Path(audio_hal_probe).resolve(strict=True)
        if not audio_probe.is_file():
            raise ValueError('Android audio HAL probe must be a regular file')
        audio_hal_probe_bind = (
            f'  --ro-bind {shlex.quote(str(audio_probe))} '
            '/vendor/lib64/libaaas-audio-hal-probe.so \\\n'
            f'  --ro-bind {shlex.quote(str(audio_probe))} '
            '/system/lib64/libaaas-audio-hal-probe.so \\\n'
        )
    audio_hal_factory_probe_bind = ""
    if audio_hal_factory_probe is not None:
        factory_probe = Path(audio_hal_factory_probe).resolve(strict=True)
        if not factory_probe.is_file():
            raise ValueError('Android audio factory probe must be a regular file')
        audio_hal_factory_probe_bind = (
            f'  --ro-bind {shlex.quote(str(factory_probe))} '
            '/system/lib64/libaaas-audio-factory-probe.so \\\n'
            f'  --ro-bind {shlex.quote(str(factory_probe))} '
            '/vendor/lib64/libaaas-audio-factory-probe.so \\\n'
        )
    audio_server_overlay_path = None
    if audio_server_overlay is not None:
        audio_server_overlay_path = Path(audio_server_overlay).resolve(strict=True)
        if not audio_server_overlay_path.is_file():
            raise ValueError('Android audio server overlay must be a regular file')
        if audio_hal_overlay is None:
            raise ValueError('audio server overlay requires the experimental audio HAL')
    audiohal_overlay_path = None
    if audiohal_overlay is not None:
        audiohal_overlay_path = Path(audiohal_overlay).resolve(strict=True)
        if not audiohal_overlay_path.is_file():
            raise ValueError('Android audiohal overlay must be a regular file')
        if audio_hal_overlay is None:
            raise ValueError('audiohal overlay requires the experimental audio HAL')
    if audio_hal_overlay is not None:
        audio_hal = Path(audio_hal_overlay).resolve(strict=True)
        if not audio_hal.is_file():
            raise ValueError('Android audio HAL overlay must be a regular file')
        # The Ranchu 7.1 factory special-cases "primary" and creates its
        # emulator-owned PrimaryDevice instead of using the legacy module
        # selector. This rootless runtime has no Ranchu audio transport, so
        # use the image's matching AOSP legacy HIDL adapter for this session.
        # That adapter routes every module, including primary, through
        # hw_get_module_by_class and the session-selected legacy HAL.
        audio_hidl_factory = (
            configured_rootfs() / 'vendor/lib64/hw/'
            'android.hardware.audio.legacy@7.1-impl.ranchu.so'
        )
        audio_service = configured_rootfs() / 'vendor/bin/hw/android.hardware.audio.service'
        audioserver = configured_rootfs() / 'system/bin/audioserver'
        audio_hal_bind = (
            f'  --ro-bind {shlex.quote(str(audio_hal))} '
            '/vendor/lib64/hw/audio.primary.aaas.so \\\n'
            f'  --ro-bind {shlex.quote(str(audio_hidl_factory.resolve()))} '
            '/vendor/lib64/hw/android.hardware.audio@7.1-impl.ranchu.so \\\n'
        )
        if audio_codec_init is not None:
            codec_init = Path(audio_codec_init).resolve(strict=True)
            if not codec_init.is_file():
                raise ValueError('Android software codec init configuration must be a file')
            audio_hal_bind += (
                f'  --ro-bind {shlex.quote(str(codec_init))} '
                '/vendor/etc/init/hw/init.ranchu.rc \\\n'
            )
        if audio_mediaextractor_init is not None:
            extractor_init = Path(audio_mediaextractor_init).resolve(strict=True)
            extractor_seccomp = Path(audio_mediaextractor_seccomp).resolve(strict=True)
            if (not extractor_init.is_file() or not extractor_seccomp.is_file()
                    or audio_ashmem_shim is None):
                raise ValueError('media extractor compatibility requires init, seccomp, and ashmem')
            audio_mediaextractor_bind = (
                f'  --ro-bind {shlex.quote(str(extractor_init))} '
                '/system/etc/init/mediaextractor.rc \\\n'
                f'  --ro-bind {shlex.quote(str(extractor_seccomp))} '
                '/vendor/etc/seccomp_policy/mediaextractor.policy \\\n'
            )
        if audio_ashmem_shim is not None:
            ashmem_shim = Path(audio_ashmem_shim).resolve(strict=True)
            if not ashmem_shim.is_file():
                raise ValueError('Android audio ashmem shim must be a regular file')
            audio_service_wrapper = Path(session) / 'audio-service-preload-wrapper.sh'
            audio_service_preloads = []
            if audio_hal_probe_bind:
                audio_service_preloads.append(
                    '/vendor/lib64/libaaas-audio-hal-probe.so')
            audio_service_preloads.append('/vendor/lib64/libaaas-audio-ashmem.so')
            audio_service_wrapper.write_text(
                '#!/system/bin/sh\n'
                'export LD_PRELOAD=' + ':'.join(audio_service_preloads) + '\n'
                'exec /vendor/bin/hw/android.hardware.audio.service.aaas-original "$@"\n'
            )
            audio_service_wrapper.chmod(0o755)
            audio_hal_bind += (
                f'  --ro-bind {shlex.quote(str(ashmem_shim))} '
                '/vendor/lib64/libaaas-audio-ashmem.so \\\n'
                f'  --ro-bind {shlex.quote(str(ashmem_shim))} '
                '/system/lib64/libaaas-audio-ashmem.so \\\n'
                f'  --ro-bind {shlex.quote(str(audio_service.resolve()))} '
                '/vendor/bin/hw/android.hardware.audio.service.aaas-original \\\n'
                f'  --ro-bind {shlex.quote(str(audio_service_wrapper.resolve()))} '
                '/vendor/bin/hw/android.hardware.audio.service \\\n'
            )
        if audiohal_overlay_path is not None:
            image_audiohal = (configured_rootfs() / 'system/lib64/libaudiohal.so').resolve()
            if audiohal_overlay_path != image_audiohal:
                audio_hal_bind += (
                    f'  --ro-bind {shlex.quote(str(audiohal_overlay_path))} '
                    '/system/lib64/libaudiohal.so \\\n'
                )
        if audio_hal_overlay is not None:
            audioserver_wrapper = Path(session) / 'audioserver-preload-wrapper.sh'
            if audio_factory_compat is not None:
                factory_compat = Path(audio_factory_compat).resolve(strict=True)
                if not factory_compat.is_file():
                    raise ValueError('Android audio factory compatibility library must be a file')
                audio_hal_bind += (
                    f'  --ro-bind {shlex.quote(str(factory_compat))} '
                    '/system/lib64/libaaas-audio-factory-compat.so \\\n'
                )
            audioserver_preloads = [
                *(['/system/lib64/libaaas-audio-hal-probe.so']
                  if audio_hal_probe_bind else []),
                *(['/system/lib64/libaaas-audio-factory-probe.so']
                  if audio_hal_factory_probe_bind else []),
                *(['/system/lib64/libaaas-audio-factory-compat.so']
                  if audio_factory_compat is not None else []),
                '/system/lib64/libselinux_shim.so',
            ]
            audioserver_wrapper.write_text(
                '#!/system/bin/sh\n'
                'export LD_PRELOAD=' + ':'.join(audioserver_preloads) + '\n'
                'exec /system/bin/audioserver.aaas-original "$@"\n'
            )
            audioserver_wrapper.chmod(0o755)
            selected_audio_server = (audio_server_overlay_path
                                     if audio_server_overlay_path is not None
                                     else audioserver)
            audio_hal_bind += (
                f'  --ro-bind {shlex.quote(str(selected_audio_server))} '
                '/system/bin/audioserver.aaas-original \\\n'
                f'  --ro-bind {shlex.quote(str(audioserver_wrapper.resolve()))} '
                '/system/bin/audioserver \\\n'
            )
    ordinary_apk_binds = ""
    if diagnostic_storage_apk is not None:
        storage_apk = Path(diagnostic_storage_apk).resolve(strict=True)
        if not storage_apk.is_file() or storage_apk.suffix.lower() != '.apk':
            raise ValueError('diagnostic storage package must be an APK file')
        if app_package != 'org.aaas.storagetest':
            raise ValueError('--diagnostic-storage-apk requires --app org.aaas.storagetest')
        diagnostic_storage_apk_bind = (
            f'  --ro-bind {shlex.quote(str(storage_apk))} '
            '/aaas-storage-probe.apk \\\n'
        )
    if storage_scan_apk is not None:
        scan_apk = Path(storage_scan_apk).resolve(strict=True)
        if not scan_apk.is_file() or scan_apk.suffix.lower() != '.apk':
            raise ValueError('storage scan helper must be an APK file')
        storage_scan_apk_bind = (
            f'  --ro-bind {shlex.quote(str(scan_apk))} '
            '/aaas-storage-scan-helper.apk \\\n'
        )
    if clipboard_apk is not None:
        clipboard_apk_path = Path(clipboard_apk).resolve(strict=True)
        if not clipboard_apk_path.is_file() or clipboard_apk_path.suffix.lower() != '.apk':
            raise ValueError('clipboard companion must be an APK file')
        clipboard_apk_bind = (
            f'  --ro-bind {shlex.quote(str(clipboard_apk_path))} '
            '/aaas-clipboard-ime.apk \\\n'
        )
    if notification_apk is not None:
        notification_apk_path = Path(notification_apk).resolve(strict=True)
        if not notification_apk_path.is_file() or notification_apk_path.suffix.lower() != '.apk':
            raise ValueError('notification companion must be an APK file')
        notification_apk_bind = (
            f'  --ro-bind {shlex.quote(str(notification_apk_path))} '
            '/aaas-notification-listener.apk \\\n'
        )
    if install_apk is not None:
        ordinary_apks = install_apk if isinstance(install_apk, (list, tuple)) else [install_apk]
        if not ordinary_apks:
            raise ValueError('application install input list must not be empty')
        if diagnostic_storage_apk is not None:
            raise ValueError('use either a storage probe APK or an ordinary APK')
        bind_lines = []
        for index, apk in enumerate(ordinary_apks, start=1):
            ordinary_apk = Path(apk).resolve(strict=True)
            if not ordinary_apk.is_file() or ordinary_apk.suffix.lower() != '.apk':
                raise ValueError('application install input must be an APK file')
            target = '/aaas-install-apk.apk' if index == 1 else f'/aaas-install-apk-{index}.apk'
            bind_lines.append(f'  --ro-bind {shlex.quote(str(ordinary_apk))} {target} \\\n')
        ordinary_apk_binds = ''.join(bind_lines)
    if native_bridge_overlay is not None:
        overlay = Path(native_bridge_overlay).resolve(strict=True)
        native_bridge_binds = (
            f'  --ro-bind "{overlay / "system/bin"}" /system/bin \\\n'
            f'  --ro-bind "{overlay / "system/etc"}" /system/etc \\\n'
            f'  --ro-bind "{overlay / "system/lib64"}" /system/lib64 \\\n'
            f'  --ro-bind "{overlay / "system/build.prop"}" /system/build.prop \\\n'
        )
        if native_bridge_exec:
            native_exec_log = Path(session) / 'native-exec.log'
            native_exec_log.touch(exist_ok=True)
            native_exec_log.chmod(0o666)
            native_bridge_binds += (
                f'  --bind "{native_exec_log}" /aaas_native_exec.log \\\n'
            )
    probe_apks = [(input_response_probe_apk, "AaasLatencyProbe")]
    if input_response_probe_apk2 is not None:
        if app_package2 is None:
            raise ValueError('--input-response-probe-apk2 requires --app2')
        probe_apks.append((input_response_probe_apk2, "AaasLatencyProbe2"))
    for probe_path, overlay_name in probe_apks:
        if probe_path is None:
            continue
        if not experimental_virtual_display:
            raise ValueError('--input-response-probe-apk requires --experimental-virtual-display')
        probe_apk = Path(probe_path).resolve()
        if not probe_apk.is_file():
            raise ValueError(f'input-response probe APK does not exist: {probe_apk}')
        native_lib_root, native_lib_manifest = prepare_diagnostic_apk_native_libraries(
            probe_apk, session, overlay_name)
        input_response_probe_binds += (
            f'  --dir /product/app/{overlay_name} \\\n'
            f'  --ro-bind "{probe_apk}" '
            f'/product/app/{overlay_name}/{overlay_name}.apk \\\n'
        )
        if native_lib_root is not None:
            input_response_probe_binds += (
                f'  --dir /product/app/{overlay_name}/lib \\\n'
                f'  --ro-bind "{native_lib_root}" '
                f'/product/app/{overlay_name}/lib \\\n'
            )
    timeout = '140'
    source = RUNNER.read_text()
    if shared_storage_dir is not None:
        shared_storage_dir = Path(shared_storage_dir).resolve(strict=True)
        if not shared_storage_dir.is_dir():
            raise ValueError('shared storage backing must be a directory')
        storage_bind = (
            '  --dir /data/media \\\n'
            f'  --bind {shlex.quote(str(shared_storage_dir.parent))} /data/media \\\n'
        )
        source = replace_once(
            source,
            '    runner_script = tmp_dir /',
            f'    shared_storage_bind = {storage_bind!r}\n'
            '    fuse_bind = (("  --dev-bind /dev/fuse /dev/fuse " + chr(92) + "\\n") '
            'if Path("/dev/fuse").exists() else "")\n'
            '    runner_script = tmp_dir /',
        )
        storage_anchor = '  --tmpfs /data ' + '\\\\' + '\n'
        if persistent_userdata_dir is not None:
            userdata_path = Path(persistent_userdata_dir)
            if userdata_path.is_symlink() or not userdata_path.is_dir():
                raise ValueError('persistent Android userdata must be a real directory')
            userdata_path = userdata_path.resolve(strict=True)
            storage_anchor = (
                f'  --bind {shlex.quote(str(userdata_path))} /data ' + '\\\\' + '\n')
        source = replace_once(
            source,
            '  --tmpfs /data ' + '\\\\' + '\n',
            storage_anchor + '{shared_storage_bind}',
        )
        source = replace_once(
            source,
            '    /system/bin/start vold\n',
            '    /system/bin/start storaged\n'
            '    /system/bin/start vold\n',
        )
        storage_probe = (
            '    echo "=== AAAS SHARED STORAGE INITIALIZATION ===" >> /aaas_session_commands\n'
            '    if [ -r /data/system/environ/classpath ]; then\n'
            '      while read -r AAAS_EXPORT_KIND AAAS_EXPORT_NAME AAAS_EXPORT_VALUE; do\n'
            '        if [ "$AAAS_EXPORT_KIND" = export ] && '
            '[ -n "$AAAS_EXPORT_NAME" ] && [ -n "$AAAS_EXPORT_VALUE" ]; then\n'
            '          export "$AAAS_EXPORT_NAME=$AAAS_EXPORT_VALUE"\n'
            '        fi\n'
            '      done < /data/system/environ/classpath\n'
            '      if [ -n "$BOOTCLASSPATH" ] && '
            '[ -n "$DEX2OATBOOTCLASSPATH" ]; then\n'
            '        echo AAAS_ANDROID_CLASSPATH_EXPORTS_LOADED >> /aaas_session_commands\n'
            '      else\n'
            '        echo AAAS_ANDROID_CLASSPATH_EXPORTS_INVALID >> /aaas_session_commands\n'
            '      fi\n'
            '    else\n'
            '      echo AAAS_ANDROID_CLASSPATH_EXPORTS_MISSING >> /aaas_session_commands\n'
            '    fi\n'
            '    /system/bin/cmd -l >> /aaas_session_commands 2>&1\n'
            '    /system/bin/sm list-volumes all >> /aaas_session_commands 2>&1\n'
            '    /system/bin/dumpsys mount | /system/bin/toybox grep -E '
            '"System unlocked users|CE unlocked users|emulated;0" | '
            'while read -r AAAS_STORAGE_LINE; do '
            '/system/bin/log -t AaaSStorageState "$AAAS_STORAGE_LINE"; done\n'
            # This fragment is inserted into a generated Python f-string;
            # escape its awk braces there so the resulting shell gets singles.
            + emulated_storage_mount_script()
            + '    /system/bin/dumpsys mount | /system/bin/toybox grep -E '
            + '"emulated;0|System unlocked users|CE unlocked users" >> /aaas_session_commands 2>&1\n'
            + '    /system/bin/dumpsys mount | /system/bin/toybox grep -E '
            + '"System unlocked users|CE unlocked users|emulated;0" | '
            + 'while read -r AAAS_STORAGE_LINE; do '
            + '/system/bin/log -t AaaSStorageState "$AAAS_STORAGE_LINE"; done\n'
            + '    /system/bin/dumpsys media.provider | /system/bin/toybox grep -i '
            + 'external_primary | while read -r AAAS_STORAGE_LINE; do '
            + '/system/bin/log -t AaaSStorageState "$AAAS_STORAGE_LINE"; done\n'
            + '    /system/bin/toybox mount | /system/bin/toybox grep -E '
            + '"fuse|/data/media|/storage" >> /aaas_session_commands 2>&1\n'
            + '    /system/bin/toybox ls -ld /data/media/0 '
            + '/storage/emulated/0 /storage/emulated/0/Documents >> /aaas_session_commands 2>&1\n'
        )
        if headless_storage:
            marker = f'aaas-headless-android-to-host-{Path(session).name}.txt'
            if not re.fullmatch(r'[A-Za-z0-9._-]+', marker):
                raise ValueError('invalid headless storage marker name')
            storage_probe += (
                '    AAAS_HEADLESS_MARKER=/storage/emulated/0/Download/' + marker + '\n'
                '    if [ -e "$AAAS_HEADLESS_MARKER" ]; then\n'
                '      echo "AAAS_HEADLESS_ANDROID_WRITE_COLLISION $AAAS_HEADLESS_MARKER" '
                '>> /aaas_session_commands\n'
                '    else\n'
                '      printf %s ' + shlex.quote('aaas-android-to-host-v1')
                + ' > "$AAAS_HEADLESS_MARKER" || exit 76\n'
                '      /system/bin/toybox sha256sum "$AAAS_HEADLESS_MARKER" '
                '>> /aaas_session_commands 2>&1\n'
                '      echo "AAAS_HEADLESS_ANDROID_WRITE_OK $AAAS_HEADLESS_MARKER" '
                '>> /aaas_session_commands\n'
                '    fi\n'
            )
        if audio_hal_bind:
            storage_probe += (
                '    echo "=== AAAS AUDIO SERVICES AFTER SYSTEM START ===" '
                '>> /aaas_session_commands\n'
                '    /system/bin/dumpsys media.audio_policy 2>&1 | '
                '/system/bin/toybox head -100 >> /aaas_session_commands\n'
                '    /system/bin/dumpsys media.audio_flinger 2>&1 | '
                '/system/bin/toybox head -100 >> /aaas_session_commands\n'
                '    /system/bin/logcat -d -b all -s DevicesFactoryHAL:E '
                'FactoryHal:V HAL:V 2>&1 | /system/bin/toybox tail -100 '
                '>> /aaas_session_commands\n'
            )
        if native_bridge_exec:
            storage_probe += (
                '    echo "=== ARM64 EXECUTION DISPATCH STATE ===" >> /aaas_session_commands\n'
                '    /system/bin/getprop ro.enable.native.bridge.exec >> /aaas_session_commands 2>&1\n'
                '    /system/bin/getprop ro.dalvik.vm.isa.arm64 >> /aaas_session_commands 2>&1\n'
                '    /system/bin/toybox mount | /system/bin/toybox grep binfmt_misc '
                '>> /aaas_session_commands 2>&1\n'
                '    /system/bin/toybox ls -la /proc/sys/fs/binfmt_misc '
                '>> /aaas_session_commands 2>&1\n'
                '    for AAAS_BINFMT in arm64_exe arm64_dyn; do '
                'if [ -r /proc/sys/fs/binfmt_misc/$AAAS_BINFMT ]; then '
                'echo "--- $AAAS_BINFMT ---" >> /aaas_session_commands; '
                '/system/bin/toybox cat /proc/sys/fs/binfmt_misc/$AAAS_BINFMT '
                '>> /aaas_session_commands 2>&1; fi; done\n'
            )
            if app_package is not None:
                package1 = shlex.quote(app_package)
                storage_probe += (
                    f'    echo "=== ARM64 EXECUTABLE PACKAGE {app_package} ===" '
                    '>> /aaas_session_commands\n'
                    f'    /system/bin/pm path --user 0 {package1} '
                    '>> /aaas_session_commands 2>&1\n'
                    f'    /system/bin/dumpsys package {package1} | '
                    '/system/bin/toybox grep -E "primaryCpuAbi|nativeLibraryDir" '
                    '>> /aaas_session_commands 2>&1\n'
                    '    for AAAS_NATIVE_DIR in /data/app/*/com.the412banner.bfe*/lib/arm64; do\n'
                    '      if [ -d "$AAAS_NATIVE_DIR" ]; then\n'
                    '        /system/bin/toybox ls -la "$AAAS_NATIVE_DIR" '
                    '>> /aaas_session_commands 2>&1\n'
                    '        /system/bin/toybox stat -c "%A %a %u:%g %n" '
                    '"$AAAS_NATIVE_DIR/lib7zz.so" '
                    '>> /aaas_session_commands 2>&1\n'
                    '        /system/bin/toybox stat -c "%A %a %u:%g %n" '
                    '"$AAAS_NATIVE_DIR/libc++_shared.so" '
                    '>> /aaas_session_commands 2>&1\n'
                    '      fi\n'
                    '    done\n'

                )
            if app_package2 is not None:
                package2 = shlex.quote(app_package2)
                storage_probe += (
                    f'    echo "=== ARM64 EXECUTABLE PACKAGE {app_package2} ===" '
                    '>> /aaas_session_commands\n'
                    f'    /system/bin/pm path --user 0 {package2} '
                    '>> /aaas_session_commands 2>&1\n'
                    f'    /system/bin/dumpsys package {package2} | '
                    '/system/bin/toybox grep -E "primaryCpuAbi|nativeLibraryDir" '
                    '>> /aaas_session_commands 2>&1\n'
                    f'    AAAS_APK_PATH=$(/system/bin/pm path --user 0 {package2} | '
                    '/system/bin/toybox cut -d: -f2- | /system/bin/toybox dirname)\n'
                    '    echo "APK_NATIVE_DIR=$AAAS_APK_PATH/lib/arm64" '
                    '>> /aaas_session_commands\n'
                    '    if [ -n "$AAAS_APK_PATH" ]; then\n'
                    '      /system/bin/toybox ls -la "$AAAS_APK_PATH/lib/arm64" '
                    '>> /aaas_session_commands 2>&1\n'
                    '      /system/bin/toybox stat -c "%A %a %u:%g %n" '
                    '"$AAAS_APK_PATH/lib/arm64/lib7zz.so" '
                    '>> /aaas_session_commands 2>&1\n'
                    '      /system/bin/toybox stat -c "%A %a %u:%g %n" '
                    '"$AAAS_APK_PATH/lib/arm64/libc++_shared.so" '
                    '>> /aaas_session_commands 2>&1\n'
                    '    fi\n'
                )
        if diagnostic_storage_apk is not None:
            storage_probe += (
                '    echo "=== INSTALLING ORDINARY STORAGE DIAGNOSTIC APK ===" >> /aaas_session_commands\n'
                '    STORAGE_INSTALL_OUTPUT=$(/system/bin/pm install -r '
                '/aaas-storage-probe.apk 2>&1)\n'
                '    STORAGE_INSTALL_STATUS=$?\n'
                '    /system/bin/log -t AaaSStorageInstall '
                '"status=$STORAGE_INSTALL_STATUS result=$STORAGE_INSTALL_OUTPUT"\n'
                '    if [ "$STORAGE_INSTALL_STATUS" -ne 0 ]; then\n'
                '      echo "AAAS_STORAGE_PROBE_INSTALL_FAILED $STORAGE_INSTALL_OUTPUT" '
                '>> /aaas_session_commands\n'
                '      echo FAILED > /aaas_session_status\n'
                '      exit 1\n'
                '    fi\n'
            )
        if storage_scan_apk is not None:
            storage_probe += (
                '    echo "=== INSTALLING SESSION STORAGE SCAN SERVICE ===" >> /aaas_session_commands\n'
                '    SCAN_INSTALL_OUTPUT=$(/system/bin/pm install -r '
                '/aaas-storage-scan-helper.apk 2>&1)\n'
                '    SCAN_INSTALL_STATUS=$?\n'
                '    /system/bin/log -t AaaSStorageScan '
                '"install_status=$SCAN_INSTALL_STATUS result=$SCAN_INSTALL_OUTPUT"\n'
                '    if [ "$SCAN_INSTALL_STATUS" -ne 0 ]; then\n'
                '      echo "AAAS_STORAGE_SCAN_INSTALL_FAILED $SCAN_INSTALL_OUTPUT" '
                '>> /aaas_session_commands\n'
                '      echo FAILED > /aaas_session_status\n'
                '      exit 1\n'
                '    fi\n'
            )
        if clipboard_apk is not None:
            storage_probe += (
                '    echo "=== INSTALLING OPT-IN AaaS CLIPBOARD INPUT METHOD ===" >> /aaas_session_commands\n'
                '    CLIPBOARD_INSTALL_OUTPUT=$(/system/bin/pm install -r '
                '/aaas-clipboard-ime.apk 2>&1)\n'
                '    CLIPBOARD_INSTALL_STATUS=$?\n'
                '    echo "AAAS_CLIPBOARD_INSTALL status=$CLIPBOARD_INSTALL_STATUS '
                'result=$CLIPBOARD_INSTALL_OUTPUT" >> /aaas_session_commands\n'
                '    if [ "$CLIPBOARD_INSTALL_STATUS" -ne 0 ]; then\n'
                '      echo FAILED > /aaas_session_status; exit 1\n'
                '    fi\n'
                '    CLIPBOARD_UID_OUTPUT=$(/system/bin/pm list packages -U '
                'org.aaas.clipboard 2>/dev/null)\n'
                # This shell is embedded in the generated runner's f-string.
                # Double braces here so the generated script receives literal
                # shell parameter expansion rather than Python parsing it.
                '    CLIPBOARD_ANDROID_UID=${{CLIPBOARD_UID_OUTPUT##*uid:}}\n'
                '    CLIPBOARD_ANDROID_UID=${{CLIPBOARD_ANDROID_UID%% *}}\n'
                '    case "$CLIPBOARD_ANDROID_UID" in ""|*[!0-9]*)\n'
                '      echo AAAS_CLIPBOARD_UID_UNAVAILABLE >> /aaas_session_commands\n'
                '      echo FAILED > /aaas_session_status; exit 1 ;; esac\n'
                '    echo "AAAS_CLIPBOARD_IME_INSTALLED uid=$CLIPBOARD_ANDROID_UID" '
                '>> /aaas_session_commands\n'
                '    (\n'
                '      LAST_CLIPBOARD_STATE=\n'
                '      while [ -n "$(/system/bin/toybox pidof system_server 2>/dev/null)" ]; do\n'
                '        CURRENT_CLIPBOARD_IME=$(/system/bin/settings get secure '
                'default_input_method 2>/dev/null)\n'
                '        case "$CURRENT_CLIPBOARD_IME" in\n'
                '          org.aaas.clipboard/org.aaas.clipboard.ClipboardImeService|'
                'org.aaas.clipboard/.ClipboardImeService) CLIPBOARD_ENABLED=1 ;;\n'
                '          *) CLIPBOARD_ENABLED=0 ;;\n'
                '        esac\n'
                '        CLIPBOARD_STATE="$CLIPBOARD_ANDROID_UID $CLIPBOARD_ENABLED"\n'
                '        if [ "$CLIPBOARD_STATE" != "$LAST_CLIPBOARD_STATE" ]; then\n'
                '          printf "%s\\n" "$CLIPBOARD_STATE" > '
                '/dev/aaas/.clipboard_state.tmp &&\n'
                '            /system/bin/toybox chmod 0600 /dev/aaas/.clipboard_state.tmp &&\n'
                '            /system/bin/toybox mv -f /dev/aaas/.clipboard_state.tmp '
                '/dev/aaas/clipboard_state\n'
                '          LAST_CLIPBOARD_STATE=$CLIPBOARD_STATE\n'
                '        fi\n'
                '        if [ "$CLIPBOARD_ENABLED" = 1 ] && '
                '[ -s /dev/aaas/clipboard_host_request ]; then\n'
                '          CLIPBOARD_REQUEST_ID=$(/system/bin/toybox cat '
                '/dev/aaas/clipboard_host_request 2>/dev/null)\n'
                '          : > /dev/aaas/clipboard_host_request\n'
                '          case "$CLIPBOARD_REQUEST_ID" in ""|*[!0-9]*) ;;\n'
                '            *) /system/bin/am broadcast --user 0 '
                '-n org.aaas.clipboard/.HostClipboardReceiver '
                '-a org.aaas.clipboard.SET >/dev/null 2>&1 ;;\n'
                '          esac\n'
                '        fi\n'
                '        CLIPBOARD_PROBE_MODE=$(/system/bin/toybox cat '
                '/dev/aaas/clipboard_probe_request 2>/dev/null)\n'
                '        case "$CLIPBOARD_PROBE_MODE" in\n'
                '          android-copy|host-paste)\n'
                '            : > /dev/aaas/clipboard_probe_request\n'
                '            CLIPBOARD_DISPLAY_ID=$(/system/bin/toybox cat '
                '/dev/aaas/vdisplay_id 2>/dev/null)\n'
                '            case "$CLIPBOARD_DISPLAY_ID" in ""|*[!0-9]*) '
                'CLIPBOARD_PROBE_RESULT=$(/system/bin/am start --user 0 '
                '-n org.aaas.clipboard/.ClipboardProbeActivity '
                '--es mode "$CLIPBOARD_PROBE_MODE" 2>&1) ;;\n'
                '              *) CLIPBOARD_PROBE_RESULT=$(/system/bin/am start --user 0 '
                '--display "$CLIPBOARD_DISPLAY_ID" '
                '-n org.aaas.clipboard/.ClipboardProbeActivity '
                '--es mode "$CLIPBOARD_PROBE_MODE" 2>&1) ;; esac\n'
                '            CLIPBOARD_PROBE_STATUS=$?\n'
                '            printf "%s %s %s\\n" "$CLIPBOARD_PROBE_MODE" '
                '"$CLIPBOARD_PROBE_STATUS" "$CLIPBOARD_PROBE_RESULT" '
                '> /dev/aaas/clipboard_probe_ack ;;\n'
                '          *) : ;;\n'
                '        esac\n'
                '        CLIPBOARD_SETTINGS_ACTION=$(/system/bin/toybox cat '
                '/dev/aaas/clipboard_settings_request 2>/dev/null)\n'
                '        if [ "$CLIPBOARD_SETTINGS_ACTION" = open ]; then\n'
                '          : > /dev/aaas/clipboard_settings_request\n'
                '          CLIPBOARD_DISPLAY_ID=$(/system/bin/toybox cat '
                '/dev/aaas/vdisplay_id 2>/dev/null)\n'
                '          case "$CLIPBOARD_DISPLAY_ID" in ""|*[!0-9]*)\n'
                '            /system/bin/am start -a android.settings.INPUT_METHOD_SETTINGS '
                '>/dev/null 2>&1 ;;\n'
                '            *) /system/bin/am start --display "$CLIPBOARD_DISPLAY_ID" '
                '-a android.settings.INPUT_METHOD_SETTINGS >/dev/null 2>&1 ;;\n'
                '          esac\n'
                '        elif [ "$CLIPBOARD_SETTINGS_ACTION" = use ]; then\n'
                '          : > /dev/aaas/clipboard_settings_request\n'
                '          if [ ! -s /dev/aaas/clipboard_ime_previous ]; then\n'
                '            CLIPBOARD_PREVIOUS_IME=$(/system/bin/settings get secure '
                'default_input_method 2>/dev/null)\n'
                '            CLIPBOARD_PREVIOUS_ENABLED=0\n'
                '            /system/bin/ime list -s 2>/dev/null | '
                '/system/bin/toybox grep -Fxq '
                'org.aaas.clipboard/.ClipboardImeService && '
                'CLIPBOARD_PREVIOUS_ENABLED=1\n'
                '            printf "%s %s\\n" "$CLIPBOARD_PREVIOUS_ENABLED" '
                '"$CLIPBOARD_PREVIOUS_IME" > /dev/aaas/clipboard_ime_previous\n'
                '            /system/bin/toybox chmod 0600 '
                '/dev/aaas/clipboard_ime_previous\n'
                '          fi\n'
                '          /system/bin/ime enable '
                'org.aaas.clipboard/.ClipboardImeService >/dev/null 2>&1\n'
                '          /system/bin/ime set '
                'org.aaas.clipboard/.ClipboardImeService >/dev/null 2>&1\n'
                '          echo use:$? > /dev/aaas/clipboard_ime_ack\n'
                '        elif [ "$CLIPBOARD_SETTINGS_ACTION" = restore ]; then\n'
                '          : > /dev/aaas/clipboard_settings_request\n'
                '          CLIPBOARD_RESTORE_STATUS=1\n'
                '          if [ -s /dev/aaas/clipboard_ime_previous ]; then\n'
                '            read CLIPBOARD_PREVIOUS_ENABLED CLIPBOARD_PREVIOUS_IME '
                '< /dev/aaas/clipboard_ime_previous\n'
                '            case "$CLIPBOARD_PREVIOUS_IME" in */*)\n'
                '              /system/bin/ime set "$CLIPBOARD_PREVIOUS_IME" '
                '>/dev/null 2>&1 && CLIPBOARD_RESTORE_STATUS=0 ;; esac\n'
                '            if [ "$CLIPBOARD_PREVIOUS_ENABLED" = 0 ]; then\n'
                '              /system/bin/ime disable '
                'org.aaas.clipboard/.ClipboardImeService >/dev/null 2>&1\n'
                '            fi\n'
                '            /system/bin/toybox rm -f '
                '/dev/aaas/clipboard_ime_previous\n'
                '          fi\n'
                '          echo restore:$CLIPBOARD_RESTORE_STATUS '
                '> /dev/aaas/clipboard_ime_ack\n'
                '        fi\n'
                '        /system/bin/toybox sleep 0.25\n'
                '      done\n'
                '    ) >/dev/null 2>&1 &\n'
            )
        if notification_apk is not None:
            storage_probe += (
                '    echo "=== INSTALLING USER-AUTHORIZED AaaS NOTIFICATION LISTENER ===" >> /aaas_session_commands\n'
                '    NOTIFICATION_INSTALL_OUTPUT=$(/system/bin/pm install -r /aaas-notification-listener.apk 2>&1)\n'
                '    NOTIFICATION_INSTALL_STATUS=$?\n'
                '    echo "AAAS_NOTIFICATION_INSTALL status=$NOTIFICATION_INSTALL_STATUS result=$NOTIFICATION_INSTALL_OUTPUT" >> /aaas_session_commands\n'
                '    if [ "$NOTIFICATION_INSTALL_STATUS" -ne 0 ]; then echo FAILED > /aaas_session_status; exit 1; fi\n'
                '    NOTIFICATION_UID_OUTPUT=$(/system/bin/pm list packages -U org.aaas.notifications 2>/dev/null)\n'
                '    NOTIFICATION_ANDROID_UID=${{NOTIFICATION_UID_OUTPUT##*uid:}}\n'
                '    NOTIFICATION_ANDROID_UID=${{NOTIFICATION_ANDROID_UID%% *}}\n'
                '    case "$NOTIFICATION_ANDROID_UID" in ""|*[!0-9]*) echo FAILED > /aaas_session_status; exit 1 ;; esac\n'
                '    (\n'
                '      LAST_NOTIFICATION_STATE=\n'
                '      while [ -n "$(/system/bin/toybox pidof system_server 2>/dev/null)" ]; do\n'
                '        NOTIFICATION_SETTINGS_REQUEST=$(/system/bin/toybox cat /dev/aaas/notification_settings_request 2>/dev/null)\n'
                '        case "$NOTIFICATION_SETTINGS_REQUEST" in\n'
                '          open) : > /dev/aaas/notification_settings_request; NOTIFICATION_DISPLAY_ID=$(/system/bin/toybox cat /dev/aaas/vdisplay_id 2>/dev/null); case "$NOTIFICATION_DISPLAY_ID" in ""|*[!0-9]*) /system/bin/am start -a android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS >/dev/null 2>&1 ;; *) /system/bin/am start --display "$NOTIFICATION_DISPLAY_ID" -a android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS >/dev/null 2>&1 ;; esac ;;\n'
                '          dump) : > /dev/aaas/notification_settings_request; /system/bin/uiautomator dump /dev/aaas/notifications/notification-settings.xml >> /aaas_session_commands 2>&1; NOTIFICATION_DUMP_STATUS=$?; /system/bin/toybox chmod 0644 /dev/aaas/notifications/notification-settings.xml 2>/dev/null || true; echo "dump $NOTIFICATION_DUMP_STATUS" > /dev/aaas/notification_settings_ack ;;\n'
                '          capture) : > /dev/aaas/notification_settings_request; NOTIFICATION_DISPLAY_ID=$(/system/bin/toybox cat /dev/aaas/vdisplay_id 2>/dev/null); /system/bin/screencap -p -d "$NOTIFICATION_DISPLAY_ID" /dev/aaas/notifications/notification-settings.png >> /aaas_session_commands 2>&1; NOTIFICATION_CAPTURE_STATUS=$?; /system/bin/toybox chmod 0644 /dev/aaas/notifications/notification-settings.png 2>/dev/null || true; echo "capture $NOTIFICATION_CAPTURE_STATUS" > /dev/aaas/notification_settings_ack ;;\n'
                '          tap\\ *) read NOTIFICATION_ACTION NOTIFICATION_REQUEST_ID NOTIFICATION_DISPLAY_ID NOTIFICATION_X NOTIFICATION_Y < /dev/aaas/notification_settings_request; : > /dev/aaas/notification_settings_request; NOTIFICATION_TAP_STATUS=2; case "$NOTIFICATION_REQUEST_ID" in ""|*[!0-9a-f]*) ;; *) case "$NOTIFICATION_DISPLAY_ID:$NOTIFICATION_X:$NOTIFICATION_Y" in *[!0-9:]*|:*|*:) ;; *) if [ "$NOTIFICATION_DISPLAY_ID" -le 10000 ] && [ "$NOTIFICATION_X" -le 719 ] && [ "$NOTIFICATION_Y" -le 1279 ]; then /system/bin/cmd input -d "$NOTIFICATION_DISPLAY_ID" tap "$NOTIFICATION_X" "$NOTIFICATION_Y" >/dev/null 2>&1; NOTIFICATION_TAP_STATUS=$?; fi ;; esac ;; esac; echo "$NOTIFICATION_REQUEST_ID $NOTIFICATION_TAP_STATUS" > /dev/aaas/notification_settings_ack ;;\n'
                '          *) : ;;\n'
                '        esac\n'
                '        ENABLED_LISTENERS=$(/system/bin/settings get secure enabled_notification_listeners 2>/dev/null)\n'
                '        case ":$ENABLED_LISTENERS:" in *":org.aaas.notifications/org.aaas.notifications.ForwardingListener:"*) NOTIFICATION_ENABLED=1 ;; *) NOTIFICATION_ENABLED=0 ;; esac\n'
                '        NOTIFICATION_STATE="$NOTIFICATION_ANDROID_UID $NOTIFICATION_ENABLED"\n'
                '        if [ "$NOTIFICATION_STATE" != "$LAST_NOTIFICATION_STATE" ]; then\n'
                '          printf "%s\\n" "$NOTIFICATION_STATE" > /dev/aaas/.notification_state.tmp && /system/bin/toybox chmod 0600 /dev/aaas/.notification_state.tmp && /system/bin/toybox mv -f /dev/aaas/.notification_state.tmp /dev/aaas/notification_state\n'
                '          LAST_NOTIFICATION_STATE=$NOTIFICATION_STATE\n'
                '        fi\n'
                '        /system/bin/toybox sleep 0.25\n'
                '      done\n'
                '    ) >/dev/null 2>&1 &\n'
            )
        if shared_storage_dir is not None:
            storage_probe += (
                '    echo check > /dev/aaas/storage_acl_request\n'
                '    ACL_WAIT=0\n'
                '    while [ ! -s /dev/aaas/storage_acl_ack ] && [ "$ACL_WAIT" -lt 150 ]; do\n'
                '      /system/bin/toybox sleep 0.1\n'
                '      ACL_WAIT=$((ACL_WAIT + 1))\n'
                '    done\n'
                '    ACL_RESULT=$(/system/bin/toybox cat /dev/aaas/storage_acl_ack 2>/dev/null)\n'
                '    if [ "$ACL_RESULT" != ready ]; then\n'
                '      echo "AAAS_STORAGE_ACL_PREFLIGHT_FAILED $ACL_RESULT" >> /aaas_session_commands\n'
                '      echo FAILED > /aaas_session_status\n'
                '      exit 1\n'
                '    fi\n'
                '    echo AAAS_STORAGE_ACL_PREFLIGHT_READY >> /aaas_session_commands\n'
            )
        if install_apk is not None:
            ordinary_apks = install_apk if isinstance(install_apk, (list, tuple)) else [install_apk]
            install_commands = []
            for index, _apk in enumerate(ordinary_apks, start=1):
                target = '/aaas-install-apk.apk' if index == 1 else f'/aaas-install-apk-{index}.apk'
                install_commands.extend((
                    f'    INSTALL_OUTPUT=$(/system/bin/pm install -r {target} 2>&1)\n',
                    '    INSTALL_STATUS=$?\n',
                    f'    echo "AAAS_USER_APK_INSTALL index={index} status=$INSTALL_STATUS result=$INSTALL_OUTPUT" '
                    '>> /aaas_session_commands\n',
                    '    if [ "$INSTALL_STATUS" -ne 0 ]; then echo FAILED > /aaas_session_status; exit 1; fi\n',
                ))
            storage_probe += (
                '    echo "=== INSTALLING ORDINARY USER APK(S) ===" >> /aaas_session_commands\n'
                + ''.join(install_commands)
            )
        if uninstall_package is not None:
            package = shlex.quote(uninstall_package)
            storage_probe += (
                '    echo "=== UNINSTALLING CONTROLLED USER APK ===" >> /aaas_session_commands\n'
                f'    UNINSTALL_OUTPUT=$(/system/bin/pm uninstall --user 0 {package} 2>&1)\n'
                '    UNINSTALL_STATUS=$?\n'
                f'    PACKAGE_REMAINS=$(/system/bin/pm list packages --user 0 {package} 2>&1)\n'
                f'    if [ "$UNINSTALL_STATUS" -ne 0 ] || [ "$PACKAGE_REMAINS" = "package:{uninstall_package}" ] || '
                f'[ -e /data/user/0/{uninstall_package} ]; then\n'
                '      echo "AAAS_USER_APK_UNINSTALL_FAILED status=$UNINSTALL_STATUS output=$UNINSTALL_OUTPUT remains=$PACKAGE_REMAINS" '
                '>> /aaas_session_commands\n'
                '      echo FAILED > /aaas_session_status\n'
                '      exit 1\n'
                '    fi\n'
                f'    echo "AAAS_USER_APK_UNINSTALL_OK package={uninstall_package} output=$UNINSTALL_OUTPUT package_list=$PACKAGE_REMAINS" '
                '>> /aaas_session_commands\n'
            )
        if assert_package_absent is not None:
            package = shlex.quote(assert_package_absent)
            storage_probe += (
                '    echo "=== VERIFYING CONTROLLED USER APK ABSENT ===" >> /aaas_session_commands\n'
                f'    PACKAGE_STATE=$(/system/bin/pm list packages --user 0 {package} 2>&1)\n'
                f'    if [ "$PACKAGE_STATE" = "package:{assert_package_absent}" ] || '
                f'[ -e /data/user/0/{assert_package_absent} ]; then\n'
                '      echo "AAAS_USER_APK_ABSENCE_FAILED state=$PACKAGE_STATE" >> /aaas_session_commands\n'
                '      echo FAILED > /aaas_session_status\n'
                '      exit 1\n'
                '    fi\n'
                f'    echo "AAAS_USER_APK_ABSENCE_OK package={assert_package_absent} state=$PACKAGE_STATE" '
                '>> /aaas_session_commands\n'
            )
        source = replace_once(
            source,
            '    echo "=== TESTING ACTIVITY LAUNCH (SETTINGS) ==="',
            storage_probe +
            '    echo "=== TESTING ACTIVITY LAUNCH (SETTINGS) ==="',
        )
    bluetooth_policy_bind = (
        aaas_bluetooth.policy_bind_command(bluetooth_policy_dir)
        if bluetooth_policy_dir is not None else ""
    )
    source = replace_once(
        source,
        '    wifi_feature_overlay = os.environ.get("AAAS_WIFI_FEATURE_OVERLAY")',
        '    bluetooth_policy_bind = ' + repr(bluetooth_policy_bind) + '\n'
        '    wifi_feature_overlay = os.environ.get("AAAS_WIFI_FEATURE_OVERLAY")',
    )
    source = replace_once(
        source,
        '{wifi_feature_bind}{services_jar_bind}',
        '{wifi_feature_bind}{bluetooth_policy_bind}{services_jar_bind}',
    )
    source = replace_once(
        source,
        '{mapper_bind}{allocator_bind}',
        native_bridge_binds + input_response_probe_binds + diagnostic_storage_apk_bind
        + storage_scan_apk_bind
        + clipboard_apk_bind + notification_apk_bind
        + ordinary_apk_binds
        + '{mapper_bind}{allocator_bind}',
    )
    if audio_hal_bind:
        source = replace_once(
            source,
            '{ipc_bind}',
            '{ipc_bind}' + audio_hal_bind + audio_hal_probe_bind
            + audio_hal_factory_probe_bind + audio_mediaextractor_bind,
        )
        source = replace_once(
            source,
            '    /system/bin/start vendor.audio-hal\n',
            '    /system/bin/setprop ro.hardware.audio.primary aaas\n'
            '    /system/bin/setprop log.tag.HAL VERBOSE\n'
            '    /system/bin/setprop log.tag.DevicesFactoryHAL VERBOSE\n'
            '    /system/bin/setprop log.tag.DeviceHAL VERBOSE\n'
            '    /system/bin/setprop log.tag.DevicesFactoryHalHidl VERBOSE\n'
            '    /system/bin/setprop log.tag.FactoryHal VERBOSE\n'
            '    /system/bin/setprop log.tag.AudioFlinger VERBOSE\n'
            '    /system/bin/setprop log.tag.AudioPolicyManager VERBOSE\n'
            '    echo "AAAS_AUDIO_HAL_SELECTOR=$(getprop ro.hardware.audio.primary)" '
            '>> /aaas_session_commands\n'
            '    /system/bin/start vendor.audio-hal\n'
            '    AAAS_AUDIO_FACTORY_READY=0\n'
            '    AAAS_AUDIO_FACTORY_TRIES=0\n'
            '    while [ "$AAAS_AUDIO_FACTORY_TRIES" -lt 50 ]; do\n'
            '      if /system/bin/lshal 2>/dev/null | '
            '/system/bin/toybox grep -Fq '
            '"android.hardware.audio@7.1::IDevicesFactory/default"; then\n'
            '        AAAS_AUDIO_FACTORY_READY=1\n'
            '        break\n'
            '      fi\n'
            '      /system/bin/toybox sleep 0.1\n'
            '      AAAS_AUDIO_FACTORY_TRIES=$((AAAS_AUDIO_FACTORY_TRIES + 1))\n'
            '    done\n'
            '    echo "AAAS_AUDIO_FACTORY_READY=$AAAS_AUDIO_FACTORY_READY" '
            '>> /aaas_session_commands\n',
        )
        source = replace_once(
            source,
            '    echo "AAAS_AUDIO_FACTORY_READY=$AAAS_AUDIO_FACTORY_READY" '
            '>> /aaas_session_commands\n',
            '    echo "AAAS_AUDIO_FACTORY_READY=$AAAS_AUDIO_FACTORY_READY" '
            '>> /aaas_session_commands\n'
            '    echo "AAAS_AUDIO_HW_PROPERTIES '
            'hardware=$(/system/bin/getprop ro.hardware) '
            'primary=$(/system/bin/getprop ro.hardware.audio.primary)" '
            '>> /aaas_session_commands\n'
            '    /system/bin/toybox ls -l '
            '/vendor/lib64/hw/audio.primary.aaas.so '
            '>> /aaas_session_commands 2>&1\n',
        )
        source = replace_once(
            source,
            '    /system/bin/start audioserver\n',
            '    /system/bin/start audioserver\n'
            '    /system/bin/toybox sleep 2\n'
            '    AAAS_HAL_SERVICE_PID=$(/system/bin/pidof android.hardware.audio.service 2>/dev/null)\n'
            '    AAAS_AUDIO_SERVER_PID=$(/system/bin/pidof audioserver 2>/dev/null)\n'
            '    echo "AAAS_AUDIO_PIDS hal=$AAAS_HAL_SERVICE_PID server=$AAAS_AUDIO_SERVER_PID" '
            '>> /aaas_session_commands\n'
            '    for AAAS_AUDIO_PID in $AAAS_HAL_SERVICE_PID $AAAS_AUDIO_SERVER_PID; do\n'
            '      if [ -n "$AAAS_AUDIO_PID" ]; then\n'
            '        echo "AAAS_AUDIO_PROCESS pid=$AAAS_AUDIO_PID" >> /aaas_session_commands\n'
            '        /system/bin/toybox readlink /proc/$AAAS_AUDIO_PID/ns/mnt '
            '>> /aaas_session_commands 2>&1\n'
            '        /system/bin/toybox ls -l /proc/$AAAS_AUDIO_PID/root/vendor/lib64/hw/audio.primary.aaas.so '
            '>> /aaas_session_commands 2>&1\n'
            '        /system/bin/toybox grep -F audio.primary.aaas.so /proc/$AAAS_AUDIO_PID/maps '
            '>> /aaas_session_commands 2>&1 || true\n'
            '        /system/bin/toybox grep -E "libaudiohal|libhardware.so" /proc/$AAAS_AUDIO_PID/maps '
            '>> /aaas_session_commands 2>&1 || true\n'
            '        /system/bin/toybox grep -E "libaudiohal@|audio.primary" /proc/$AAAS_AUDIO_PID/maps '
            '>> /aaas_session_commands 2>&1 || true\n'
            '      fi\n'
            '    done\n'
            '    echo "AAAS_AUDIO_DEBUG_PROPERTIES" >> /aaas_session_commands\n'
            '    /system/bin/getprop ro.hardware.audio.primary >> /aaas_session_commands\n'
            '    /system/bin/getprop log.tag.FactoryHal >> /aaas_session_commands\n'
            '    echo "AAAS_AUDIO_FACTORY_WAITED_BEFORE_AUDIOSERVER_START=1" '
            '>> /aaas_session_commands\n'
            '    /system/bin/getenforce >> /aaas_session_commands 2>&1\n'
            '    /system/bin/toybox realpath /vendor/lib64/hw/audio.primary.aaas.so '
            '>> /aaas_session_commands 2>&1\n'
            '    /system/bin/toybox ls -lZ /vendor/lib64/hw/audio.primary.aaas.so '
            '>> /aaas_session_commands 2>&1\n'
            '    echo "AAAS_AUDIO_POLICY_DUMP_BEGIN" >> /aaas_session_commands\n'
            '    /system/bin/dumpsys media.audio_policy 2>&1 | '
            '/system/bin/toybox head -100 >> /aaas_session_commands\n'
            '    echo "AAAS_AUDIO_POLICY_DUMP_END" >> /aaas_session_commands\n'
            '    /system/bin/logcat -d -b all -s DevicesFactoryHAL:E FactoryHal:V HAL:V '
            '2>&1 | /system/bin/toybox tail -100 >> /aaas_session_commands\n',
        )
    source = replace_once(
        source,
        '    ipc_dir = tmp_dir / "aaas_ipc"',
        '    vdc_overlay = Path(os.environ["AAAS_VDC_OVERLAY"])\n'
        '    vdc_bind = f\'  --ro-bind "{vdc_overlay}" /system/bin/vdc \' + chr(92) + "\\n"\n'
        '    framework_ime_overlay = Path(os.environ["AAAS_FRAMEWORK_JAR_OVERLAY"])\n'
        '    framework_ime_bind = f\'  --ro-bind "{framework_ime_overlay}" /system/framework/framework.jar \' + chr(92) + "\\n"\n'
        '    ipc_dir = tmp_dir / "aaas_ipc"',
    )
    source = replace_once(
        source,
        "  sh -c '\n    sleep() {{ /system/bin/toybox sleep \"$@\"; }}\n"
        "    /system/bin/init second_stage &\n    INIT_PID=$!\n",
        "  sh -c '\n    (\n    sleep() {{ /system/bin/toybox sleep \"$@\"; }}\n",
    )
    source = replace_once(
        source,
        '    kill -9 $INIT_PID 2>/dev/null\n  \'\n'
        'runner_status=$?\n{network_cleanup}exit "$runner_status"\n"""',
        '    :\n    ) &\n    exec /system/bin/init second_stage\n  \'\n'
        'runner_status=$?\n{network_cleanup}exit "$runner_status"\n"""',
    )
    if experimental_virtual_display:
        # Record whether this image includes the platform flag. The scoped
        # services overlay handles images whose Aconfig registry omits it.
        source = replace_once(
            source,
            '    ) &\n    exec /system/bin/init second_stage',
            '    ) &\n'
            '    AFLAGS_FILE=/tmp/aaas_aflags_list\n'
            '    /system/bin/aflags list > "$AFLAGS_FILE" 2>&1\n'
            '    AFLAGS_RC=$?\n'
            '    echo "AAAS_AFLAGS_LIST_RC=$AFLAGS_RC" >> /aaas_session_commands\n'
            '    if /system/bin/toybox grep -Fq '
            '"com.android.server.display.feature.flags.enable_display_content_mode_management" '
            '"$AFLAGS_FILE"; then\n'
            '      echo AAAS_DISPLAY_CONTENT_FLAG_PRESENT >> /aaas_session_commands\n'
            '    else\n'
            '      /system/bin/toybox grep -iE "error|not found|display_content" '
            '"$AFLAGS_FILE" >> /aaas_session_commands || true\n'
            '      echo AAAS_DISPLAY_CONTENT_FLAG_UNAVAILABLE >> /aaas_session_commands\n'
            '    fi\n'
            '    exec /system/bin/init second_stage',
        )
    tombstone_application_filter = (
        "          if ! /system/bin/toybox grep -Fq \"Cmdline: /system/bin/surfaceflinger\" \"$text_source\" && {{\n"
        "              [ -z \"$test_pid\" ] || ! /system/bin/toybox grep -Fq \"pid: $test_pid,\" \"$text_source\";\n"
        "            }}; then continue; fi\n"
    )
    tombstone_capture_worker = (
        "    (\n"
        "      /system/bin/toybox umask 077\n"
        "      /system/bin/toybox mkdir -p /data/tombstones /tombstone_export\n"
        "      aaas_export_stable_tombstones() {{\n"
        "        pending=0\n"
        "        for source in /data/tombstones/tombstone_*; do\n"
        "          [ -f \"$source\" ] || continue\n"
        "          name=${{source##*/}}\n"
        "          text_name=${{name%.pb}}\n"
        "          text_source=/data/tombstones/$text_name\n"
        "          [ -f \"$text_source\" ] || continue\n"
        "          test_pid=$(/system/bin/toybox cat /dev/aaas/tombstone_capture_test_pid 2>/dev/null)\n"
        "          if ! /system/bin/toybox grep -Fq \"Cmdline: /system/bin/surfaceflinger\" \"$text_source\" && {{\n"
        "              [ -z \"$test_pid\" ] || ! /system/bin/toybox grep -Fq \"pid: $test_pid,\" \"$text_source\";\n"
        "            }}; then continue; fi\n"
        "          signature=$(/system/bin/toybox stat -c '%s:%y' \"$source\" 2>/dev/null)\n"
        "          [ -n \"$signature\" ] || {{ pending=1; continue; }}\n"
        "          stamp=/tmp/aaas_tombstone_${{name}}.stamp\n"
        "          previous=$(/system/bin/toybox cat \"$stamp\" 2>/dev/null)\n"
        "          if [ \"$previous\" = done:\"$signature\" ]; then continue; fi\n"
        "          pending=1\n"
        "          if [ \"$previous\" = \"$signature\" ]; then\n"
        "            temporary=/tombstone_export/.${{name}}.tmp\n"
        "            if /system/bin/toybox cp \"$source\" \"$temporary\"; then\n"
        "              after=$(/system/bin/toybox stat -c '%s:%y' \"$source\" 2>/dev/null)\n"
        "              if [ \"$after\" = \"$signature\" ]; then\n"
        "                /system/bin/toybox chmod 0600 \"$temporary\"\n"
        "                /system/bin/toybox mv -f \"$temporary\" \"/tombstone_export/$name\"\n"
        "                echo done:\"$signature\" > \"$stamp\"\n"
        "              else\n"
        "                /system/bin/toybox rm -f \"$temporary\"\n"
        "              fi\n"
        "            fi\n"
        "          else\n"
        "            echo \"$signature\" > \"$stamp\"\n"
        "          fi\n"
        "        done\n"
        "        [ \"$pending\" -eq 0 ]\n"
        "      }}\n"
        "      test_started=0\n"
        "      while :; do\n"
        "        if [ \"$test_started\" -eq 0 ] && [ \"$(/system/bin/toybox cat /dev/aaas/tombstone_capture_test 2>/dev/null)\" = segv-child ]; then\n"
        "          test_started=1\n"
        "          : > /dev/aaas/tombstone_capture_test\n"
        "          /system/bin/sh -c \"kill -SEGV \\\\$\\\\$\" >/dev/null 2>&1 &\n"
        "          test_pid=$!\n"
        "          echo $test_pid > /dev/aaas/tombstone_capture_test_pid\n"
        "          wait \"$test_pid\" 2>/dev/null\n"
        "          echo $? > /dev/aaas/tombstone_capture_test_result\n"
        "        fi\n"
        "        aaas_export_stable_tombstones\n"
        "        if [ \"$(/system/bin/toybox cat /dev/aaas/tombstone_capture_request 2>/dev/null)\" = stop ]; then\n"
        "          if aaas_export_stable_tombstones; then\n"
        "            echo complete > /dev/aaas/tombstone_capture_ack\n"
        "            exit 0\n"
        "          fi\n"
        "        fi\n"
        "        /system/bin/toybox sleep 0.1\n"
        "      done\n"
        "    ) >/dev/null 2>&1 &\n"
    )
    if capture_app_tombstones:
        tombstone_capture_worker = tombstone_capture_worker.replace(
            tombstone_application_filter, '')
    source = replace_once(
        source, '    exec /system/bin/init second_stage',
        tombstone_capture_worker + '    exec /system/bin/init second_stage',
    )
    source = replace_once(
        source,
        '    ipc_dir = tmp_dir / "aaas_ipc"',
        '    session_commands = Path(os.environ["AAAS_SESSION_COMMANDS"])\n'
        '    commands_bind = (f\'  --bind "{session_commands}" '
        '/aaas_session_commands \' + chr(92) + "\\n")\n'
        '    ipc_dir = Path(os.environ["AAAS_SESSION_IPC"])',
    )
    if experimental_virtual_display:
        source = replace_once(
            source,
            '    ipc_dir = Path(os.environ["AAAS_SESSION_IPC"])',
            '    vdisplay_dex = Path(os.environ["AAAS_VDISPLAY_DEX"])\n'
            '    vdisplay_rc = Path(os.environ["AAAS_VDISPLAY_RC"])\n'
            '    vdisplay_broker_bind = (\n'
            '        f\'  --ro-bind "{vdisplay_dex}" /system/framework/aaas-display-broker.dex \' + chr(92) + "\\n"\n'
            '        f\'  --ro-bind "{vdisplay_rc}" /system/etc/init/aaas-display-broker.rc \' + chr(92) + "\\n")\n'
            '    ipc_dir = Path(os.environ["AAAS_SESSION_IPC"])',
        )
        source = replace_once(
            source,
            '    session_commands = Path(os.environ["AAAS_SESSION_COMMANDS"])',
            '    session_commands = Path(os.environ["AAAS_SESSION_COMMANDS"])\n'
            '    vdisplay_input_adapter_log = Path(\n'
            '        os.environ["AAAS_VDISPLAY_INPUT_ADAPTER_LOG"])\n'
            '    vdisplay_input_adapter_log_bind = (\n'
            '        f\'  --bind "{vdisplay_input_adapter_log}" '
            '/aaas_vdisplay_input_adapter.log \' + chr(92) + "\\n")',
        )
        if app_package2 is not None:
            source = replace_once(
                source,
                '    vdisplay_input_adapter_log_bind = (\n'
                '        f\'  --bind "{vdisplay_input_adapter_log}" '
                '/aaas_vdisplay_input_adapter.log \' + chr(92) + "\\n")',
                '    vdisplay_input_adapter_log_bind = (\n'
                '        f\'  --bind "{vdisplay_input_adapter_log}" '
                '/aaas_vdisplay_input_adapter.log \' + chr(92) + "\\n")\n'
                '    vdisplay2_input_adapter_log = Path(\n'
                '        os.environ["AAAS_VDISPLAY2_INPUT_ADAPTER_LOG"])\n'
                '    vdisplay2_input_adapter_log_bind = (\n'
                '        f\'  --bind "{vdisplay2_input_adapter_log}" '
                '/aaas_vdisplay2_input_adapter.log \' + chr(92) + "\\n")',
            )
    source = replace_once(source, '    ipc_dir.chmod(0o777)', '    ipc_dir.chmod(0o711)')
    input_adapter_log_placeholder = '{input_adapter_log_bind}'
    if experimental_virtual_display:
        input_adapter_log_placeholder += '{vdisplay_input_adapter_log_bind}'
        if app_package2 is not None:
            input_adapter_log_placeholder += '{vdisplay2_input_adapter_log_bind}'
    source = replace_once(
        source,
        '    overlay_libvulkan = tmp_dir / "libvulkan.so"',
        '    lmkd_overlay = Path(os.environ["AAAS_LMKD_OVERLAY"])\n'
        '    lmkd_bind = f\'  --ro-bind "{lmkd_overlay}" /system/bin/lmkd \\\\\\n\'\n'
        '    overlay_libvulkan = tmp_dir / "libvulkan.so"',
    )
    source = replace_once(
        source, '    overlay_angle = tmp_dir / "libGLESv2_angle.so"',
        '    session_status = Path(os.environ["AAAS_SESSION_STATUS"])\n'
        '    status_bind = f\'  --bind "{session_status}" /aaas_session_status \\\\\\n\'\n'
        '    session_logcat = Path(os.environ["AAAS_SESSION_LOGCAT"])\n'
        '    logcat_bind = f\'  --bind "{session_logcat}" /aaas_session_logcat \\\\\\n\'\n'
        '    input_adapter = Path(os.environ.get("AAAS_INPUT_ADAPTER", ""))\n'
        '    input_adapter_bind = f\'  --ro-bind "{input_adapter}" '
        '/system/bin/aaas-input-adapter \\\\\\n\' if input_adapter.is_file() else ""\n'
        '    input_adapter_log = Path(os.environ.get("AAAS_INPUT_ADAPTER_LOG", ""))\n'
        '    input_adapter_log_bind = f\'  --bind "{input_adapter_log}" '
        '/aaas_input_adapter.log \\\\\\n\' if input_adapter_log.is_file() else ""\n'
        '    overlay_angle = tmp_dir / "libGLESv2_angle.so"',
    )
    source = replace_once(
        source,
        '{mapper_bind}{allocator_bind}{composer_bind}{vulkan_bind}',
        ('{vdisplay_broker_bind}' if experimental_virtual_display else '')
        + '{vdc_bind}{framework_ime_bind}{lmkd_bind}{status_bind}{logcat_bind}{commands_bind}{input_adapter_bind}'
        + input_adapter_log_placeholder
        + '{mapper_bind}{allocator_bind}{composer_bind}{vulkan_bind}',
    )
    if experimental_virtual_display:
        # SurfaceFlinger snapshots this property while constructing its HAL
        # virtual-display ID allocator. Set it before the daemon is launched;
        # setting it after boot cannot activate the Composer3 path.
        source = replace_once(
            source,
            '    if [ "{sf_probe_env}" = "1" ]; then',
            '    /system/bin/setprop debug.sf.enable_hwc_vds 1\n'
            '    /system/bin/setprop debug.aaas.display_content_mode_management 1\n'
            '    if [ "{sf_probe_env}" = "1" ]; then',
        )
    logcat_anchor = '    /system/bin/toybox ifconfig lo 127.0.0.1 up 2>/dev/null || true'
    source = replace_once(
        source, logcat_anchor,
        '    /system/bin/logcat -b all -v threadtime >> /aaas_session_logcat 2>&1 &\n'
        + logcat_anchor,
    )
    source = replace_once(
        source,
        '    echo "=== TESTING PACKAGE MANAGER COMMAND IPC ==="',
        '    /system/bin/settings put secure show_ime_with_hard_keyboard '
        + ('0' if desktop_ime else '1') + '\n'
        + ('    /system/bin/settings put secure aaas_desktop_mode 1\n'
           if desktop_ime else
           '    /system/bin/settings delete secure aaas_desktop_mode\n')
        + '    echo "=== TESTING PACKAGE MANAGER COMMAND IPC ==="',
    )
    if experimental_virtual_display:
        source = replace_once(
            source,
            '    echo "=== STEP 1: SETTING APEX & KEYSTORE PROPS ==="',
            '    /system/bin/aflags list 2>&1 | /system/bin/toybox grep -F '
            "'enable_display_content_mode_management' >> /aaas_session_commands\n"
            '    echo "=== STEP 1: SETTING APEX & KEYSTORE PROPS ==="',
        )
    if not headless_storage and not experimental_virtual_display:
        source = replace_once(
            source,
            '    echo "=== TESTING PACKAGE MANAGER COMMAND IPC ==="',
            '    if [ -x /system/bin/aaas-input-adapter ]; then\n'
            '      /system/bin/aaas-input-adapter --socket /dev/aaas/input.sock '
            '--session-file /dev/aaas/input_session --log /aaas_input_adapter.log &\n'
            '      INPUT_ADAPTER_PID=$!\n'
            '      echo "AAAS_INPUT_ADAPTER_STARTED $INPUT_ADAPTER_PID"\n'
            '    fi\n'
            '    echo "=== TESTING PACKAGE MANAGER COMMAND IPC ==="',
        )
    if audio_media_file is None:
        app_launch_script = (
            '    echo "=== RESOLVING AND LAUNCHING ANDROID APPLICATION ==="\n'
            '    APP_COMPONENT=$(/system/bin/cmd package resolve-activity --brief --user 0 '
            '-a android.intent.action.MAIN -c android.intent.category.LAUNCHER '
            f'-p {app_package} 2>&1 | /system/bin/toybox tee -a /aaas_session_commands '
            '| /system/bin/toybox tail -n 1)\n'
            '    case "$APP_COMPONENT" in */*) ;; *) echo "No launchable activity for '
            f'{app_package}"; echo FAILED > /aaas_session_status; exit 1 ;; esac\n'
            '    /system/bin/cmd activity start-activity -W -n "$APP_COMPONENT" || '
            '/system/bin/am start -W -n "$APP_COMPONENT"'
        )
    else:
        media_relative = PurePosixPath(str(audio_media_file))
        if (media_relative.is_absolute() or not media_relative.parts
                or any(part in ('', '.', '..') for part in media_relative.parts)
                or media_relative.suffix.lower() != '.wav'
                or not re.fullmatch(r'[A-Za-z0-9_./-]+', media_relative.as_posix())):
            raise ValueError('audio media file must be a supported relative shared-media path')
        media_guest_path = '/storage/emulated/0/' + media_relative.as_posix()
        if app_package not in MEDIA_TEST_COMPONENTS:
            raise ValueError('audio media test requires a supported media application')
        media_component = MEDIA_TEST_COMPONENTS[app_package]
        media_display_option = ' --display "$VD_ID"' if experimental_virtual_display else ''
        app_launch_script = (
            '    echo "=== OPENING SHARED AUDIO THROUGH ANDROID MEDIASTORE ==="\n'
            '    /system/bin/setprop debug.stagefright.c2-poolmask 0x80000\n'
            '    echo "AAAS_CODEC2_LINEAR_POOL=$( /system/bin/getprop '
            'debug.stagefright.c2-poolmask )" >> /aaas_session_commands\n'
            '    /system/bin/start media.swcodec >> /aaas_session_commands 2>&1 || true\n'
            '    echo "AAAS_MEDIA_SWCODEC_STATE=$(/system/bin/getprop init.svc.media.swcodec)" '
            '>> /aaas_session_commands\n'
            f'    MEDIA_GUEST_PATH="{media_guest_path}"\n'
            '    /system/bin/am broadcast --user 0 '
            '-a android.intent.action.MEDIA_SCANNER_SCAN_FILE '
            '-d "file://$MEDIA_GUEST_PATH" >> /aaas_session_commands 2>&1\n'
            '    MEDIA_ID=\n'
            '    MEDIA_ATTEMPT=0\n'
            '    while [ -z "$MEDIA_ID" ] && [ "$MEDIA_ATTEMPT" -lt 20 ]; do\n'
            '      MEDIA_QUERY=$(/system/bin/content query '
            '--uri content://media/external_primary/audio/media '
            '--projection _id:_data 2>&1 | /system/bin/toybox grep -F -- '
            '"$MEDIA_GUEST_PATH" | /system/bin/toybox tee -a /aaas_session_commands)\n'
            '      MEDIA_ID=${{MEDIA_QUERY#* _id=}}\n'
            '      MEDIA_ID=${{MEDIA_ID%%,*}}\n'
            '      MEDIA_ATTEMPT=$((MEDIA_ATTEMPT + 1))\n'
            '      [ -n "$MEDIA_ID" ] || /system/bin/toybox sleep 0.5\n'
            '    done\n'
            '    case "x$MEDIA_ID" in x|x*[!0-9]*) echo "AAAS_AUDIO_MEDIA_NOT_INDEXED" '
            '>> /aaas_session_commands; echo FAILED > /aaas_session_status; exit 1 ;; esac\n'
            f'    APP_COMPONENT={media_component}\n'
            '    MEDIA_URI="content://media/external_primary/audio/media/$MEDIA_ID"\n'
            f'    if ! /system/bin/cmd activity start-activity{media_display_option} '
            '-n "$APP_COMPONENT" '
            '-a android.intent.action.VIEW -d "$MEDIA_URI" -t audio/wav '
            '--grant-read-uri-permission '
            '>> /aaas_session_commands 2>&1; then\n'
            f'      /system/bin/am start{media_display_option} -n "$APP_COMPONENT" '
            '-a android.intent.action.VIEW -d "$MEDIA_URI" -t audio/wav '
            '--grant-read-uri-permission '
            '>> /aaas_session_commands 2>&1\n'
            '    fi\n'
            + ('    echo "AAAS_ACTIVITY_LAUNCH_OK display=$VD_ID component=$APP_COMPONENT" '
               '>> /aaas_session_commands\n' if experimental_virtual_display else '') +
            f'    /system/bin/dumpsys activity activities | /system/bin/toybox grep -F '
            f'{app_package} >> /aaas_session_commands 2>&1\n'
            '    /system/bin/uiautomator dump /data/local/tmp/aaas-audio-preview.xml '
            '>> /aaas_session_commands 2>&1\n'
            '    /system/bin/toybox cat /data/local/tmp/aaas-audio-preview.xml '
            '>> /aaas_session_commands 2>&1\n'
            '    echo "AAAS_AUDIO_MEDIA_OPEN component=$APP_COMPONENT uri=$MEDIA_URI" '
            '>> /aaas_session_commands'
        )
        if audio_playback_volume_test:
            app_launch_script += (
                '\n    OLD_MEDIA_VOLUME=$(/system/bin/cmd media_session volume '
                '--stream 3 --get 2>&1)\n'
                '    OLD_MEDIA_VOLUME=${{OLD_MEDIA_VOLUME#*volume is }}\n'
                '    OLD_MEDIA_VOLUME=${{OLD_MEDIA_VOLUME%% *}}\n'
                '    case "$OLD_MEDIA_VOLUME" in *[!0-9]*|"") '
                'echo AAAS_MEDIA_VOLUME_QUERY_FAILED >> /aaas_session_commands; '
                'exit 1 ;; esac\n'
                '    echo "AAAS_MEDIA_VOLUME_INITIAL=$OLD_MEDIA_VOLUME" '
                '>> /aaas_session_commands\n'
                '    /system/bin/cmd media_session volume --stream 3 --set 15 '
                '--get >> /aaas_session_commands 2>&1\n'
                '    /system/bin/toybox sleep 5\n'
                '    /system/bin/cmd media_session volume --stream 3 --set 0 '
                '--get >> /aaas_session_commands 2>&1\n'
                '    /system/bin/toybox sleep 1\n'
                '    /system/bin/cmd media_session volume --stream 3 --set 15 '
                '--get >> /aaas_session_commands 2>&1\n'
                '    /system/bin/toybox sleep 1\n'
                '    /system/bin/cmd media_session dispatch stop '
                '>> /aaas_session_commands 2>&1\n'
                '    /system/bin/cmd media_session volume --stream 3 --set '
                '"$OLD_MEDIA_VOLUME" >> /aaas_session_commands 2>&1\n'
                '    echo "AAAS_MEDIA_VOLUME_TEST_COMPLETE '
                'restored_volume=$OLD_MEDIA_VOLUME" >> /aaas_session_commands'
            )
    source = replace_once(
        source,
        '    echo "=== TESTING ACTIVITY LAUNCH (SETTINGS) ==="\n'
        '    /system/bin/cmd activity start-activity -W -n com.android.settings/.Settings || '
        '/system/bin/am start -W -n com.android.settings/.Settings',
        app_launch_script,
    )
    if audio_hal_bind and not experimental_virtual_display and audio_media_file is None:
        source = replace_once(
            source,
            '    /system/bin/cmd activity start-activity -W -n "$APP_COMPONENT" || '
            '/system/bin/am start -W -n "$APP_COMPONENT"',
            '    /system/bin/cmd activity start-activity -W -n "$APP_COMPONENT" || '
            '/system/bin/am start -W -n "$APP_COMPONENT"\n'
            '    echo "=== AAAS AUDIO SERVICES AFTER APP LAUNCH ===" '
            '>> /aaas_session_commands\n'
            '    AAAS_AUDIO_POLICY_WAIT=0\n'
            '    AAAS_AUDIO_POLICY_DUMP=""\n'
            '    while [ "$AAAS_AUDIO_POLICY_WAIT" -lt 40 ]; do\n'
            '      AAAS_AUDIO_POLICY_DUMP=$(/system/bin/dumpsys media.audio_policy 2>/dev/null)\n'
            '      if echo "$AAAS_AUDIO_POLICY_DUMP" | /system/bin/toybox grep -Fq "AudioPolicyManager:"; then break; fi\n'
            '      /system/bin/toybox sleep 0.25\n'
            '      AAAS_AUDIO_POLICY_WAIT=$((AAAS_AUDIO_POLICY_WAIT + 1))\n'
            '    done\n'
            '    AAAS_AUDIO_MANAGER_STATE=$(echo "$AAAS_AUDIO_POLICY_DUMP" | /system/bin/toybox grep -F "AudioPolicyManager:" | /system/bin/toybox tail -1)\n'
            '    echo "AAAS_AUDIO_MANAGER_STATE=$AAAS_AUDIO_MANAGER_STATE" >> /aaas_session_commands\n'
            '    /system/bin/dumpsys media.audio_policy 2>&1 | '
            '/system/bin/toybox head -120 >> /aaas_session_commands\n'
            '    /system/bin/dumpsys media.audio_flinger 2>&1 | '
            '/system/bin/toybox head -120 >> /aaas_session_commands\n'
            '    /system/bin/logcat -d -b all -s DevicesFactoryHAL:E '
            'FactoryHal:V HAL:V 2>&1 | /system/bin/toybox tail -100 '
            '>> /aaas_session_commands',
        )
    elif audio_hal_bind and not experimental_virtual_display:
        source = replace_once(
            source,
            '    echo "AAAS_AUDIO_MEDIA_OPEN component=$APP_COMPONENT uri=$MEDIA_URI" '
            '>> /aaas_session_commands',
            '    echo "AAAS_AUDIO_MEDIA_OPEN component=$APP_COMPONENT uri=$MEDIA_URI" '
            '>> /aaas_session_commands\n'
            '    /system/bin/dumpsys media.audio_policy 2>&1 | '
            '/system/bin/toybox head -120 >> /aaas_session_commands\n'
            '    /system/bin/dumpsys media.audio_flinger 2>&1 | '
            '/system/bin/toybox head -120 >> /aaas_session_commands',
        )
    if experimental_virtual_display:
        vdisplay_launch_anchor = (
            '    echo "=== OPENING SHARED AUDIO THROUGH ANDROID MEDIASTORE ==="'
            if audio_media_file is not None else
            '    echo "=== RESOLVING AND LAUNCHING ANDROID APPLICATION ==="')
        source = replace_once(
            source,
            vdisplay_launch_anchor,
            '    echo "=== STARTING TRUSTED AaaS VIRTUAL DISPLAY BROKER ==="\n'
            '    echo AAAS_DISPLAY_BROKER_START_REQUESTED >> /aaas_session_commands\n'
            '    /system/bin/start aaas-display-broker\n'
            '    /system/bin/toybox sleep 2\n'
            '    /system/bin/getprop init.svc.aaas-display-broker >> /aaas_session_commands\n'
            '    /system/bin/toybox ps -A >> /aaas_session_commands\n'
            '    BROKER_PID=\n'
            '    for PROC in /proc/[0-9]*; do\n'
            '      if /system/bin/toybox tr "\\000" " " < "$PROC/cmdline" 2>/dev/null '
            '| /system/bin/toybox grep -q "com.aaas.display.AaasDisplayBroker"; then\n'
            '        BROKER_PID=${{PROC#/proc/}}\n'
            '        break\n'
            '      fi\n'
            '    done\n'
            '    echo "AAAS_DISPLAY_BROKER_PID=$BROKER_PID" >> /aaas_session_commands\n'
            '    if [ -n "$BROKER_PID" ]; then\n'
            '      /system/bin/toybox cat /proc/$BROKER_PID/status '
            '>> /aaas_session_commands 2>&1\n'
            '      /system/bin/toybox cat /proc/$BROKER_PID/wchan '
            '>> /aaas_session_commands 2>&1\n'
            '      /system/bin/debuggerd -b "$BROKER_PID" '
            '>> /aaas_session_commands 2>&1 || true\n'
            '    fi\n'
            '    VD_WAIT=0\n'
            '    while [ -z "$(/system/bin/toybox cat /dev/aaas/vdisplay_id 2>/dev/null)" '
            '&& [ "$VD_WAIT" -lt 30 ]; do\n'
            '      /system/bin/toybox sleep 1\n'
            '      VD_WAIT=$((VD_WAIT + 1))\n'
            '    done\n'
            '    VD_ID=$(/system/bin/toybox cat /dev/aaas/vdisplay_id 2>/dev/null | '
            '/system/bin/toybox tr -d "\\r\\n")\n'
            '    case "$VD_ID" in ""|*[!0-9]*) echo "trusted virtual display creation failed"; '
            'echo AAAS_VDISPLAY_ID_MISSING >> /aaas_session_commands; '
            '/system/bin/getprop init.svc.aaas-display-broker >> /aaas_session_commands; '
            'echo FAILED > /aaas_session_status; exit 1 ;; esac\n'
            '    echo "AAAS_TRUSTED_VDISPLAY_ID=$VD_ID"\n'
            '    /system/bin/aaas-input-adapter --socket /dev/aaas/input-vdisplay.sock '
            '--session-file /dev/aaas/input_session --log /aaas_vdisplay_input_adapter.log '
            '--focus-request /dev/aaas/vdisplay_focus_1 '
            '--focus-ack /dev/aaas/vdisplay_focus_ack_1 '
            '--display "$VD_ID" &\n'
            '    VDISPLAY_INPUT_ADAPTER_PID=$!\n'
            '    echo "AAAS_VDISPLAY_INPUT_ADAPTER_STARTED=$VDISPLAY_INPUT_ADAPTER_PID" '
            '>> /aaas_session_commands\n'
            '    ADAPTER_WAIT=0\n'
            '    while ! /system/bin/toybox grep -Fq hello '
            '/aaas_vdisplay_input_adapter.log 2>/dev/null && [ "$ADAPTER_WAIT" -lt 100 ]; do\n'
            '      /system/bin/toybox sleep 0.1\n'
            '      ADAPTER_WAIT=$((ADAPTER_WAIT + 1))\n'
            '    done\n'
            '    if ! /system/bin/toybox grep -Fq hello '
            '/aaas_vdisplay_input_adapter.log 2>/dev/null; then\n'
            '      echo AAAS_VDISPLAY_INPUT_ADAPTER_NOT_READY >> /aaas_session_commands\n'
            '      echo FAILED > /aaas_session_status\n'
            '      exit 1\n'
            '    fi\n'
            '    echo "=== RESOLVING AND LAUNCHING ANDROID APPLICATION ==="',
        )
        if audio_media_file is None:
            source = replace_once(
                source,
                '    /system/bin/cmd activity start-activity -W -n "$APP_COMPONENT" || '
                '/system/bin/am start -W -n "$APP_COMPONENT"',
                '    if ! /system/bin/cmd activity start-activity -W --display "$VD_ID" '
                '-n "$APP_COMPONENT" >> /aaas_session_commands 2>&1; then\n'
                '      if ! /system/bin/am start -W --display "$VD_ID" -n "$APP_COMPONENT" '
                '>> /aaas_session_commands 2>&1; then\n'
                '        echo "AAAS_ACTIVITY_LAUNCH_FAILED display=$VD_ID component=$APP_COMPONENT" '
                '>> /aaas_session_commands\n'
                '        echo FAILED > /aaas_session_status\n'
                '        exit 1\n'
                '      fi\n'
                '    fi\n'
                '    echo "AAAS_ACTIVITY_LAUNCH_OK display=$VD_ID component=$APP_COMPONENT" '
                '>> /aaas_session_commands',
            )
        source = replace_once(
            source,
            '    echo "AAAS_ACTIVITY_LAUNCH_OK display=$VD_ID component=$APP_COMPONENT" '
            '>> /aaas_session_commands',
            '    echo "AAAS_ACTIVITY_LAUNCH_OK display=$VD_ID component=$APP_COMPONENT" '
            '>> /aaas_session_commands\n'
            '    echo "=== SECONDARY DISPLAY TASK STATE ===" >> /aaas_session_commands\n'
            '    /system/bin/dumpsys activity activities | /system/bin/toybox grep -E '
            '"TaskInfo|displayId=$VD_ID|mResumedActivity" >> /aaas_session_commands 2>&1\n'
            '    echo "=== SECONDARY DISPLAY WINDOW POLICY ===" >> /aaas_session_commands\n'
            '    /system/bin/dumpsys window displays >> /aaas_session_commands 2>&1\n'
            '    echo "=== SECONDARY DISPLAY INPUT WINDOWS ===" >> /aaas_session_commands\n'
            '    /system/bin/dumpsys input | /system/bin/toybox grep -iE '
            '"displayId=$VD_ID|AaaS application output|com.android.settings|Taskbar|StatusBar" '
            '>> /aaas_session_commands 2>&1',
        )
        if diagnostic_storage_apk is not None:
            picker_input = (
                '      STORAGE_INPUT_OUTPUT=$(/system/bin/cmd input -d "$VD_ID" tap 160 430 2>&1)\n'
                '      STORAGE_INPUT_STATUS=$?\n'
                '      echo "AAAS_STORAGE_OPEN_SELECT status=$STORAGE_INPUT_STATUS output=$STORAGE_INPUT_OUTPUT" '
                '>> /aaas_session_commands\n'
                '      /system/bin/toybox sleep 5\n'
                '      STORAGE_INPUT_OUTPUT=$(/system/bin/cmd input -d "$VD_ID" tap 640 1240 2>&1)\n'
                '      STORAGE_INPUT_STATUS=$?\n'
                '      echo "AAAS_STORAGE_OPEN_CONFIRM status=$STORAGE_INPUT_STATUS output=$STORAGE_INPUT_OUTPUT" '
                '>> /aaas_session_commands\n'
            ) if diagnostic_storage_open else (
                '      STORAGE_INPUT_OUTPUT=$(/system/bin/cmd input -d "$VD_ID" tap 640 1240 2>&1)\n'
                '      STORAGE_INPUT_STATUS=$?\n'
                '      echo "AAAS_STORAGE_INPUT status=$STORAGE_INPUT_STATUS output=$STORAGE_INPUT_OUTPUT" '
                '>> /aaas_session_commands\n'
            )
            output_file_check = (
                '' if diagnostic_storage_open else
                '      if [ -f /storage/emulated/0/Download/aaas-storage-android-to-host.txt ]; then\n'
                '        /system/bin/toybox sha256sum '
                '/storage/emulated/0/Download/aaas-storage-android-to-host.txt '
                '>> /aaas_session_commands 2>&1\n'
                '        echo AAAS_STORAGE_PROBE_OUTPUT_FILE_PRESENT >> /aaas_session_commands\n'
                '      else\n'
                '        echo AAAS_STORAGE_PROBE_OUTPUT_FILE_MISSING >> /aaas_session_commands\n'
                '      fi\n'
            )
            media_store_query = (
                '      echo "=== MEDIASTORE SHARED-FILE QUERY ===" >> /aaas_session_commands\n'
                '      /system/bin/content query --user 0 '
                '--uri content://media/external_primary/file '
                '--projection _id:_display_name '
                '>> /aaas_session_commands 2>&1\n'
            )
            probe_replacement = ''.join([
                '    echo "AAAS_ACTIVITY_LAUNCH_OK display=$VD_ID component=$APP_COMPONENT" '
                '>> /aaas_session_commands\n'
                '    echo "=== STORAGE PROBE APP OPS ===" >> /aaas_session_commands\n'
                '    /system/bin/cmd appops get --user 0 '
                f'{app_package} >> /aaas_session_commands 2>&1\n'
                '    echo "AAAS_STORAGE_PROBE_UI_AUTOMATION_BEGIN" >> /aaas_session_commands\n'
                '    STORAGE_PICKER_WAIT=0\n'
                '    while ! /system/bin/dumpsys activity activities | '
                '/system/bin/toybox grep -Fq "com.android.documentsui/.picker.PickActivity" && '
                '[ "$STORAGE_PICKER_WAIT" -lt 30 ]; do\n'
                '      /system/bin/toybox sleep 1\n'
                '      STORAGE_PICKER_WAIT=$((STORAGE_PICKER_WAIT + 1))\n'
                '    done\n'
                '    if [ "$STORAGE_PICKER_WAIT" -lt 30 ]; then\n'
                '      # Activity visibility precedes picker layout/input readiness.\n'
                '      /system/bin/toybox sleep 3\n',
                picker_input,
                '      /system/bin/toybox sleep 5\n'
                '      /system/bin/dumpsys activity activities | '
                '/system/bin/toybox grep -E "mResumedActivity|com.android.documentsui" '
                '>> /aaas_session_commands 2>&1\n'
                '      /system/bin/logcat -d -s AaasStorageProbe:I AaasStorageProbe:E '
                '>> /aaas_session_commands 2>&1\n',
                output_file_check,
                media_store_query,
                ('      /system/bin/cmd activity force-stop --user 0 '
                 f'{app_package}\n'
                 '      echo "AAAS_STORAGE_PROBE_FORCE_STOP=$?" >> /aaas_session_commands\n'
                 '      /system/bin/toybox sleep 2\n'
                 '      /system/bin/cmd activity start-activity -W --display "$VD_ID" '
                 '-n "$APP_COMPONENT" >> /aaas_session_commands 2>&1\n'
                 '      echo "AAAS_STORAGE_PROBE_RELAUNCH=$?" >> /aaas_session_commands\n'
                 '      /system/bin/toybox sleep 3\n'
                 '      /system/bin/logcat -d -s AaasStorageProbe:I AaasStorageProbe:E '
                 '>> /aaas_session_commands 2>&1\n'
                 if diagnostic_storage_relaunch else ''),
                ('      echo AAAS_STORAGE_PROBE_OPEN_TAPS_SENT >> /aaas_session_commands\n'
                 if diagnostic_storage_open else
                 '      echo AAAS_STORAGE_PROBE_SAVE_TAP_SENT >> /aaas_session_commands\n'),
                '    else\n'
                '      echo AAAS_STORAGE_PROBE_PICKER_NOT_FOUND >> /aaas_session_commands\n'
                '    fi\n'
                '    echo "=== SECONDARY DISPLAY TASK STATE ===" >> /aaas_session_commands',
            ])
            source = replace_once(
                source,
                '    echo "AAAS_ACTIVITY_LAUNCH_OK display=$VD_ID component=$APP_COMPONENT" '
                '>> /aaas_session_commands\n'
                '    echo "=== SECONDARY DISPLAY TASK STATE ===" >> /aaas_session_commands',
                probe_replacement,
            )
        if app_package2 is not None:
            source = replace_once(
                source,
                '    echo "AAAS_ACTIVITY_LAUNCH_OK display=$VD_ID component=$APP_COMPONENT" '
                '>> /aaas_session_commands',
                '    echo "AAAS_ACTIVITY_LAUNCH_OK display=$VD_ID component=$APP_COMPONENT" '
                '>> /aaas_session_commands\n'
                '    VD2_WAIT=0\n'
                '    while [ -z "$(/system/bin/toybox cat /dev/aaas/vdisplay2_id 2>/dev/null)" '
                '&& [ "$VD2_WAIT" -lt 30 ]; do\n'
                '      /system/bin/toybox sleep 1\n'
                '      VD2_WAIT=$((VD2_WAIT + 1))\n'
                '    done\n'
                '    VD_ID2=$(/system/bin/toybox cat /dev/aaas/vdisplay2_id 2>/dev/null | '
                '/system/bin/toybox tr -d "\\r\\n")\n'
                '    case "$VD_ID2" in ""|*[!0-9]*) echo "second trusted display missing"; '
                'echo FAILED > /aaas_session_status; exit 1 ;; esac\n'
                '    /system/bin/aaas-input-adapter --socket /dev/aaas/input-vdisplay-2.sock '
                '--session-file /dev/aaas/input_session --log /aaas_vdisplay2_input_adapter.log '
                '--focus-request /dev/aaas/vdisplay_focus_2 '
                '--focus-ack /dev/aaas/vdisplay_focus_ack_2 '
                '--display "$VD_ID2" &\n'
                '    VDISPLAY2_INPUT_ADAPTER_PID=$!\n'
                '    echo "AAAS_VDISPLAY2_INPUT_ADAPTER_STARTED=$VDISPLAY2_INPUT_ADAPTER_PID" '
                '>> /aaas_session_commands\n'
                '    APP_COMPONENT2=$(/system/bin/cmd package resolve-activity --brief --user 0 '
                '-a android.intent.action.MAIN -c android.intent.category.LAUNCHER '
                f'-p {app_package2} 2>&1 | /system/bin/toybox tee -a /aaas_session_commands '
                '| /system/bin/toybox tail -n 1)\n'
                '    case "$APP_COMPONENT2" in */*) ;; *) echo "No launchable activity for '
                f'{app_package2}"; echo FAILED > /aaas_session_status; exit 1 ;; esac\n'
                '    if ! /system/bin/cmd activity start-activity -W --display "$VD_ID2" '
                '-n "$APP_COMPONENT2" >> /aaas_session_commands 2>&1; then\n'
                '      if ! /system/bin/am start -W --display "$VD_ID2" -n "$APP_COMPONENT2" '
                '>> /aaas_session_commands 2>&1; then\n'
                '        echo "AAAS_ACTIVITY2_LAUNCH_FAILED display=$VD_ID2 component=$APP_COMPONENT2" '
                '>> /aaas_session_commands; echo FAILED > /aaas_session_status; exit 1\n'
                '      fi\n'
                '    fi\n'
                '    echo "AAAS_ACTIVITY2_LAUNCH_OK display=$VD_ID2 component=$APP_COMPONENT2" '
                '>> /aaas_session_commands\n'
                '    ADAPTER2_WAIT=0\n'
                '    while ! /system/bin/toybox grep -Fq hello '
                '/aaas_vdisplay2_input_adapter.log 2>/dev/null && [ "$ADAPTER2_WAIT" -lt 100 ]; do\n'
                '      /system/bin/toybox sleep 0.1\n'
                '      ADAPTER2_WAIT=$((ADAPTER2_WAIT + 1))\n'
                '    done\n'
                '    if ! /system/bin/toybox grep -Fq hello '
                '/aaas_vdisplay2_input_adapter.log 2>/dev/null; then\n'
                '      echo AAAS_VDISPLAY2_INPUT_ADAPTER_NOT_READY >> /aaas_session_commands\n'
                '      echo FAILED > /aaas_session_status; exit 1\n'
                '    fi',
            )
    readiness_and_watch = (
        f'    APP_PACKAGE={app_package}\n'
        + (f'    APP_PACKAGE2={app_package2}\n' if app_package2 is not None else '')
        + (
        '    # Track the Android activity/task lifecycle; process names may be custom.\n'
        '    aaas_app_task_alive() {{\n'
        '      AAAS_FORCED_CLOSED=$(/system/bin/toybox cat /dev/aaas/app1_forced_closed 2>/dev/null)\n'
        '      [ "$AAAS_FORCED_CLOSED" != "$APP_PACKAGE" ] || {{ echo AAAS_TASK_CHECK_FORCED_CLOSED >> /aaas_session_commands; return 1; }}\n'
        + (
            '      AAAS_DISPLAY_ACK=$(/system/bin/toybox cat /dev/aaas/vdisplay_control_ack_1 2>/dev/null)\n'
            '      case "$AAAS_DISPLAY_ACK" in released*) echo AAAS_TASK_CHECK_DISPLAY_RELEASED >> /aaas_session_commands; return 1 ;; esac\n'
            '      [ -n "$VD_ID" ] && return 0\n'
            '      echo AAAS_TASK_CHECK_DISPLAY_ID_MISSING >> /aaas_session_commands\n'
            if experimental_virtual_display else ''
        )
        + (
        '      AAAS_TASK_DUMP=$(/system/bin/dumpsys activity activities 2>&1)\n'
        '      if printf "%s\\n" "$AAAS_TASK_DUMP" | '
        '/system/bin/toybox grep -F "$APP_PACKAGE/" >/dev/null 2>&1; then return 0; fi\n'
        '      # Android 16 omits some non-focused virtual-display tasks from the global '
        '      # ActivityTaskManager dump while WindowManager still owns their live window.\n'
        '      AAAS_WINDOW_DUMP=$(/system/bin/dumpsys window 2>&1)\n'
        '      if printf "%s\\n" "$AAAS_WINDOW_DUMP" | '
        '/system/bin/toybox grep -F "$APP_PACKAGE/" >/dev/null 2>&1; then return 0; fi\n'
        '      /system/bin/toybox sleep 0.2\n'
        '      AAAS_TASK_DUMP=$(/system/bin/dumpsys activity activities 2>&1)\n'
        '      if printf "%s\\n" "$AAAS_TASK_DUMP" | '
        '/system/bin/toybox grep -F "$APP_PACKAGE/" >/dev/null 2>&1; then\n'
        '        echo "AAAS_TASK_CHECK_TRANSIENT_MISS package=$APP_PACKAGE" '
        '>> /aaas_session_commands\n'
        '        return 0\n'
        '      fi\n'
        '      AAAS_WINDOW_DUMP=$(/system/bin/dumpsys window 2>&1)\n'
        '      if printf "%s\\n" "$AAAS_WINDOW_DUMP" | '
        '/system/bin/toybox grep -F "$APP_PACKAGE/" >/dev/null 2>&1; then\n'
        '        echo "AAAS_TASK_CHECK_WINDOW_MANAGER package=$APP_PACKAGE" '
        '>> /aaas_session_commands\n'
        '        return 0\n'
        '      fi\n'
        '      echo "AAAS_TASK_CHECK_MISSING package=$APP_PACKAGE" '
        '>> /aaas_session_commands\n'
        '      printf "%s\\n" "$AAAS_WINDOW_DUMP" | '
        '/system/bin/toybox grep -F "$APP_PACKAGE" | '
        '/system/bin/toybox tail -n 5 >> /aaas_session_commands\n'
        '      printf "%s\\n" "$AAAS_TASK_DUMP" | '
        '/system/bin/toybox grep -F "ActivityRecord" | '
        '/system/bin/toybox tail -n 5 >> /aaas_session_commands\n'
        '      return 1\n'
        '    }}\n'
        '    /system/bin/toybox sleep 3\n'
        '    if [ "$(/system/bin/getprop sys.boot_completed)" != "1" ] || '
        '! aaas_app_task_alive; then\n'
        '      echo FAILED > /aaas_session_status\n'
        '      exit 1\n'
        '    fi\n'
        '    echo RUNNING > /aaas_session_status\n'
        '    while [ "$(/system/bin/getprop sys.boot_completed)" = "1" ] && '
        '[ -n "$(/system/bin/toybox pidof system_server)" ] && '
        'aaas_app_task_alive'
        )
    )
    )
    if headless_storage:
        readiness_and_watch = (
            '    /system/bin/toybox sleep 3\n'
            '    if [ "$(/system/bin/getprop sys.boot_completed)" != "1" ] || '
            '! /system/bin/toybox pidof system_server >/dev/null || '
            '! /system/bin/toybox pidof vold >/dev/null; then\n'
            '      echo AAAS_HEADLESS_STORAGE_FRAMEWORK_NOT_READY >> /aaas_session_commands\n'
            '      echo FAILED > /aaas_session_status; exit 1\n'
            '    fi\n'
            '    echo RUNNING > /aaas_session_status\n'
            '    echo AAAS_HEADLESS_STORAGE_READY boot_completed=1 system_server=running vold=running '
            '>> /aaas_session_commands\n'
            '    while [ "$(/system/bin/getprop sys.boot_completed)" = "1" ] && '
            '[ -n "$(/system/bin/toybox pidof system_server)" ] && '
            '[ -n "$(/system/bin/toybox pidof vold)" ] && '
            '[ "$(/system/bin/toybox cat /aaas_session_status)" != STOPPING ]; do\n'
            + ('      if [ -s /dev/aaas/storage_scan_request ]; then\n'
               '        read SCAN_ID SCAN_PATH_B64 < /dev/aaas/storage_scan_request\n'
               '        : > /dev/aaas/storage_scan_request\n'
               '        SCAN_PATH=$(printf "%s" "$SCAN_PATH_B64" | '
               '/system/bin/toybox base64 -d 2>/dev/null)\n'
               '        case "$SCAN_ID" in\n'
               '          ""|*[!0-9a-f]*) echo "failed $SCAN_ID invalid_path" '
               '> /dev/aaas/storage_scan_ack ;;\n'
               '          *) case "$SCAN_PATH" in\n'
               '          /storage/emulated/0/*)\n'
               '            case "$SCAN_PATH" in *"/../"*|*"/.."|*"/Android/data"*|*"/Android/obb"*) '
               'echo "failed $SCAN_ID invalid_path" > /dev/aaas/storage_scan_ack ;;\n'
               '            *) SCAN_OUTPUT=$(/system/bin/am broadcast --include-stopped-packages '
               '--user 0 -n org.aaas.storagescan/.ScanReceiver --es path "$SCAN_PATH" '
               '--es requestId "$SCAN_ID" 2>&1); SCAN_STATUS=$?; '
               'if [ "$SCAN_STATUS" -eq 0 ]; then echo "started $SCAN_ID $SCAN_PATH" '
               '> /dev/aaas/storage_scan_ack; else echo "failed $SCAN_ID $SCAN_OUTPUT" '
               '> /dev/aaas/storage_scan_ack; fi ;;\n'
               '            esac ;;\n'
               '          *) echo "failed $SCAN_ID invalid_path" > /dev/aaas/storage_scan_ack ;;\n'
               '          esac ;;\n'
               '        esac\n'
               '      fi\n'
               '      if [ -s /dev/aaas/storage_scan_query_request ]; then\n'
               '        read QUERY_ID QUERY_URI_B64 < /dev/aaas/storage_scan_query_request\n'
               '        : > /dev/aaas/storage_scan_query_request\n'
               '        QUERY_URI=$(printf "%s" "$QUERY_URI_B64" | '
               '/system/bin/toybox base64 -d 2>/dev/null)\n'
               '        case "$QUERY_URI" in content://media/*) QUERY_OUTPUT=$('
               '/system/bin/content query --uri "$QUERY_URI" '
               '--projection _id:_display_name:_data 2>&1); QUERY_STATUS=$? ;;\n'
               '          *) QUERY_OUTPUT=invalid_content_uri; QUERY_STATUS=2 ;; esac\n'
               '        QUERY_OUTPUT_B64=$(printf "%s" "$QUERY_OUTPUT" | '
               '/system/bin/toybox base64 | /system/bin/toybox tr -d "\\\\n")\n'
               '        echo "$QUERY_ID $QUERY_STATUS $QUERY_OUTPUT_B64" '
               '> /dev/aaas/storage_scan_query_ack\n'
               '      fi\n' if storage_scan_apk is not None else '')
            + '      /system/bin/toybox sleep 1\n'
            '    done\n'
            '    echo AAAS_HEADLESS_STORAGE_FRAMEWORK_STOPPED >> /aaas_session_commands\n'
        )
    if experimental_virtual_display:
        readiness_and_watch = readiness_and_watch.replace(
            '    echo RUNNING > /aaas_session_status\n',
            '    echo RUNNING > /aaas_session_status\n'
            f'    AAAS_IDLE_TIMEOUT_SECONDS={idle_timeout_seconds}\n'
            '    AAAS_IDLE_SINCE=0\n'
            '    AAAS_SURFACEFLINGER_INITIAL_PID=$(/system/bin/toybox pidof surfaceflinger)\n'
            '    (\n'
            '      while [ "$(/system/bin/toybox cat /aaas_session_status)" = RUNNING ]; do\n'
            '        AAAS_SURFACEFLINGER_CURRENT_PID=$(/system/bin/toybox pidof surfaceflinger 2>/dev/null)\n'
            '        if [ -z "$AAAS_SURFACEFLINGER_CURRENT_PID" ] || '
            '[ "$AAAS_SURFACEFLINGER_CURRENT_PID" != "$AAAS_SURFACEFLINGER_INITIAL_PID" ]; then\n'
            '          echo "AAAS_FRAMEWORK_DEATH service=surfaceflinger initial=$AAAS_SURFACEFLINGER_INITIAL_PID current=$AAAS_SURFACEFLINGER_CURRENT_PID" '
            '>> /aaas_session_commands\n'
            '          echo FAILED > /aaas_session_status\n'
            '          for ADAPTER_PID in "$INPUT_ADAPTER_PID" '
            '"$VDISPLAY_INPUT_ADAPTER_PID" "$VDISPLAY2_INPUT_ADAPTER_PID"; do\n'
            '            case "$ADAPTER_PID" in ""|*[!0-9]*) ;; *) '
            '/system/bin/toybox kill "$ADAPTER_PID" 2>/dev/null || true ;; esac\n'
            '          done\n'
            '          echo stop > /dev/aaas/display_broker_shutdown\n'
            '          DEATH_RELEASE_WAIT=0\n'
            '          while [ "$(/system/bin/toybox cat /dev/aaas/display_broker_shutdown 2>/dev/null)" '
            '!= released ] && [ "$DEATH_RELEASE_WAIT" -lt 30 ]; do\n'
            '            /system/bin/toybox sleep 0.1\n'
            '            DEATH_RELEASE_WAIT=$((DEATH_RELEASE_WAIT + 1))\n'
            '          done\n'
            '          if [ "$(/system/bin/toybox cat /dev/aaas/display_broker_shutdown 2>/dev/null)" '
            '= released ]; then echo AAAS_BROKER_RELEASED_AFTER_FRAMEWORK_DEATH '
            '>> /aaas_session_commands; else echo AAAS_BROKER_UNAVAILABLE_AFTER_FRAMEWORK_DEATH '
            '>> /aaas_session_commands; fi\n'
            '          exit 0\n'
            '        fi\n'
            '        /system/bin/toybox sleep 0.2\n'
            '      done\n'
            '    ) >/dev/null 2>&1 &\n',
        )
    if app_package2 is not None:
        readiness_and_watch = readiness_and_watch.replace(
            '    }}\n'
            '    /system/bin/toybox sleep 3\n'
            '    if [ "$(/system/bin/getprop sys.boot_completed)" != "1" ] || '
            '! aaas_app_task_alive; then\n',
            '    }}\n'
            '    aaas_app2_task_alive() {{\n'
            '      [ "$(/system/bin/toybox cat /dev/aaas/app2_forced_closed 2>/dev/null)" '
            '!= "$APP_PACKAGE2" ] || return 1\n'
            + (
                '      case "$(/system/bin/toybox cat /dev/aaas/vdisplay_control_ack_2 2>/dev/null)" in released*) return 1 ;; esac\n'
                '      [ -n "$VD_ID2" ] && return 0\n'
                if experimental_virtual_display else ''
            )
            + ('      /system/bin/dumpsys activity activities | '
            '/system/bin/toybox grep -F "u0 $APP_PACKAGE2/" >/dev/null 2>&1\n'
            )
            + '    }}\n'
            '    /system/bin/toybox sleep 3\n'
            '    if [ "$(/system/bin/getprop sys.boot_completed)" != "1" ] || '
            '! aaas_app_task_alive || ! aaas_app2_task_alive; then\n'
        )
        readiness_and_watch = readiness_and_watch.replace(
            '&& aaas_app_task_alive',
            '&& [ "$(/system/bin/toybox cat /aaas_session_status)" != "STOPPING" ]', 1)
    elif experimental_virtual_display:
        # Dynamic launches use slot 2 even when no second app was supplied at
        # startup. Define the matching liveness predicate for that case too;
        # without it the shell's watcher reports every dynamically launched
        # second-window task as closed and immediately tears its display down.
        app2_watch = (
            '    aaas_app2_task_alive() {{\n'
            '      [ -n "$APP_PACKAGE2" ] || return 1\n'
            '      [ "$(/system/bin/toybox cat /dev/aaas/app2_forced_closed 2>/dev/null)" '
            '!= "$APP_PACKAGE2" ] || return 1\n'
            '      case "$(/system/bin/toybox cat /dev/aaas/vdisplay_control_ack_2 '
            '2>/dev/null)" in released*) return 1 ;; esac\n'
            '      [ -n "$VD_ID2" ] && return 0\n'
            '      /system/bin/dumpsys activity activities | '
            '/system/bin/toybox grep -F "u0 $APP_PACKAGE2/" >/dev/null 2>&1\n'
            '    }}\n')
        readiness_and_watch = readiness_and_watch.replace(
            '    while [ "$(/system/bin/getprop sys.boot_completed)" = "1" ]',
            app2_watch +
            '    while [ "$(/system/bin/getprop sys.boot_completed)" = "1" ]', 1)
    if experimental_virtual_display:
        readiness_and_watch += (
            ' && [ "$(/system/bin/toybox cat /aaas_session_status)" != "STOPPING" ]; do\n'
        )
        readiness_and_watch += (
            '      if [ -z "$(/system/bin/toybox pidof surfaceflinger 2>/dev/null)" ]; then\n'
            '        echo AAAS_FRAMEWORK_DEATH service=surfaceflinger >> /aaas_session_commands\n'
            '        echo FAILED > /aaas_session_status\n'
            '        for ADAPTER_PID in "$INPUT_ADAPTER_PID" '
            '"$VDISPLAY_INPUT_ADAPTER_PID" "$VDISPLAY2_INPUT_ADAPTER_PID"; do\n'
            '          case "$ADAPTER_PID" in ""|*[!0-9]*) ;; *) '
            '/system/bin/toybox kill "$ADAPTER_PID" 2>/dev/null || true ;; esac\n'
            '        done\n'
            '        echo stop > /dev/aaas/display_broker_shutdown\n'
            '        DEATH_RELEASE_WAIT=0\n'
            '        while [ "$(/system/bin/toybox cat /dev/aaas/display_broker_shutdown 2>/dev/null)" '
            '!= released ] && [ "$DEATH_RELEASE_WAIT" -lt 30 ]; do\n'
            '          /system/bin/toybox sleep 0.1\n'
            '          DEATH_RELEASE_WAIT=$((DEATH_RELEASE_WAIT + 1))\n'
            '        done\n'
            '        if [ "$(/system/bin/toybox cat /dev/aaas/display_broker_shutdown 2>/dev/null)" '
            '= released ]; then echo AAAS_BROKER_RELEASED_AFTER_FRAMEWORK_DEATH '
            '>> /aaas_session_commands; else echo AAAS_BROKER_UNAVAILABLE_AFTER_FRAMEWORK_DEATH '
            '>> /aaas_session_commands; fi\n'
            '        break\n'
            '      fi\n'
        )
        if storage_scan_apk is not None:
            readiness_and_watch += (
                '      if [ -s /dev/aaas/storage_scan_request ]; then\n'
                '        read SCAN_ID SCAN_PATH_B64 < /dev/aaas/storage_scan_request\n'
                '        : > /dev/aaas/storage_scan_request\n'
                '        case "$SCAN_ID" in ""|*[!0-9a-f]*) SCAN_ID=invalid ;; esac\n'
                '        SCAN_PATH=$(printf "%s" "$SCAN_PATH_B64" | '
                '/system/bin/toybox base64 -d 2>/dev/null)\n'
                '        case "$SCAN_PATH" in\n'
                '          /storage/emulated/0/*)\n'
                '            case "$SCAN_PATH" in *"/../"*|*"/.."|*"/Android/data/"*|'
                '*"/Android/data"|*"/Android/obb/"*|*"/Android/obb")\n'
                '              echo "failed $SCAN_ID invalid_path" > /dev/aaas/storage_scan_ack ;;\n'
                '            *)\n'
                '              SCAN_SERVICE_OUTPUT=$(/system/bin/am broadcast '
                '--include-stopped-packages --user 0 '
                '-n org.aaas.storagescan/.ScanReceiver '
                '--es path "$SCAN_PATH" --es requestId "$SCAN_ID" 2>&1)\n'
                '              SCAN_SERVICE_STATUS=$?\n'
                '              echo "AAAS_STORAGE_SCAN_SERVICE status=$SCAN_SERVICE_STATUS output=$SCAN_SERVICE_OUTPUT" '
                '>> /aaas_session_commands\n'
                '              if [ "$SCAN_SERVICE_STATUS" -eq 0 ]; then\n'
                '                echo "started $SCAN_ID $SCAN_PATH" '
                '> /dev/aaas/storage_scan_ack\n'
                '              else\n'
                '                echo "failed $SCAN_ID launch $SCAN_SERVICE_OUTPUT" '
                '> /dev/aaas/storage_scan_ack\n'
                '              fi\n'
                '              ;;\n'
                '            esac\n'
                '            ;;\n'
                '          *) echo "failed $SCAN_ID invalid_path" '
                '> /dev/aaas/storage_scan_ack ;;\n'
                '        esac\n'
                '      fi\n'
                '      if [ -s /dev/aaas/storage_scan_query_request ]; then\n'
                '        read QUERY_ID QUERY_URI_B64 < /dev/aaas/storage_scan_query_request\n'
                '        : > /dev/aaas/storage_scan_query_request\n'
                '        QUERY_URI=$(printf "%s" "$QUERY_URI_B64" | '
                '/system/bin/toybox base64 -d 2>/dev/null)\n'
                '        case "$QUERY_URI" in content://media/*)\n'
                '          QUERY_OUTPUT=$(/system/bin/content query '
                '--uri "$QUERY_URI" --projection _id:_display_name:_data 2>&1)\n'
                '          QUERY_STATUS=$? ;;\n'
                '          *) QUERY_OUTPUT=invalid_content_uri; QUERY_STATUS=2 ;;\n'
                '        esac\n'
                '        QUERY_OUTPUT_B64=$(printf "%s" "$QUERY_OUTPUT" | '
                '/system/bin/toybox base64 | /system/bin/toybox tr -d "\\n")\n'
                '        echo "$QUERY_ID $QUERY_STATUS $QUERY_OUTPUT_B64" '
                '> /dev/aaas/storage_scan_query_ack\n'
                '      fi\n'
                '      if [ -s /dev/aaas/catalog_request ]; then\n'
                '        read CATALOG_ID < /dev/aaas/catalog_request\n'
                '        : > /dev/aaas/catalog_request\n'
                '        case "$CATALOG_ID" in ""|*[!0-9a-f]*) CATALOG_ID=invalid ;; esac\n'
                '        CATALOG_OUTPUT=/dev/aaas/catalog-$CATALOG_ID.tsv\n'
                '        if [ "$CATALOG_ID" != invalid ] && [ -f "$CATALOG_OUTPUT" ] && '
                '[ ! -L "$CATALOG_OUTPUT" ]; then\n'
                '          CATALOG_BROADCAST=$(/system/bin/am broadcast '
                '--include-stopped-packages --user 0 '
                '-n org.aaas.storagescan/.CatalogReceiver '
                '-a org.aaas.storagescan.CATALOG --es requestId "$CATALOG_ID" 2>&1)\n'
                '          CATALOG_STATUS=$?\n'
                '          echo "AAAS_CATALOG_BROADCAST status=$CATALOG_STATUS output=$CATALOG_BROADCAST" '
                '>> /aaas_session_commands\n'
                '          echo "$CATALOG_ID $CATALOG_STATUS" > /dev/aaas/catalog_ack\n'
                '        else\n'
                '          echo "$CATALOG_ID 2" > /dev/aaas/catalog_ack\n'
                '        fi\n'
                '      fi\n'
            )
        if experimental_virtual_display:
            readiness_and_watch += (
                '      if [ -s /dev/aaas/apk_install_request ]; then\n'
                '        read INSTALL_ID INSTALL_PATH_B64 < /dev/aaas/apk_install_request\n'
                '        : > /dev/aaas/apk_install_request\n'
                '        case "$INSTALL_ID" in ""|*[!0-9a-f]*) INSTALL_ID=invalid ;; esac\n'
                '        INSTALL_PATH=$(printf "%s" "$INSTALL_PATH_B64" | '
                '/system/bin/toybox base64 -d 2>/dev/null)\n'
                '        if [ "$INSTALL_ID" != invalid ] && [ "$INSTALL_PATH" = '
                '"/storage/emulated/0/.aaas-install-$INSTALL_ID.apk" ]; then\n'
                '          INSTALL_OUTPUT=$(/system/bin/pm install -r "$INSTALL_PATH" 2>&1)\n'
                '          INSTALL_STATUS=$?\n'
                '        else INSTALL_OUTPUT=invalid_path; INSTALL_STATUS=2; fi\n'
                '        INSTALL_OUTPUT_B64=$(printf "%s" "$INSTALL_OUTPUT" | '
                '/system/bin/toybox base64 | /system/bin/toybox tr -d "\\n")\n'
                '        echo "$INSTALL_ID $INSTALL_STATUS $INSTALL_OUTPUT_B64" '
                '> /dev/aaas/apk_install_ack\n'
                '      fi\n'
            )
            for slot in range(1, max_apps + 1):
                suffix = '' if slot == 1 else str(slot)
                app_variable = 'APP_PACKAGE' + suffix
                display_variable = 'VD_ID' + suffix
                adapter_pid_variable = 'VDISPLAY' + ('' if slot == 1 else str(slot)) + '_INPUT_ADAPTER_PID'
                socket_name = 'input-vdisplay' + ('-' + str(slot) if slot > 1 else '') + '.sock'
                log_name = ('aaas_vdisplay_input_adapter.log' if slot == 1 else
                            'aaas_vdisplay2_input_adapter.log' if slot == 2 else
                            'aaas_session_commands')
                focus_name = f'vdisplay_focus_{slot}'
                focus_ack_name = f'vdisplay_focus_ack_{slot}'
                readiness_and_watch += (
                    f'      if [ -s /dev/aaas/app{slot}_launch_request ]; then\n'
                    f'        read REQ_ID REQ_PACKAGE REQ_DISPLAY < /dev/aaas/app{slot}_launch_request\n'
                    f'        : > /dev/aaas/app{slot}_launch_request\n'
                    '        case "$REQ_ID" in ""|*[!0-9a-f]*) REQ_ID=invalid ;; esac\n'
                    '        case "$REQ_DISPLAY" in ""|*[!0-9]*) REQ_DISPLAY=invalid ;; esac\n'
                    '        case "$REQ_PACKAGE" in *[!A-Za-z0-9._]*|.*|*..*|*.) '
                    'echo "failed invalid_package" > /dev/aaas/app'
                    f'{slot}_launch_ack ;;\n'
                    '        *)\n'
                    f'          {app_variable}="$REQ_PACKAGE"\n'
                    f'          {display_variable}="$REQ_DISPLAY"\n'
                    f'          : > /dev/aaas/app{slot}_forced_closed\n'
                    '          APP_COMPONENT=$(/system/bin/cmd package resolve-activity --brief '
                    '--user 0 -a android.intent.action.MAIN '
                    '-c android.intent.category.LAUNCHER -p "$REQ_PACKAGE" 2>&1 | '
                    '/system/bin/toybox tail -n 1)\n'
                    '          case "$APP_COMPONENT" in */*) ;; *) APP_COMPONENT= ;; esac\n'
                    f'          if [ -n "$APP_COMPONENT" ]; then\n'
                    f'            if [ -n "${adapter_pid_variable}" ]; then '
                    f'/system/bin/toybox kill "${adapter_pid_variable}" 2>/dev/null || true; '
                    f'{adapter_pid_variable}=; fi\n'
                    '            /system/bin/aaas-input-adapter --socket /dev/aaas/'
                    f'{socket_name} --session-file /dev/aaas/input_session '
                    f'--log /{log_name} --focus-request /dev/aaas/{focus_name} '
                    f'--focus-ack /dev/aaas/{focus_ack_name} '
                    f'--display "$REQ_DISPLAY" & {adapter_pid_variable}=$!\n'
                    '          fi\n'
                    '          if [ -n "$APP_COMPONENT" ] && '
                    '/system/bin/cmd activity start-activity -W --display "$REQ_DISPLAY" '
                    '-n "$APP_COMPONENT" >> /aaas_session_commands 2>&1; then\n'
                    f'            echo "started $REQ_ID $REQ_PACKAGE $REQ_DISPLAY" '
                    f'> /dev/aaas/app{slot}_launch_ack\n'
                    f'            echo RUNNING > /dev/aaas/app{slot}_state\n'
                    '          else\n'
                    f'            echo "failed $REQ_ID launch" > /dev/aaas/app{slot}_launch_ack\n'
                    '          fi\n'
                    '          ;;\n'
                    '        esac\n'
                    '      fi\n'
                    f'      if [ -s /dev/aaas/app{slot}_stop_request ]; then\n'
                    f'        read STOP_ID STOP_PACKAGE < /dev/aaas/app{slot}_stop_request\n'
                    f'        : > /dev/aaas/app{slot}_stop_request\n'
                    '        case "$STOP_ID" in ""|*[!0-9a-f]*) STOP_ID=invalid ;; esac\n'
                    '        case "$STOP_PACKAGE" in *[!A-Za-z0-9._]*|.*|*..*|*.) '
                    f'echo "failed invalid_package" > /dev/aaas/app{slot}_stop_ack ;;\n'
                    '        *)\n'
                    f'          if [ "$STOP_PACKAGE" = "${app_variable}" ] && '
                    '/system/bin/cmd activity force-stop --user 0 "$STOP_PACKAGE" '
                    '>> /aaas_session_commands 2>&1; then\n'
                    '            STOP_TASK_LINE=$(/system/bin/dumpsys activity activities | '
                    '/system/bin/toybox grep -F "u0 $STOP_PACKAGE/" | '
                    '/system/bin/toybox tail -n 1)\n'
                    '            STOP_TASK_ID=$(echo "$STOP_TASK_LINE" | '
                    '/system/bin/toybox sed "s/.* t//; s/[^0-9].*//")\n'
                    '            if [ -n "$STOP_TASK_ID" ]; then\n'
                    '              case "$STOP_TASK_ID" in\n'
                    '                *[!0-9]*) : ;;\n'
                    '                *)\n'
                    '/system/bin/cmd activity stack remove "$STOP_TASK_ID" '
                    '>> /aaas_session_commands 2>&1 || true\n'
                    '                  ;;\n'
                    '              esac\n'
                    '            fi\n'
                    f'            echo "$STOP_PACKAGE" > /dev/aaas/app{slot}_forced_closed\n'
                    f'            echo "stopped $STOP_ID $STOP_PACKAGE" > /dev/aaas/app{slot}_stop_ack\n'
                    f'            echo CLOSED > /dev/aaas/app{slot}_state\n'
                    '          else\n'
                    f'            echo "failed $STOP_ID force_stop" > /dev/aaas/app{slot}_stop_ack\n'
                    '          fi\n'
                    '          ;;\n'
                    '        esac\n'
                    '      fi\n'
                    f'      if [ "$(/system/bin/toybox cat /dev/aaas/app{slot}_state '
                    '2>/dev/null)" != RUNNING ]; then\n'
                    f'        case "$' + adapter_pid_variable + '" in ""|*[!0-9]*) ;; *) '
                    f'/system/bin/toybox kill "$' + adapter_pid_variable + '" 2>/dev/null || true; '
                    f'{adapter_pid_variable}= ;; esac\n'
                    '      fi\n'
                )
            readiness_and_watch += (
                '      if aaas_app_task_alive; then echo RUNNING > /dev/aaas/app1_state; '
                'else echo CLOSED > /dev/aaas/app1_state; '
                'if [ -n "$VDISPLAY_INPUT_ADAPTER_PID" ]; then '
                '/system/bin/toybox kill "$VDISPLAY_INPUT_ADAPTER_PID" 2>/dev/null || true; '
                'VDISPLAY_INPUT_ADAPTER_PID=; fi; fi\n'
                '      if aaas_app2_task_alive; then echo RUNNING > /dev/aaas/app2_state; '
                'else echo CLOSED > /dev/aaas/app2_state; '
                'if [ -n "$VDISPLAY2_INPUT_ADAPTER_PID" ]; then '
                '/system/bin/toybox kill "$VDISPLAY2_INPUT_ADAPTER_PID" 2>/dev/null || true; '
                'VDISPLAY2_INPUT_ADAPTER_PID=; fi; fi\n'
                '      if aaas_app_task_alive || aaas_app2_task_alive; then AAAS_IDLE_SINCE=0; '
                'else\n'
                '        AAAS_IDLE_NOW=$(/system/bin/toybox date +%s)\n'
                '        if [ "$AAAS_IDLE_SINCE" -eq 0 ]; then\n'
                '          AAAS_IDLE_SINCE=$AAAS_IDLE_NOW\n'
                '          echo "AAAS_IDLE_STARTED timeout=$AAAS_IDLE_TIMEOUT_SECONDS" '
                '>> /aaas_session_commands\n'
                '        elif [ "$((AAAS_IDLE_NOW - AAAS_IDLE_SINCE))" -ge '
                '"$AAAS_IDLE_TIMEOUT_SECONDS" ]; then\n'
                '          echo AAAS_IDLE_TIMEOUT_REACHED >> /aaas_session_commands\n'
                '          echo STOPPING > /aaas_session_status\n'
                '        fi\n'
                '      fi\n'
                '      /system/bin/toybox sleep 1\n'
            )
        else:
            readiness_and_watch += '      /system/bin/toybox sleep 2\n'
        readiness_and_watch += '    done\n'
        if not experimental_virtual_display:
            if app_package2 is not None:
                readiness_and_watch += (
                    '    if [ "$(/system/bin/getprop sys.boot_completed)" = "1" ] && '
                    '[ -n "$(/system/bin/toybox pidof system_server)" ] && '
                    '[ "$(/system/bin/toybox cat /aaas_session_status)" != "FAILED" ] && '
                    '! aaas_app_task_alive && ! aaas_app2_task_alive; then\n'
                    '      echo STOPPING > /aaas_session_status\n'
                    '    fi\n'
                )
            else:
                readiness_and_watch += (
                    '    if [ "$(/system/bin/getprop sys.boot_completed)" = "1" ] && '
                    '[ -n "$(/system/bin/toybox pidof system_server)" ] && '
                    '[ "$(/system/bin/toybox cat /aaas_session_status)" != "FAILED" ] && '
                    '! aaas_app_task_alive; then echo STOPPING > /aaas_session_status; fi\n'
                )
        readiness_and_watch += (
            '    if [ "$(/system/bin/toybox cat /aaas_session_status)" = "STOPPING" ]; then\n'
            '      echo AAAS_DISPLAY_BROKER_STOP_REQUESTED >> /aaas_session_commands\n'
            '      echo stop > /dev/aaas/display_broker_shutdown\n'
            '      RELEASE_WAIT=0\n'
            '      while [ "$(/system/bin/toybox cat /dev/aaas/display_broker_shutdown 2>/dev/null)" '
            '!= released ] && [ "$RELEASE_WAIT" -lt 50 ]; do\n'
            '        /system/bin/toybox sleep 0.1\n'
            '        RELEASE_WAIT=$((RELEASE_WAIT + 1))\n'
            '      done\n'
            '      if [ "$(/system/bin/toybox cat /dev/aaas/display_broker_shutdown 2>/dev/null)" '
            '= released ]; then\n'
            '        echo AAAS_DISPLAY_BROKER_STOPPED >> /aaas_session_commands\n'
            '        /system/bin/stop aaas-display-broker\n'
            '        SERVICE_WAIT=0\n'
            '        while [ "$(/system/bin/getprop init.svc.aaas-display-broker)" != stopped ] '
            '&& [ "$SERVICE_WAIT" -lt 50 ]; do\n'
            '          /system/bin/toybox sleep 0.1\n'
            '          SERVICE_WAIT=$((SERVICE_WAIT + 1))\n'
            '        done\n'
            '        if [ "$(/system/bin/getprop init.svc.aaas-display-broker)" = stopped ]; then\n'
            '          echo AAAS_DISPLAY_BROKER_SERVICE_STOPPED >> /aaas_session_commands\n'
            '        else\n'
            '          echo AAAS_DISPLAY_BROKER_SERVICE_STOP_FAILED >> /aaas_session_commands\n'
            '          echo FAILED > /aaas_session_status\n'
            '          exit 1\n'
            '        fi\n'
            '      else\n'
            '        echo AAAS_DISPLAY_BROKER_STOP_FAILED >> /aaas_session_commands\n'
            '        echo FAILED > /aaas_session_status\n'
            '        exit 1\n'
            '      fi\n'
            '    else\n'
            '      echo FAILED > /aaas_session_status\n'
            '    fi\n'
        )
    elif not headless_storage:
        readiness_and_watch += '; do\n'
        if storage_scan_apk is not None:
            readiness_and_watch += (
                '      if [ -s /dev/aaas/storage_scan_request ]; then\n'
                '        read SCAN_ID SCAN_PATH_B64 < /dev/aaas/storage_scan_request\n'
                '        : > /dev/aaas/storage_scan_request\n'
                '        case "$SCAN_ID" in ""|*[!0-9a-f]*) SCAN_ID=invalid ;; esac\n'
                '        SCAN_PATH=$(printf "%s" "$SCAN_PATH_B64" | '
                '/system/bin/toybox base64 -d 2>/dev/null)\n'
                '        case "$SCAN_PATH" in /storage/emulated/0/*)\n'
                '          case "$SCAN_PATH" in *"/../"*|*"/.."|*"/Android/data/"*|'
                '*"/Android/data"|*"/Android/obb/"*|*"/Android/obb")\n'
                '            echo "failed $SCAN_ID invalid_path" > /dev/aaas/storage_scan_ack ;;\n'
                '          *)\n'
                '            SCAN_SERVICE_OUTPUT=$(/system/bin/am broadcast '
                '--include-stopped-packages --user 0 '
                '-n org.aaas.storagescan/.ScanReceiver '
                '--es path "$SCAN_PATH" --es requestId "$SCAN_ID" 2>&1)\n'
                '            SCAN_SERVICE_STATUS=$?\n'
                '            echo "AAAS_STORAGE_SCAN_SERVICE status=$SCAN_SERVICE_STATUS output=$SCAN_SERVICE_OUTPUT" '
                '>> /aaas_session_commands\n'
                '            if [ "$SCAN_SERVICE_STATUS" -eq 0 ]; then\n'
                '              echo "started $SCAN_ID $SCAN_PATH" > /dev/aaas/storage_scan_ack\n'
                '            else\n'
                '              echo "failed $SCAN_ID launch $SCAN_SERVICE_OUTPUT" > /dev/aaas/storage_scan_ack\n'
                '            fi ;;\n'
                '          esac ;;\n'
                '          *) echo "failed $SCAN_ID invalid_path" > /dev/aaas/storage_scan_ack ;;\n'
                '        esac\n'
                '      fi\n'
                '      if [ -s /dev/aaas/storage_scan_query_request ]; then\n'
                '        read QUERY_ID QUERY_URI_B64 < /dev/aaas/storage_scan_query_request\n'
                '        : > /dev/aaas/storage_scan_query_request\n'
                '        QUERY_URI=$(printf "%s" "$QUERY_URI_B64" | '
                '/system/bin/toybox base64 -d 2>/dev/null)\n'
                '        case "$QUERY_URI" in content://media/*)\n'
                '          QUERY_OUTPUT=$(/system/bin/content query '
                '--uri "$QUERY_URI" --projection _id:_display_name:_data 2>&1)\n'
                '          QUERY_STATUS=$? ;;\n'
                '          *) QUERY_OUTPUT=invalid_content_uri; QUERY_STATUS=2 ;;\n'
                '        esac\n'
                '        QUERY_OUTPUT_B64=$(printf "%s" "$QUERY_OUTPUT" | '
                '/system/bin/toybox base64 | /system/bin/toybox tr -d "\\n")\n'
                '        echo "$QUERY_ID $QUERY_STATUS $QUERY_OUTPUT_B64" '
                '> /dev/aaas/storage_scan_query_ack\n'
                '      fi\n'
                '      if [ -s /dev/aaas/catalog_request ]; then\n'
                '        read CATALOG_ID < /dev/aaas/catalog_request\n'
                '        : > /dev/aaas/catalog_request\n'
                '        case "$CATALOG_ID" in ""|*[!0-9a-f]*) CATALOG_ID=invalid ;; esac\n'
                '        CATALOG_OUTPUT=/dev/aaas/catalog-$CATALOG_ID.tsv\n'
                '        if [ "$CATALOG_ID" != invalid ] && [ -f "$CATALOG_OUTPUT" ] && '
                '[ ! -L "$CATALOG_OUTPUT" ]; then\n'
                '          CATALOG_BROADCAST=$(/system/bin/am broadcast '
                '--include-stopped-packages --user 0 '
                '-n org.aaas.storagescan/.CatalogReceiver '
                '-a org.aaas.storagescan.CATALOG --es requestId "$CATALOG_ID" 2>&1)\n'
                '          CATALOG_STATUS=$?\n'
                '          echo "AAAS_CATALOG_BROADCAST status=$CATALOG_STATUS output=$CATALOG_BROADCAST" '
                '>> /aaas_session_commands\n'
                '          echo "$CATALOG_ID $CATALOG_STATUS" > /dev/aaas/catalog_ack\n'
                '        else\n'
                '          echo "$CATALOG_ID 2" > /dev/aaas/catalog_ack\n'
                '        fi\n'
                '      fi\n'
            )
        readiness_and_watch += (
            '      /system/bin/toybox sleep 2\n'
            '    done\n'
            '    echo FAILED > /aaas_session_status\n'
        )
    if headless_storage:
        readiness_and_watch += (
            '    if [ "$(/system/bin/toybox cat /aaas_session_status)" = STOPPING ]; then exit 0; fi\n'
            '    echo AAAS_HEADLESS_STORAGE_FRAMEWORK_STOPPED_UNEXPECTEDLY >> /aaas_session_commands\n'
            '    echo FAILED > /aaas_session_status\n'
            '    exit 1\n'
            '    if [ "{settings_sigquit}"'
        )
    else:
        readiness_and_watch += (
            '    exit 1\n'
            '    if [ "{settings_sigquit}"'
        )
    if experimental_virtual_display:
        readiness_and_watch = readiness_and_watch.replace(
            '&& aaas_app_task_alive',
            '&& [ "$(/system/bin/toybox cat /aaas_session_status)" = "RUNNING" ]')
        extra_idle_guard = ''.join(
            f' && [ "$(/system/bin/toybox cat /dev/aaas/app{i}_state 2>/dev/null)" != RUNNING ]'
            for i in range(3, max_apps + 1))
        readiness_and_watch = readiness_and_watch.replace(
            '! aaas_app_task_alive; then echo STOPPING',
            '! aaas_app_task_alive' + extra_idle_guard + '; then echo STOPPING')
        readiness_and_watch = readiness_and_watch.replace(
            '! aaas_app_task_alive && ! aaas_app2_task_alive; then',
            '! aaas_app_task_alive && ! aaas_app2_task_alive' + extra_idle_guard + '; then')
    source = replace_once(
        source,
        '    /system/bin/toybox sleep 3\n    if [ "{settings_sigquit}"',
        readiness_and_watch,
    )
    source = replace_once(source, '                         start_new_session=True)',
                          '                         start_new_session=False)')
    source = replace_once(source, f'p.communicate(timeout={timeout})', 'p.communicate(timeout=None)')
    output = session / 'runner.py'
    output.write_text(source)
    output.chmod(0o700)
    return output


def select_lmkd_overlay(use_source_lmkd):
    return (
        ('m1b85_lmkd_source_built', LMKD_SOURCE_BUILT_SHA256)
        if use_source_lmkd else
        ('m1b83_lmkd_vmstats_diagnostic', LMKD_DIAGNOSTIC_SHA256)
    )


def vdisplay_services_overlay_is_current():
    try:
        receipt = json.loads(VDISPLAY_SERVICES_RECEIPT.read_text())
        source_patch = ROOT / 'patches/m1e/display-content-mode-compat.patch'
        return (
            VDISPLAY_SERVICES_OVERLAY.is_file()
            and receipt.get('input_sha256') == sha256(
                TMP / 'm1b8_services_battery_mobile_diagnostic.jar')
            and receipt.get('output_sha256') == sha256(VDISPLAY_SERVICES_OVERLAY)
            and receipt.get('source_patch_sha256') == sha256(source_patch)
            and receipt.get('property') == 'debug.aaas.display_content_mode_management'
            and receipt.get('alarm_fallback') == (
                'AlarmHandler delegates due alarms to deliverAlarmsLocked and reschedules')
            and receipt.get('alarm_source_patch_sha256') == sha256(
                ROOT / 'patches/m1e/alarm-listener-fallback.patch')
            and receipt.get('storage_transcoding_default') == (
                'false; explicit persist.sys.fuse and DeviceConfig overrides remain honored')
        )
    except (OSError, ValueError, KeyError):
        return False


def storage_services_overlay_is_current():
    try:
        receipt = json.loads(STORAGE_SERVICES_RECEIPT.read_text())
        original = TMP / 'm1b8_services_battery_mobile_diagnostic.jar'
        alarm_patch = ROOT / 'patches/m1e/alarm-listener-fallback.patch'
        return (
            STORAGE_SERVICES_OVERLAY.is_file()
            and receipt.get('input_sha256') == sha256(original)
            and receipt.get('output_sha256') == sha256(STORAGE_SERVICES_OVERLAY)
            and receipt.get('apktool_sha256') == sha256(APKTOOL)
            and receipt.get('default') == (
                'false; system property and DeviceConfig overrides preserved')
            and receipt.get('alarm_fallback') == (
                'AlarmHandler delegates due alarms to deliverAlarmsLocked and reschedules')
            and receipt.get('alarm_source_patch_sha256') == sha256(alarm_patch)
        )
    except (OSError, ValueError, KeyError):
        return False


def build_storage_services_overlay():
    if not storage_services_overlay_is_current():
        subprocess.run([
            sys.executable, str(ROOT / 'scripts/build_m4_storage_services_overlay.py'),
            '--original', str(TMP / 'm1b8_services_battery_mobile_diagnostic.jar'),
            '--apktool', str(APKTOOL), '--output', str(STORAGE_SERVICES_OVERLAY),
            '--receipt', str(STORAGE_SERVICES_RECEIPT), '--work-parent', str(TMP),
        ], check=True)
    return STORAGE_SERVICES_OVERLAY


def framework_transition_overlay_is_current():
    source = configured_rootfs() / 'system/framework/framework.jar'
    try:
        receipt = json.loads(FRAMEWORK_TRANSITION_RECEIPT.read_text())
        return (
            receipt.get('revision') == '99b01a65cc4c104933788b3143285ab6bae65827'
            and receipt.get('input_sha256') == sha256(source)
            and receipt.get('apktool_sha256') == sha256(APKTOOL)
            and receipt.get('builder_sha256') == sha256(FRAMEWORK_TRANSITION_BUILDER)
            and receipt.get('overlay_sha256') == sha256(FRAMEWORK_TRANSITION_OVERLAY)
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def build_framework_transition_overlay():
    guard = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/android_workspace.py'),
         '--workspace', str(WORKSPACE), 'check'],
        capture_output=True, text=True,
    )
    if guard.returncode:
        raise RuntimeError(guard.stdout + guard.stderr)
    subprocess.run([
        sys.executable, str(FRAMEWORK_TRANSITION_BUILDER),
        '--original', str(configured_rootfs() / 'system/framework/framework.jar'),
        '--apktool', str(APKTOOL), '--output', str(FRAMEWORK_TRANSITION_OVERLAY),
        '--work-parent', str(TMP), '--receipt', str(FRAMEWORK_TRANSITION_RECEIPT),
    ], check=True)


def validate_diagnostic_vulkan_overlay(path):
    overlay = Path(path).resolve(strict=True)
    workspace_tmp = TMP.resolve()
    try:
        overlay.relative_to(workspace_tmp)
    except ValueError as error:
        raise ValueError('diagnostic Vulkan overlay must be inside the AaaS workspace tmp directory') from error
    if overlay == (TMP / 'm1b83_sampling_lock_vulkan.so').resolve():
        raise ValueError('diagnostic Vulkan overlay cannot replace the production overlay')
    manifest_path = Path(str(overlay) + '.manifest.json')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema_version') != 1:
        raise ValueError(f'unsupported diagnostic overlay manifest: {manifest_path}')
    if manifest.get('source_revision') != 'cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5':
        raise ValueError('diagnostic overlay source revision is not the pinned SwiftShader revision')
    identity = manifest.get('output', {})
    if identity.get('sha256') != sha256(overlay):
        raise ValueError('diagnostic overlay hash does not match its manifest')
    notes = subprocess.run(['readelf', '-n', str(overlay)], check=True,
                            capture_output=True, text=True, timeout=5).stdout
    build_id = next((line.split('Build ID:', 1)[1].strip()
                     for line in notes.splitlines() if 'Build ID:' in line), None)
    if not build_id or identity.get('build_id') != build_id:
        raise ValueError('diagnostic overlay Build ID does not match its manifest')
    return overlay


def validate_swiftshader_runtime_overlay():
    overlay = validate_diagnostic_vulkan_overlay(SWIFTSHADER_RUNTIME_OVERLAY)
    manifest = json.loads(Path(str(overlay) + '.manifest.json').read_text())
    identity = manifest.get('output', {})
    if manifest.get('source_diff_sha256') != SWIFTSHADER_RUNTIME_SOURCE_DIFF_SHA256:
        raise ValueError('runtime SwiftShader overlay source patch does not match the validated bounds fix')
    if manifest.get('diagnostics_enabled') is not False:
        raise ValueError('runtime SwiftShader overlay must have diagnostics disabled')
    if identity.get('sha256') != SWIFTSHADER_RUNTIME_SHA256:
        raise ValueError('runtime SwiftShader overlay hash differs from the validated candidate')
    return overlay


def verify_requirements(use_source_lmkd=False, orientation='portrait',
                        diagnostic_vulkan_overlay=None,
                        diagnostic_framework_overlay=None,
                        diagnostic_framework_sha256=None,
                        audio_enabled=False, storage_only=False):
    check = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/android_workspace.py'),
         '--workspace', str(WORKSPACE), 'check'],
        capture_output=True, text=True,
    )
    if check.returncode:
        raise RuntimeError(check.stdout + check.stderr)
    mount = json.loads(check.stdout)['mount']
    if mount['filesystem'] not in ('ext4', 'xfs', 'btrfs', 'ntfs3'):
        raise RuntimeError(f'unsupported enrolled workspace filesystem: {mount}')
    if not configured_rootfs().is_dir():
        raise RuntimeError(f'Android rootfs is missing: {configured_rootfs()}')
    if audio_enabled:
        audio_required = (
            configured_rootfs() / 'vendor/lib64/hw/android.hardware.audio.legacy@7.1-impl.ranchu.so',
            configured_rootfs() / 'vendor/bin/hw/android.hardware.audio.service',
            configured_rootfs() / 'system/bin/audioserver',
            configured_rootfs() / 'system/lib64/libaudiohal.so',
        )
        missing_audio = [str(path) for path in audio_required if not path.is_file()]
        if missing_audio:
            raise RuntimeError('Android 16 Ranchu audio profile is incomplete: '
                               + ', '.join(missing_audio))
    if not storage_only and not PRESENTER.is_file():
        raise RuntimeError(f'build the presenter first: {PRESENTER}')
    drm_render_node = None if storage_only else aaas_graphics.discover_render_node()
    if not storage_only and not INPUT_ADAPTER.is_file():
        print(f'AaaS: input adapter not built; pointer input disabled ({INPUT_ADAPTER})',
              file=sys.stderr)
    lmkd_overlay_entry = select_lmkd_overlay(use_source_lmkd)
    required = {
        'AAAS_VDC_OVERLAY': ('m1d_vdc_overlay/vdc', VDC_OVERLAY_SHA256),
        'AAAS_FRAMEWORK_JAR_OVERLAY': (FRAMEWORK_TRANSITION_OVERLAY.name, None),
        'AAAS_VULKAN_OVERLAY': (SWIFTSHADER_RUNTIME_OVERLAY.name, SWIFTSHADER_RUNTIME_SHA256),
        'AAAS_LMKD_OVERLAY': lmkd_overlay_entry,
        'AAAS_RANGING_JAR_OVERLAY': ('m1b8_service-ranging.rebuilt2.jar', None),
        'AAAS_NETWORKSTATS_LIB_OVERLAY': ('m1b81_networkstats_uid_diagnostic.so', None),
        'AAAS_MEMINFO_LIB_OVERLAY': ('m1b81_meminfo_gpu_diagnostic.so', None),
        'AAAS_SERVICES_JAR_OVERLAY': ('m1b8_services_battery_mobile_diagnostic.jar', None),
        'AAAS_KEYSTORE_SID_PROBE': ('m1b81_libkeystore_sid_uid1000_rebuild.so', None),
        'AAAS_HWSM_SID_PROBE': ('m1b81_libhwsm_sid_probe_rebuilt.so', None),
    }
    paths = {}
    for key, (name, expected_hash) in required.items():
        if key == 'AAAS_FRAMEWORK_JAR_OVERLAY' and diagnostic_framework_overlay:
            path = Path(diagnostic_framework_overlay).resolve()
            if not diagnostic_framework_sha256:
                raise RuntimeError('diagnostic framework overlay requires an explicit SHA-256')
            expected_hash = diagnostic_framework_sha256.lower()
            if not re.fullmatch(r'[0-9a-f]{64}', expected_hash):
                raise RuntimeError('diagnostic framework SHA-256 must be 64 lowercase hex digits')
        elif key == 'AAAS_VULKAN_OVERLAY' and diagnostic_vulkan_overlay:
            try:
                path = validate_diagnostic_vulkan_overlay(diagnostic_vulkan_overlay)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                raise RuntimeError(f'invalid diagnostic Vulkan overlay: {error}') from error
            expected_hash = None
        elif key == 'AAAS_VULKAN_OVERLAY':
            try:
                path = validate_swiftshader_runtime_overlay()
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                raise RuntimeError(f'invalid runtime SwiftShader overlay: {error}') from error
        else:
            path = FRAMEWORK_TRANSITION_OVERLAY if key == 'AAAS_FRAMEWORK_JAR_OVERLAY' else TMP / name
            if key == 'AAAS_FRAMEWORK_JAR_OVERLAY' and not framework_transition_overlay_is_current():
                raise RuntimeError('Android transition framework overlay receipt is missing or stale')
        if not path.is_file():
            raise RuntimeError(f'missing required diagnostic overlay: {path}')
        if expected_hash and sha256(path) != expected_hash:
            raise RuntimeError(f'overlay checksum changed: {path}')
        paths[key] = str(path)
    if orientation == 'portrait':
        composer = COMPOSER_PORTRAIT
        expected_composer_hash = COMPOSER_PORTRAIT_SHA256
    else:
        composer = COMPOSER_LANDSCAPE
        expected_composer_hash = None
    if not composer.is_file():
        raise RuntimeError(f'build the {orientation} Composer overlay first: {composer}')
    if expected_composer_hash and sha256(composer) != expected_composer_hash:
        raise RuntimeError(f'Composer overlay checksum changed: {composer}')
    paths['AAAS_COMPOSER_OVERLAY'] = str(composer)
    if drm_render_node is not None:
        paths['AAAS_DRM_RENDER_NODE'] = str(drm_render_node)
    return paths


def build_multi_output_composer(max_count=64):
    """Build Composer with runtime-registered independent display endpoints."""
    receipt = COMPOSER_MULTI_OUTPUT.with_suffix('.json')
    composer_source = ROOT / 'experiments/m1b/composer_aaas'
    source_paths = [composer_source / name for name in
                    ('composer_service.cpp', 'aaas_transport.cpp', 'aaas_transport.h',
                     'virtual_transport_pool.h', 'linear_copy.h', 'mixed_compose.h',
                     'Makefile')]
    source_paths.append(ROOT / 'experiments/m1a/src/wire_v2.c')
    source_digest = hashlib.sha256()
    for source_path in source_paths:
        source_digest.update(source_path.name.encode('utf-8') + b'\0')
        source_digest.update(source_path.read_bytes())
    source_sha256 = source_digest.hexdigest()
    if COMPOSER_MULTI_OUTPUT.is_file() and receipt.is_file():
        try:
            recorded = json.loads(receipt.read_text())
            if (recorded.get('endpoint_mode') == 'on-demand' and
                    recorded.get('max_count') == max_count and
                    recorded.get('source_sha256') == source_sha256 and
                    recorded.get('sha256') == sha256(COMPOSER_MULTI_OUTPUT)):
                return COMPOSER_MULTI_OUTPUT
        except (OSError, ValueError):
            pass
    libcxx = Path(os.environ.get('AAAS_TOOLCHAIN_LIBCXX',
                                 str(WORKSPACE / 'toolchain/libc++')))
    if not (libcxx / 'usr/include/c++/v1/vector').is_file():
        raise RuntimeError('Android libc++ headers are unavailable; set AAAS_TOOLCHAIN_LIBCXX')
    command = [
        'make', '-C', str(ROOT / 'experiments/m1b/composer_aaas'),
        f'WORKSPACE_ROOT={WORKSPACE}', f'ROOTFS={configured_rootfs()}',
        f'TOOLCHAIN_LIBCXX={libcxx}', f'OUT_DIR={TMP}',
        f'BUILD_DIR={TMP / "composer_build"}',
        f'BIN={COMPOSER_MULTI_OUTPUT}',
        'AAAS_ENABLE_VIRTUAL_DISPLAY=1',
        f'AAAS_VIRTUAL_DISPLAY_MAX_COUNT={max_count}',
        'AAAS_DISPLAY_WIDTH=720',
        'AAAS_DISPLAY_HEIGHT=1280',
        'all',
    ]
    subprocess.run(command, check=True)
    if not COMPOSER_MULTI_OUTPUT.is_file():
        raise RuntimeError(f'two-output Composer build missing: {COMPOSER_MULTI_OUTPUT}')
    receipt.write_text(json.dumps({'endpoint_mode': 'on-demand',
                                   'sha256': sha256(COMPOSER_MULTI_OUTPUT),
                                   'source_sha256': source_sha256,
                                   'max_count': max_count,
                                   'source': 'experiments/m1b/composer_aaas',
                                   'build_flags': ['AAAS_ENABLE_VIRTUAL_DISPLAY=1',
                                                   f'AAAS_VIRTUAL_DISPLAY_MAX_COUNT={max_count}']},
                                  sort_keys=True, indent=2) + '\n')
    return COMPOSER_MULTI_OUTPUT


def show_primary_diagnostic(args):
    """Keep the primary Wayland window for diagnostics, not normal app mode."""
    if getattr(args, 'headless_storage', False):
        return False
    return not (args.experimental_virtual_display and args.app) or args.show_primary_diagnostic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--startup-timeout', type=int, default=90)
    parser.add_argument('--use-source-lmkd', action='store_true',
                        help='Use the source-built Android 16 LMKD binary instead of diagnostic overlay')
    parser.add_argument('--memory-policy', choices=('none', 'cgroup'), default='none',
                        help='Apply a rootless delegated cgroup v2 memory policy')
    parser.add_argument('--orientation', choices=('portrait', 'landscape'),
                        default='portrait',
                        help='initial Android display orientation (default: portrait)')
    parser.add_argument('--window-size', type=parse_window_size,
                        help='initial virtual display size as WIDTHxHEIGHT; defaults to '
                             '420x740 portrait or 740x420 landscape')
    parser.add_argument('--display-size', type=parse_display_size,
                        help='initial Android framebuffer as WIDTHxHEIGHT; defaults to '
                             '720x1280 portrait or 1280x720 landscape')
    parser.add_argument('--display-density', type=parse_display_density, default=240,
                        help='initial Android virtual display density in dpi (default: 240)')
    parser.add_argument('--app', default=DEFAULT_APP_PACKAGE,
                        help='installed package with a MAIN/LAUNCHER activity '
                             '(default: com.android.settings)')
    parser.add_argument('--app2',
                        help='optional second installed app for the experimental '
                             'two-display prototype')
    parser.add_argument('--app-extra', action='append', default=[],
                        help='additional installed package to launch after startup (repeatable)')
    parser.add_argument('--max-apps', type=int, default=16,
                        help='per-runtime safety bound for active Android windows (default: 16)')
    parser.add_argument('--idle-timeout-seconds', type=int, default=60,
                        help='stop an idle two-output runtime after this many seconds '
                             '(1..3600; default: 60)')
    parser.add_argument('--software-keyboard', action='store_true',
                        help='Allow Android to show its software keyboard (mobile/accessibility mode)')
    parser.add_argument('--experimental-virtual-display', action='store_true',
                        help='Use the isolated M1E trusted virtual-display prototype')
    parser.add_argument('--audio', action='store_true',
                        help='Enable the reproducible session-local Android/PipeWire audio path')
    parser.add_argument('--experimental-audio-hal', action='store_true',
                        help=argparse.SUPPRESS)
    parser.add_argument('--experimental-audio-hal-diagnostics', action='store_true',
                        help='Instrument Android audio services during HAL diagnosis')
    parser.add_argument('--experimental-audio-server-overlay',
                        help='Session-only replacement audioserver binary for HAL diagnosis')
    parser.add_argument('--experimental-audiohal-overlay',
                        help='Session-only replacement libaudiohal.so for HAL diagnosis')
    parser.add_argument('--audio-playback-sink',
                        help='Optional PipeWire/Pulse sink name for Android playback')
    parser.add_argument('--audio-capture-source',
                        help='Optional PipeWire/Pulse source name for authorized Android recording')
    parser.add_argument('--audio-media-file',
                        help='Open a shared-media WAV with Android Music via a temporary MediaStore URI grant')
    parser.add_argument('--audio-playback-volume-test', action='store_true',
                        help='Exercise Music mute and volume for --audio-media-file, then restore volume')
    parser.add_argument('--show-primary-diagnostic', action='store_true',
                        help='Also present Android primary display in a diagnostic Wayland window')
    parser.add_argument('--diagnostic-vulkan-overlay',
                        help='Use a manifest-verified temporary SwiftShader overlay instead of production')
    parser.add_argument('--diagnostic-framework-overlay',
                        help='Select an isolated framework JAR overlay for experiments')
    parser.add_argument('--diagnostic-framework-sha256',
                        help='Required expected SHA-256 for the diagnostic framework overlay')
    parser.add_argument('--diagnostic-composer-overlay',
                        help='Use a hash-checked Composer binary for isolated runtime experiments')
    parser.add_argument('--diagnostic-composer-sha256',
                        help='Required SHA-256 for --diagnostic-composer-overlay')
    parser.add_argument('--resource-diagnostics', action='store_true',
                        help='Write read-only host/cgroup snapshots at session start and shutdown')
    parser.add_argument('--trace-staging-stages', action='store_true',
                        help='Opt in to per-operation staging and presenter-thread timing')
    parser.add_argument('--trace-input-response-roi',
                        help='Opt in to bounded input-to-presented-frame tracking for source ROI x,y,w,h')
    parser.add_argument('--input-response-probe-apk',
                        help='diagnostic-only APK overlaid as a system app for input latency measurements')
    parser.add_argument('--input-response-probe-apk2',
                        help='optional second diagnostic APK for distinct-package two-display input checks')
    parser.add_argument('--diagnostic-storage-apk',
                        help='install the controlled storage probe as an ordinary /data/app package')
    parser.add_argument('--install-apk', action='append',
                        help='install an APK as an ordinary user package before launch; repeat for multiple APKs')
    parser.add_argument('--uninstall-package',
                        help='uninstall a controlled org.aaas package through PackageManager')
    parser.add_argument('--assert-package-absent',
                        help='verify a controlled org.aaas package and its user data are absent')
    parser.add_argument('--diagnostic-storage-open', action='store_true',
                        help='select the first file in DocumentsUI for the storage diagnostic APK')
    parser.add_argument('--diagnostic-storage-relaunch', action='store_true',
                        help='force-stop and relaunch the app after SAF selection')
    parser.add_argument('--headless-storage', action='store_true',
                        help='run storage checks without host Wayland presentation')
    parser.add_argument('--diagnostic-native-bridge-overlay',
                        help='hash-verified Android Native Bridge bundle for isolated ARM64 tests')
    parser.add_argument('--diagnostic-native-bridge-arm64-first', action='store_true',
                        help='prefer arm64-v8a when an APK contains multiple native ABIs')
    parser.add_argument('--diagnostic-native-bridge-exec', action='store_true',
                        help='opt in to session-local ARM64 ELF execution through Berberis binfmt_misc')
    parser.add_argument('--diagnostic-native-exec-libraries-apk',
                        help='session-local guest dependency overlay source APK (requires native exec)')
    parser.add_argument('--diagnostic-capture-app-tombstones', action='store_true',
                        help='opt in to private export of app crash tombstones for compatibility debugging')
    parser.add_argument('--resource-sample-interval', type=float, default=0.0,
                        help='Opt in to host/cgroup resource snapshots; optionally sample every N seconds (0 disables periodic samples, max 3600 samples)')
    parser.add_argument('--test-tombstone-capture', action='store_true',
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.headless_storage and (args.experimental_virtual_display or args.app2 or
                                  args.audio or args.experimental_audio_hal or
                                  args.show_primary_diagnostic):
        parser.error('--headless-storage cannot enable displays, a second app, or audio')
    audio_enabled = args.audio or args.experimental_audio_hal
    if ((args.experimental_audio_server_overlay or args.experimental_audiohal_overlay)
            and not audio_enabled):
        parser.error('audio binary overlays require --audio')
    if args.experimental_audio_hal_diagnostics and not audio_enabled:
        parser.error('--experimental-audio-hal-diagnostics requires --audio')
    if args.audio_media_file and not audio_enabled:
        parser.error('--audio-media-file requires --audio')
    if args.audio_media_file and args.app not in MEDIA_TEST_COMPONENTS:
        parser.error('--audio-media-file requires a supported media application')
    if args.audio_playback_volume_test and not args.audio_media_file:
        parser.error('--audio-playback-volume-test requires --audio-media-file')
    if args.audio_media_file:
        media_relative = PurePosixPath(args.audio_media_file)
        if (media_relative.is_absolute() or not media_relative.parts
                or any(part in ('', '.', '..') for part in media_relative.parts)
                or media_relative.suffix.lower() != '.wav'
                or not re.fullmatch(r'[A-Za-z0-9_./-]+', media_relative.as_posix())):
            parser.error('--audio-media-file must be a relative .wav path under shared media')
        media_host_path = (WORKSPACE / 'shared-storage/android-media/0'
                           / media_relative.as_posix()).resolve(strict=True)
        media_root = (WORKSPACE / 'shared-storage/android-media/0').resolve(strict=True)
        if not media_host_path.is_file() or not media_host_path.is_relative_to(media_root):
            parser.error('--audio-media-file must name a regular file in shared Android media')
    native_bridge_bundle = native_bridge_entries = None
    if args.diagnostic_native_bridge_overlay:
        if not args.experimental_virtual_display:
            parser.error('--diagnostic-native-bridge-overlay requires --experimental-virtual-display')
        try:
            native_bridge_bundle, native_bridge_entries = validate_native_bridge_bundle(
                args.diagnostic_native_bridge_overlay)
        except (OSError, ValueError) as error:
            parser.error(str(error))
    elif args.diagnostic_native_bridge_arm64_first:
        parser.error('--diagnostic-native-bridge-arm64-first requires --diagnostic-native-bridge-overlay')
    if args.diagnostic_native_bridge_exec and not args.diagnostic_native_bridge_overlay:
        parser.error('--diagnostic-native-bridge-exec requires --diagnostic-native-bridge-overlay')
    if args.diagnostic_native_exec_libraries_apk and not args.diagnostic_native_bridge_exec:
        parser.error('--diagnostic-native-exec-libraries-apk requires --diagnostic-native-bridge-exec')
    if args.diagnostic_framework_overlay and not args.experimental_virtual_display:
        parser.error('--diagnostic-framework-overlay requires --experimental-virtual-display')
    if args.diagnostic_framework_sha256 and not args.diagnostic_framework_overlay:
        parser.error('--diagnostic-framework-sha256 requires --diagnostic-framework-overlay')
    if bool(args.diagnostic_composer_overlay) != bool(args.diagnostic_composer_sha256):
        parser.error('--diagnostic-composer-overlay and --diagnostic-composer-sha256 must be used together')
    if args.diagnostic_composer_overlay and not args.experimental_virtual_display:
        parser.error('--diagnostic-composer-overlay requires --experimental-virtual-display')
    if args.trace_staging_stages and not args.experimental_virtual_display:
        parser.error('--trace-staging-stages requires --experimental-virtual-display')
    if args.trace_input_response_roi and not args.experimental_virtual_display:
        parser.error('--trace-input-response-roi requires --experimental-virtual-display')
    if args.input_response_probe_apk and not args.experimental_virtual_display:
        parser.error('--input-response-probe-apk requires --experimental-virtual-display')
    if args.input_response_probe_apk2 and not args.app2:
        parser.error('--input-response-probe-apk2 requires --app2')
    if args.diagnostic_storage_apk and args.app != 'org.aaas.storagetest':
        parser.error('--diagnostic-storage-apk requires --app org.aaas.storagetest')
    if args.diagnostic_storage_open and not args.diagnostic_storage_apk:
        parser.error('--diagnostic-storage-open requires --diagnostic-storage-apk')
    if args.diagnostic_storage_relaunch and not args.diagnostic_storage_open:
        parser.error('--diagnostic-storage-relaunch requires --diagnostic-storage-open')
    if args.install_apk and args.diagnostic_storage_apk:
        parser.error('--install-apk and --diagnostic-storage-apk are mutually exclusive')
    for package, option in ((args.uninstall_package, '--uninstall-package'),
                            (args.assert_package_absent, '--assert-package-absent')):
        if package is not None:
            try:
                validate_app_package(package)
            except ValueError as error:
                parser.error(f'{option}: {error}')
            if not package.startswith('org.aaas.'):
                parser.error(f'{option} is limited to controlled org.aaas packages')
    if args.uninstall_package and args.assert_package_absent:
        parser.error('use only one package lifecycle operation per session')
    if args.startup_timeout < 1:
        parser.error('startup timeout must be positive')
    if args.test_tombstone_capture and args.app2:
        parser.error('--test-tombstone-capture requires a single-app disposable session')
    if not 0.0 <= args.resource_sample_interval <= 3600.0:
        parser.error('resource sample interval must be between 0 and 3600 seconds')
    if args.max_apps < 1 or args.max_apps > 256:
        parser.error('--max-apps must be from 1 to 256')
    try:
        validate_app_package(args.app)
        if args.app2 is not None:
            validate_app_package(args.app2)
            if args.app2 == args.app:
                raise ValueError('app2 must differ from app')
            if not args.experimental_virtual_display:
                raise ValueError('--app2 requires --experimental-virtual-display')
    except ValueError as error:
        parser.error(str(error))
    selected_packages = [package for package in (args.app, args.app2, *args.app_extra)
                         if package]
    if len(set(selected_packages)) != len(selected_packages):
        parser.error('each application package may be selected only once')
    if args.app_extra and not args.experimental_virtual_display:
        parser.error('--app-extra requires --experimental-virtual-display')
    if not args.diagnostic_framework_overlay and not framework_transition_overlay_is_current():
        if not APKTOOL.is_file():
            raise RuntimeError(f'missing pinned apktool for Android transition input overlay: {APKTOOL}')
        build_framework_transition_overlay()
    paths = verify_requirements(use_source_lmkd=args.use_source_lmkd,
                                orientation=args.orientation,
                                diagnostic_vulkan_overlay=args.diagnostic_vulkan_overlay,
                                diagnostic_framework_overlay=args.diagnostic_framework_overlay,
                                diagnostic_framework_sha256=args.diagnostic_framework_sha256,
                                audio_enabled=audio_enabled,
                                storage_only=args.headless_storage)
    if not args.experimental_virtual_display:
        paths['AAAS_SERVICES_JAR_OVERLAY'] = str(build_storage_services_overlay())
    if args.experimental_virtual_display:
        if not COMPOSER_VDISPLAY.is_file():
            raise RuntimeError('build the M1E virtual-display Composer first')
        subprocess.run([
            'make', '-C', str(ROOT / 'experiments/m1e/display_broker'),
            f'WORKSPACE={WORKSPACE}', f'BUILD_DIR={TMP / "m1e_display_broker_build"}',
            f'OUT={VDISPLAY_BROKER_DEX}',
        ], check=True)
        if not VDISPLAY_BROKER_DEX.is_file():
            raise RuntimeError('M1E virtual-display broker build produced no DEX')
        if not APKTOOL.is_file():
            raise RuntimeError(f'missing pinned apktool for M1E framework overlay: {APKTOOL}')
        if not vdisplay_services_overlay_is_current():
            subprocess.run([
                sys.executable, str(ROOT / 'scripts/patch_m1e_display_content_mode.py'),
                '--original', str(TMP / 'm1b8_services_battery_mobile_diagnostic.jar'),
                '--apktool', str(APKTOOL), '--output', str(VDISPLAY_SERVICES_OVERLAY),
                '--work-parent', str(TMP), '--receipt', str(VDISPLAY_SERVICES_RECEIPT),
            ], check=True)
        if args.diagnostic_composer_overlay:
            diagnostic_composer = Path(args.diagnostic_composer_overlay).resolve(strict=True)
            expected_composer_hash = args.diagnostic_composer_sha256.lower()
            if not re.fullmatch(r'[0-9a-f]{64}', expected_composer_hash):
                raise RuntimeError('diagnostic Composer SHA-256 must be 64 lowercase hex digits')
            if sha256(diagnostic_composer) != expected_composer_hash:
                raise RuntimeError(f'diagnostic Composer checksum changed: {diagnostic_composer}')
            paths['AAAS_COMPOSER_OVERLAY'] = str(diagnostic_composer)
        else:
            paths['AAAS_COMPOSER_OVERLAY'] = str(
                build_multi_output_composer(args.max_apps))
        paths['AAAS_SERVICES_JAR_OVERLAY'] = str(VDISPLAY_SERVICES_OVERLAY)
    graphics_provenance = collect_graphics_provenance(paths)
    primary_diagnostic = show_primary_diagnostic(args)
    lock_fd = os.open(TMP / '.aaas_session.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        print('AaaS: another foreground session is already running', file=sys.stderr)
        return 2
    stop = False

    def request_stop(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    session = Path(tempfile.mkdtemp(prefix='m1b84_session_', dir=TMP))
    session.chmod(0o700)
    native_bridge_overlay = None
    if native_bridge_bundle is not None:
        native_bridge_overlay = prepare_native_bridge_overlay(
            native_bridge_bundle, native_bridge_entries, session,
            arm64_first=args.diagnostic_native_bridge_arm64_first,
            native_exec=args.diagnostic_native_bridge_exec,
            native_exec_library_apk=args.diagnostic_native_exec_libraries_apk)
    bluetooth_policy_dir = session / 'bluetooth-policy'
    bluetooth_policy_manifest = aaas_bluetooth.create_unavailable_policy(
        configured_rootfs(), bluetooth_policy_dir)
    (session / 'bluetooth-policy.json').write_text(
        json.dumps(bluetooth_policy_manifest, indent=2) + '\n')
    (session / 'bluetooth-policy.json').chmod(0o600)
    provenance_path = session / 'runtime-graphics-provenance.json'
    provenance_path.write_text(json.dumps(graphics_provenance, indent=2) + '\n')
    provenance_path.chmod(0o600)
    prefix = f'm1b84_session_{os.getpid()}_'
    storage_scan_apk = STORAGE_SCAN_APK
    tombstone_dir = session / 'tombstones'
    tombstone_dir.mkdir(mode=0o700)
    ipc = session / 'ipc'
    ipc.mkdir(mode=0o711)
    virtual_endpoint_dir = ipc / 'virtual-endpoints'
    virtual_endpoint_dir.mkdir(mode=0o755)
    virtual_endpoint_dir.chmod(0o755)
    status = session / 'status'
    write_status_sentinel(status, 'STARTING')
    status.chmod(0o666)
    logcat = session / 'logcat.log'
    logcat.touch()
    logcat.chmod(0o666)
    session_commands = session / 'commands.log'
    session_commands.touch()
    session_commands.chmod(0o666)
    display_broker_log = ipc / 'display_broker.log'
    display_broker_log.touch()
    display_broker_log.chmod(0o666)
    input_adapter_log = session / 'input-adapter.log'
    input_adapter_log.touch()
    input_adapter_log.chmod(0o666)
    vdisplay_input_adapter_log = session / 'vdisplay-input-adapter.log'
    vdisplay2_input_adapter_log = session / 'vdisplay2-input-adapter.log'
    if args.experimental_virtual_display:
        vdisplay_input_adapter_log.touch()
        vdisplay_input_adapter_log.chmod(0o666)
        if args.app2:
            vdisplay2_input_adapter_log.touch()
            vdisplay2_input_adapter_log.chmod(0o666)
    input_session = int.from_bytes(os.urandom(8), 'little') or 1
    (ipc / 'input_session').write_text(f'0x{input_session:016x}\n')
    (ipc / 'input_session').chmod(0o600)
    if args.experimental_virtual_display:
        (ipc / 'vdisplay_id').write_text('')
        (ipc / 'vdisplay_id').chmod(0o666)
        (ipc / 'vdisplay2_id').write_text('enabled:8\n' if args.app2 else '8\n')
        (ipc / 'vdisplay2_id').chmod(0o666)
        for index in range(3, args.max_apps + 1):
            path = ipc / f'vdisplay{index}_id'
            path.write_text('')
            path.chmod(0o666)
        (ipc / 'display_broker_shutdown').write_text('')
        (ipc / 'display_broker_shutdown').chmod(0o666)
        for index in range(1, args.max_apps + 1):
            for name in (f'vdisplay_resize_{index}', f'vdisplay_close_{index}',
                         f'vdisplay_control_ack_{index}', f'app{index}_state',
                         f'vdisplay_focus_{index}', f'vdisplay_focus_ack_{index}',
                         f'vdisplay_create_{index}', f'vdisplay_create_ack_{index}',
                         f'app{index}_launch_request', f'app{index}_launch_ack',
                         f'app{index}_stop_request', f'app{index}_stop_ack',
                         f'app{index}_forced_closed'):
                path = ipc / name
                path.write_text('')
                path.chmod(0o666)
            for name in (f'window_identity_{index}_request',
                         f'window_identity_{index}_ack'):
                path = ipc / name
                path.write_text('')
                path.chmod(0o600)
        for name in ('apk_install_request', 'apk_install_ack'):
            path = ipc / name
            path.write_text('')
            path.chmod(0o600)
    if storage_scan_apk is not None:
        for name in ('storage_scan_request', 'storage_scan_ack',
                     'storage_scan_query_request', 'storage_scan_query_ack',
                     'catalog_request', 'catalog_ack'):
            path = ipc / name
            path.write_text('')
            path.chmod(0o666)
    for name in ('tombstone_capture_request', 'tombstone_capture_ack',
                 'tombstone_capture_test_pid',
                 'tombstone_capture_test_result'):
        path = ipc / name
        path.write_text('')
        path.chmod(0o600)
    for name in ('clipboard_host_request', 'clipboard_state',
                 'clipboard_settings_request', 'clipboard_ime_previous',
                 'clipboard_ime_ack', 'clipboard_probe_request',
                 'clipboard_probe_ack'):
        path = ipc / name
        path.write_text('')
        path.chmod(0o600)
    notification_state_path = ipc / 'notification_state'
    notification_state_path.write_text('')
    notification_state_path.chmod(0o600)
    notification_settings_path = ipc / 'notification_settings_request'
    notification_settings_path.write_text('')
    notification_settings_path.chmod(0o600)
    notification_settings_ack_path = ipc / 'notification_settings_ack'
    notification_settings_ack_path.write_text('')
    notification_settings_ack_path.chmod(0o600)
    if args.test_tombstone_capture:
        test_request = ipc / 'tombstone_capture_test'
        test_request.write_text('')
        test_request.chmod(0o600)
    policy = None
    policy_monitor = None
    policy_log = session / 'policy.jsonl'
    if args.memory_policy == 'cgroup':
        try:
            policy = aaas_cgroup.CgroupSession.create(
                name=f'{os.getpid()}-{session.name.rsplit("_", 1)[-1]}')
        except aaas_cgroup.CgroupError as error:
            print(f'AaaS: cgroup memory policy unavailable: {error}', file=sys.stderr)
            os.close(lock_fd)
            return 1
        print(f'AaaS: cgroup memory policy at {policy.session_dir}', flush=True)
    resource_policy_path = policy.session_dir if policy is not None else None
    if args.resource_sample_interval > 0:
        resource_sample_log = session / 'resources-periodic.jsonl'
        periodic_sample_count = 0
        next_resource_sample = time.monotonic() + args.resource_sample_interval
    else:
        resource_sample_log = None
        periodic_sample_count = 0
        next_resource_sample = None
    collect_resource_diagnostics = (
        args.resource_diagnostics or args.resource_sample_interval > 0)
    if collect_resource_diagnostics:
        try:
            aaas_resources.write_snapshot(
                session / 'resources-start.json', workspace=WORKSPACE,
                policy_cgroup=resource_policy_path,
                tracked_packages=[package for package in (args.app, args.app2)
                                  if package])
        except OSError as error:
            print(f'AaaS: resource snapshot unavailable: {error}',
                  file=sys.stderr, flush=True)
    shared_storage_path = aaas_storage.prepare_backing_directory(WORKSPACE)
    persistent_userdata_path = aaas_userdata.prepare_userdata_directory(WORKSPACE)
    clipboard_ipc_dir = None
    notification_ipc_dir = None
    clipboard_apk = None
    notification_apk = None
    if not shutil.which('setfacl'):
        raise RuntimeError('shared storage requires the host ACL utilities')
    if not args.headless_storage:
        clipboard_ipc_dir = aaas_clipboard.prepare_ipc_directory(ipc)
        notification_ipc_dir = aaas_notifications.prepare_ipc_directory(ipc)
        subprocess.run(['make', '-C', str(ROOT / 'experiments/m4/clipboard')],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True)
        if not CLIPBOARD_BRIDGE.is_file():
            raise RuntimeError('clipboard Wayland bridge build did not produce its executable')
    scan_builder = ROOT / 'experiments/m4/storage_scan_helper/build_scan_helper.py'
    subprocess.run([
        sys.executable, str(scan_builder), '--apktool', str(APKTOOL),
        '--apksig', str(APKSIG), '--dx', str(ANDROID_DX),
        '--keystore', str(STORAGE_SCAN_KEYSTORE),
        '--output', str(STORAGE_SCAN_APK),
    ], check=True)
    if not args.headless_storage:
        clipboard_builder = ROOT / 'experiments/m4/clipboard/build_clipboard_ime.py'
        subprocess.run([
            sys.executable, str(clipboard_builder), '--apktool', str(APKTOOL),
            '--framework-res', str(configured_rootfs() / 'system/framework/framework-res.apk'),
            '--apksig', str(APKSIG), '--dx', str(ANDROID_DX),
            '--zipalign', str(ANDROID_ZIPALIGN),
            '--keystore', str(STORAGE_SCAN_KEYSTORE), '--output', str(CLIPBOARD_APK),
        ], check=True)
        notification_builder = ROOT / 'experiments/m4/notifications/build_listener.py'
        subprocess.run([
            sys.executable, str(notification_builder), '--apktool', str(APKTOOL),
            '--framework-res', str(configured_rootfs() / 'system/framework/framework-res.apk'),
            '--apksig', str(APKSIG), '--dx', str(ANDROID_DX),
            '--zipalign', str(ANDROID_ZIPALIGN),
            '--keystore', str(STORAGE_SCAN_KEYSTORE), '--output', str(NOTIFICATION_APK),
        ], check=True)
    audio_hal_overlay = None
    audio_hal_probe = None
    audio_hal_factory_probe = None
    audio_ashmem_shim = None
    audio_factory_compat = None
    audio_server_overlay = None
    audiohal_overlay = None
    audio_codec_init = None
    audio_mediaextractor_init = None
    audio_mediaextractor_seccomp = None
    if audio_enabled:
        audio_overlay_dir = TMP / 'm4-audio/pristine-system'
        subprocess.run([
            sys.executable, str(ROOT / 'scripts/build_m4_audio_overlays.py'),
            '--system-image', str(TMP / 'partitions/system.raw.img'),
            '--output-dir', str(audio_overlay_dir),
            '--workspace', str(WORKSPACE),
        ], check=True)
        audio_server_overlay = (Path(args.experimental_audio_server_overlay)
                                if args.experimental_audio_server_overlay
                                else audio_overlay_dir / 'audioserver')
        audiohal_overlay = (Path(args.experimental_audiohal_overlay)
                            if args.experimental_audiohal_overlay
                            else audio_overlay_dir / 'libaudiohal.so')
        audio_hal_overlay = TMP / 'm4-audio/audio.primary.aaas.so'
        subprocess.run([
            sys.executable, str(ROOT / 'experiments/m4/audio/build_audio_hal.py'),
            '--rootfs', str(configured_rootfs()),
            '--output', str(audio_hal_overlay),
        ], check=True)
        audio_ashmem_shim = TMP / 'm4-audio/libaaas-audio-ashmem.so'
        subprocess.run([
            sys.executable, str(ROOT / 'experiments/m4/audio/build_ashmem_compat.py'),
            '--rootfs', str(configured_rootfs()),
            '--output', str(audio_ashmem_shim),
        ], check=True)
        audio_factory_compat = TMP / 'm4-audio/libaaas-audio-factory-compat.so'
        subprocess.run([
            sys.executable, str(ROOT / 'experiments/m4/audio/build_factory_compat.py'),
            '--rootfs', str(configured_rootfs()),
            '--output', str(audio_factory_compat),
        ], check=True)
        audio_codec_rc = (
            configured_rootfs() / 'apex/com.android.media.swcodec/etc/mediaswcodec.rc')
        audio_vendor_init = (
            bluetooth_policy_dir / 'vendor/etc/init/hw/init.ranchu.rc')
        if not audio_codec_rc.is_file() or not audio_vendor_init.is_file():
            parser.error('Android software codec init configuration is missing from the image')
        vendor_init_text = audio_vendor_init.read_text()
        if re.search(r'^service\s+media\.swcodec\b', vendor_init_text, re.MULTILINE):
            parser.error('Ranchu init already defines the software codec service')
        audio_codec_init = TMP / 'm4-audio/init.ranchu.rc'
        audio_codec_init.write_text(
            vendor_init_text.rstrip() + '\n\n'
            '# AaaS session-local import of the image software codec service.\n'
            + audio_codec_rc.read_text().lstrip()
        )
        mediaextractor_rc = (
            configured_rootfs() / 'system/etc/init/mediaextractor.rc')
        mediaextractor_text = mediaextractor_rc.read_text()
        service_decl = 'service mediaextractor /system/bin/mediaextractor\n'
        if mediaextractor_text.count(service_decl) != 1:
            parser.error('Android media extractor init service is not recognized')
        if 'LD_PRELOAD' in mediaextractor_text:
            parser.error('Android media extractor already defines LD_PRELOAD')
        audio_mediaextractor_init = TMP / 'm4-audio/mediaextractor.rc'
        audio_mediaextractor_init.write_text(
            mediaextractor_text.replace(
                service_decl,
                service_decl + '    setenv LD_PRELOAD '
                '/system/lib64/libaaas-audio-ashmem.so\n', 1))
        audio_mediaextractor_seccomp = TMP / 'm4-audio/mediaextractor.policy'
        audio_mediaextractor_seccomp.write_text(mediaextractor_seccomp_supplement())
        if args.experimental_audio_hal_diagnostics:
            audio_hal_probe = TMP / 'm4-audio/libaaas-audio-hal-probe.so'
            subprocess.run([
                sys.executable, str(ROOT / 'experiments/m4/audio/build_hal_probe.py'),
                '--rootfs', str(configured_rootfs()),
                '--output', str(audio_hal_probe),
            ], check=True)
            audio_hal_factory_probe = TMP / 'm4-audio/libaaas-audio-factory-probe.so'
            subprocess.run([
                sys.executable, str(ROOT / 'experiments/m4/audio/build_factory_probe.py'),
                '--rootfs', str(configured_rootfs()),
                '--output', str(audio_hal_factory_probe),
            ], check=True)
    runner = make_session_runner(session, desktop_ime=not args.software_keyboard,
                                 app_package=args.app,
                                 experimental_virtual_display=args.experimental_virtual_display,
                                 app_package2=args.app2,
                                 bluetooth_policy_dir=bluetooth_policy_dir,
                                 input_response_probe_apk=args.input_response_probe_apk,
                                 input_response_probe_apk2=args.input_response_probe_apk2,
                                 native_bridge_overlay=native_bridge_overlay,
                                 capture_app_tombstones=args.diagnostic_capture_app_tombstones,
                                 idle_timeout_seconds=args.idle_timeout_seconds,
                                 shared_storage_dir=shared_storage_path,
                                 diagnostic_storage_apk=args.diagnostic_storage_apk,
                                 diagnostic_storage_open=args.diagnostic_storage_open,
                                 diagnostic_storage_relaunch=args.diagnostic_storage_relaunch,
                                 install_apk=args.install_apk,
                                 uninstall_package=args.uninstall_package,
                                 assert_package_absent=args.assert_package_absent,
                                 storage_scan_apk=storage_scan_apk,
                                 persistent_userdata_dir=persistent_userdata_path,
                                 native_bridge_exec=args.diagnostic_native_bridge_exec,
                                 clipboard_apk=clipboard_apk if args.headless_storage else CLIPBOARD_APK,
                                 notification_apk=notification_apk if args.headless_storage else NOTIFICATION_APK,
                                 audio_hal_overlay=audio_hal_overlay,
                                 audio_hal_probe=audio_hal_probe,
                                 audio_hal_factory_probe=audio_hal_factory_probe,
                                 audio_server_overlay=audio_server_overlay,
                                 audiohal_overlay=audiohal_overlay,
                                 audio_ashmem_shim=audio_ashmem_shim,
                                 audio_factory_compat=audio_factory_compat,
                                 audio_codec_init=audio_codec_init,
                                 audio_mediaextractor_init=audio_mediaextractor_init,
                                 audio_mediaextractor_seccomp=audio_mediaextractor_seccomp,
                                 audio_media_file=args.audio_media_file,
                                 audio_playback_volume_test=args.audio_playback_volume_test,
                                 headless_storage=args.headless_storage,
                                 max_apps=args.max_apps)
    env = os.environ.copy()
    env.update(paths)
    env.update(AAAS_WORKSPACE=str(WORKSPACE), AAAS_ROOTFS=str(configured_rootfs()))
    scripts_path = str(ROOT / 'scripts')
    env['PYTHONPATH'] = scripts_path + (os.pathsep + env['PYTHONPATH']
                                        if env.get('PYTHONPATH') else '')
    presenter_width, presenter_height = initial_window_size(
        args.orientation, args.window_size)
    presenter_size = (str(presenter_width), str(presenter_height))
    display_width, display_height = initial_display_size(
        args.orientation, args.display_size)
    display_size = (str(display_width), str(display_height))
    boot_wait = (min(args.startup_timeout, 180)
                 if args.experimental_virtual_display else args.startup_timeout)
    env.update(AAAS_LOG_PREFIX=prefix, AAAS_BOOTANIM='0',
               AAAS_BOOT_WAIT=str(boot_wait),
               AAAS_SESSION_IPC=str(ipc), AAAS_SESSION_STATUS=str(status),
               AAAS_TOMBSTONE_EXPORT=str(tombstone_dir),
               AAAS_SESSION_LOGCAT=str(logcat),
               AAAS_SESSION_COMMANDS=str(session_commands),
               AAAS_INPUT_ADAPTER=str(INPUT_ADAPTER) if INPUT_ADAPTER.is_file() else '',
               AAAS_INPUT_ADAPTER_LOG=str(input_adapter_log))
    if args.experimental_virtual_display:
        broker_rc = session / 'aaas-display-broker.rc'
        broker_rc_template = VDISPLAY_BROKER_RC.read_text()
        if broker_rc_template.count('AAAS_DISPLAY_COUNT') != 1:
            raise RuntimeError('display broker service template has invalid capacity marker')
        broker_rc.write_text(broker_rc_template.replace(
            'AAAS_DISPLAY_COUNT', str(args.max_apps)))
        env.update(AAAS_VDISPLAY_DEX=str(VDISPLAY_BROKER_DEX),
                   AAAS_VDISPLAY_RC=str(broker_rc),
                   AAAS_VDISPLAY_INPUT_ADAPTER_LOG=str(vdisplay_input_adapter_log))
        if args.app2:
            env['AAAS_VDISPLAY2_INPUT_ADAPTER_LOG'] = str(vdisplay2_input_adapter_log)
    presenter = virtual_presenter = virtual_presenter2 = android = None
    audio_process = None
    clipboard_process = None
    notification_process = None
    notification_active_uid = None
    notification_failed_uid = None
    clipboard_active_uid = None
    clipboard_failed_uid = None
    presenter_trace_args = []
    # Some Wayland compositors advertise linux-drm-syncobj-v1 but fail to
    # signal release timeline points for our imported staging buffers. In
    # that case wl_buffer.release is intentionally undefined while the
    # explicit-sync surface is alive, eventually exhausting presenter slots.
    # The bounded CPU staging path waits Android's acquire fence before copying
    # and uses ordinary Wayland buffer release for reuse.
    presenter_trace_args.extend(presenter_sync_args())
    if args.diagnostic_composer_overlay:
        presenter_trace_args.append('--trace-buffer-identities')
    if args.trace_staging_stages:
        presenter_trace_args.append('--trace-staging-stages')
    if args.trace_input_response_roi:
        presenter_trace_args.extend(['--trace-input-response-roi', args.trace_input_response_roi])
    state = 'CREATED'
    input_ready_reported = False
    running_session = False
    window_close_requested = {index: None for index in range(1, args.max_apps + 1)}
    slot_packages = {index: (args.app if index == 1 else args.app2 if index == 2 else None)
                     for index in range(1, args.max_apps + 1)}
    slot_lifecycle_generation = {index: 0 for index in range(1, args.max_apps + 1)}
    slot_presenters = {index: None for index in range(1, args.max_apps + 1)}
    slot_endpoint_registrations = {index: None for index in range(1, args.max_apps + 1)}
    window_hidden = {index: slot_packages[index] is None
                     for index in range(1, args.max_apps + 1)}
    storage_scan_uris = {}
    control_path = aaas_control.session_socket_path(WORKSPACE, session.name)
    socket_dir = control_path.parent
    control_path_pointer = ipc / 'aaas-control.path'
    control_server = None
    capture_status = 'not_requested'

    def atomic_control_write(path, value):
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_text(value + '\n')
        temporary.chmod(0o666)
        os.replace(temporary, path)

    def window_identity_for_package(package):
        known_names = {'com.android.settings': 'Settings',
                       'com.android.contacts': 'Contacts',
                       'com.android.calendar': 'Calendar',
                       'com.android.deskclock': 'Clock',
                       'com.android.dialer': 'Phone',
                       'com.apotris.android': 'Apotris'}
        label = known_names.get(
            package, package.rsplit('.', 1)[-1].replace('_', ' ').replace('-', ' ').title())
        # Use a stable package-specific Wayland identity.  Do not gate this on
        # finding a desktop file in XDG_DATA_HOME: KDE's application entries
        # may live in a different XDG data directory (for example when AaaS
        # uses a private XDG_DATA_HOME), and the generic fallback makes KWin
        # group every Android app under "wayland-host-presenter".
        app_id = f'aaas-catalog-{package}'
        try:
            data_home = aaas_config.xdg_paths()['data_home']
            catalog = json.loads((data_home / 'aaas/catalog.json').read_text())
            app = next((item for item in catalog.get('applications', [])
                        if item.get('package') == package), None)
            if app and isinstance(app.get('label'), str):
                candidate = app['label'].strip()
                if candidate and len(candidate) <= 256 and not any(
                        ord(char) < 0x20 or ord(char) == 0x7f for char in candidate):
                    label = candidate
        except (OSError, ValueError, TypeError):
            pass
        return label, app_id

    def request_window_identity(slot, package, activation_token=''):
        request_path = ipc / f'window_identity_{slot}_request'
        ack_path = ipc / f'window_identity_{slot}_ack'
        if request_path.is_symlink() or ack_path.is_symlink():
            raise RuntimeError(f'Android window identity IPC is unsafe for slot {slot}')
        request_id = os.urandom(12).hex()
        label, app_id = window_identity_for_package(package)
        ack_path.write_text('')
        atomic_control_write(request_path,
                             f'{request_id}\n{label}\n{app_id}\n{activation_token}')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if ack_path.read_text().strip() == request_id:
                return {'title': label, 'app_id': app_id}
            time.sleep(.025)
        raise RuntimeError(f'presenter did not apply app identity for {package}')

    def hide_presenter_window(slot):
        request_path = ipc / f'window_identity_{slot}_request'
        ack_path = ipc / f'window_identity_{slot}_ack'
        if request_path.is_symlink() or ack_path.is_symlink():
            raise RuntimeError(f'Android window identity IPC is unsafe for slot {slot}')
        request_id = os.urandom(12).hex()
        ack_path.write_text('')
        atomic_control_write(request_path, f'{request_id}\n\norg.aaas.android-app')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if ack_path.read_text().strip() == request_id:
                return
            time.sleep(.025)
        raise RuntimeError(f'presenter did not hide closed app window in slot {slot}')

    def register_presenter_endpoint(slot, socket_path):
        registration = virtual_endpoint_dir / f'{slot}-{os.urandom(8).hex()}.endpoint'
        android_socket = f'/dev/aaas/{socket_path.name}'
        descriptor = os.open(registration, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(descriptor, (android_socket + '\n').encode('utf-8'))
        finally:
            os.close(descriptor)
        slot_endpoint_registrations[slot] = registration

    def prepare_presenter_sockets(slot):
        """Use short host socket names; Android keeps its stable IPC aliases.

        A portable workspace may live under a deeply nested mount path. Linux
        AF_UNIX socket paths are limited to sizeof(sockaddr_un.sun_path), so
        the historic descriptive socket names can silently truncate/fail.
        The short targets stay in the same bind-mounted IPC directory while
        Android-side adapter names remain compatible via relative symlinks.
        """
        wayland_name = f'w{slot}.sock'
        input_name = f'i{slot}.sock'
        socket_path = ipc / wayland_name
        input_path = ipc / input_name
        android_input_name = ('input-vdisplay.sock' if slot == 1 else
                              f'input-vdisplay-{slot}.sock')
        android_input_path = ipc / android_input_name
        socket_path.unlink(missing_ok=True)
        input_path.unlink(missing_ok=True)
        android_input_path.unlink(missing_ok=True)
        android_input_path.symlink_to(input_name)
        return socket_path, input_path

    def start_dynamic_presenter(slot, package):
        socket_path, input_path = prepare_presenter_sockets(slot)
        display_path = ipc / ('vdisplay_id' if slot == 1 else f'vdisplay{slot}_id')
        resize_path = ipc / f'vdisplay_resize_{slot}'
        identity_request_path = ipc / f'window_identity_{slot}_request'
        identity_ack_path = ipc / f'window_identity_{slot}_ack'
        window_title, window_app_id = window_identity_for_package(package)
        log_path = session / ('virtual-presenter.log' if slot == 1
                              else f'virtual-presenter{slot}.log')
        # A released slot may retain the last xdg_toplevel configure. A new
        # Android display starts at presenter_size, so never replay the old
        # lifecycle's request into its new VirtualDisplay.
        resize_path.write_text('')
        with log_path.open('ab') as presenter_log:
            process = subprocess.Popen(
                [str(PRESENTER), '--socket', str(socket_path), '--node', paths['AAAS_DRM_RENDER_NODE'],
                 *presenter_trace_args,
                 *presenter_geometry_args(presenter_size, display_size),
                 '--input-socket', str(input_path),
                 '--input-session', f'0x{input_session:016x}',
                 '--input-display-id-file', str(display_path),
                 '--resize-request', str(resize_path),
                 '--title', window_title, '--app-id', window_app_id,
                 *(['--defer-map'] if package == 'Android Application' else []),
                 '--identity-request', str(identity_request_path),
                 '--identity-ack', str(identity_ack_path)],
                stdout=presenter_log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + 10
        while not socket_path.exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                terminate_process_group(process)
                raise RuntimeError(f'presenter for slot {slot} did not start')
            time.sleep(.05)
        if package != 'Android Application':
            register_presenter_endpoint(slot, socket_path)
        return process

    def manager_request(request):
        nonlocal virtual_presenter, virtual_presenter2, stop
        if not isinstance(request, dict) or not isinstance(request.get('op'), str):
            return {'ok': False, 'error': 'invalid_request'}
        op = request['op']
        if op not in ('list', 'stop') and (
                state != 'RUNNING' or status.read_text().strip() != 'RUNNING'):
            return {'ok': False, 'error': 'session_not_running', 'state': state}
        if op == 'list':
            return {'ok': True, 'state': state,
                    'windows': [
                        {'slot': slot, 'package': slot_packages[slot],
                         'display_id': read_presenter_display_id(ipc, slot),
                         'state': read_presenter_slot_state(ipc, slot),
                         'presenter_pid': (proc.pid if proc is not None and
                                           proc.poll() is None else None)}
                         for slot, proc in slot_presenters.items()
                        if slot_packages[slot] is not None]}
        if op == 'stop':
            stop = True
            return {'ok': True, 'state': 'STOPPING'}
        if op == 'clipboard_setup':
            request_path = ipc / 'clipboard_settings_request'
            if request_path.is_symlink() or not request_path.is_file():
                return {'ok': False, 'error': 'clipboard_settings_unavailable'}
            request_path.write_text('open\n')
            request_path.chmod(0o600)
            return {'ok': True, 'action': 'android_input_method_settings_opened',
                    'instruction': 'enable and select AaaS Clipboard in Android settings'}
        if op == 'notifications_setup':
            request_path = ipc / 'notification_settings_request'
            if request_path.is_symlink() or not request_path.is_file():
                return {'ok': False, 'error': 'notification_settings_unavailable'}
            request_path.write_text('open\n')
            request_path.chmod(0o600)
            return {'ok': True, 'action': 'android_notification_listener_settings_opened',
                    'instruction': 'authorize AaaS Notifications in Android Settings'}
        if op == 'notifications_ui':
            action = request.get('action')
            if action not in ('tap', 'dump', 'capture'):
                return {'ok': False, 'error': 'invalid_notification_ui_action'}
            request_path = ipc / 'notification_settings_request'
            ack_path = ipc / 'notification_settings_ack'
            if request_path.is_symlink() or ack_path.is_symlink():
                return {'ok': False, 'error': 'notification_settings_control_unsafe'}
            request_id = os.urandom(8).hex()
            ack_path.write_text('')
            if action == 'tap':
                x, y = request.get('x'), request.get('y')
                display_id = request.get('display_id')
                if display_id is None:
                    try:
                        display_id = int((ipc / 'vdisplay_id').read_text().strip())
                    except (OSError, ValueError):
                        return {'ok': False, 'error': 'notification_ui_display_unavailable'}
                if (not isinstance(x, int) or isinstance(x, bool) or
                        not isinstance(y, int) or isinstance(y, bool) or
                        not 0 <= x <= 719 or not 0 <= y <= 1279 or
                        not isinstance(display_id, int) or isinstance(display_id, bool) or
                        not 0 <= display_id <= 10000):
                    return {'ok': False, 'error': 'notification_ui_coordinates_out_of_range'}
                request_path.write_text(f'tap {request_id} {display_id} {x} {y}\n')
            else:
                request_path.write_text(action + '\n')
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    response = ack_path.read_text().strip().split()
                except OSError:
                    response = []
                if action in ('dump', 'capture') and len(response) == 2 and response[0] == action:
                    return {'ok': response[1] == '0', 'action': action}
                if action == 'tap' and len(response) == 2 and response[0] == request_id:
                    return {'ok': response[1] == '0', 'action': action}
                time.sleep(.05)
            return {'ok': False, 'error': 'notification_ui_timeout'}
        if op == 'clipboard_probe':
            mode = request.get('mode')
            if mode not in ('android-copy', 'host-paste'):
                return {'ok': False, 'error': 'invalid_clipboard_probe_mode'}
            request_path = ipc / 'clipboard_probe_request'
            if request_path.is_symlink() or not request_path.is_file():
                return {'ok': False, 'error': 'clipboard_probe_unavailable'}
            request_path.write_text(mode + '\n')
            request_path.chmod(0o600)
            ack_path = ipc / 'clipboard_probe_ack'
            if ack_path.is_symlink() or not ack_path.is_file():
                return {'ok': False, 'error': 'clipboard_probe_ack_unsafe'}
            ack_path.write_text('')
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    fields = ack_path.read_text().strip().split(maxsplit=2)
                except OSError:
                    fields = []
                if len(fields) >= 2 and fields[0] == mode:
                    return {'ok': fields[1] == '0', 'action': 'clipboard_probe_started',
                            'mode': mode,
                            'broadcast': fields[2] if len(fields) > 2 else ''}
                time.sleep(.05)
            return {'ok': False, 'error': 'clipboard_probe_timeout'}
        if op in ('clipboard_ime_use', 'clipboard_ime_restore'):
            action = 'use' if op == 'clipboard_ime_use' else 'restore'
            request_path = ipc / 'clipboard_settings_request'
            ack_path = ipc / 'clipboard_ime_ack'
            if request_path.is_symlink() or ack_path.is_symlink():
                return {'ok': False, 'error': 'clipboard_ime_control_unsafe'}
            ack_path.write_text('')
            request_path.write_text(action + '\n')
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                try:
                    ack = ack_path.read_text().strip()
                except OSError:
                    ack = ''
                if ack.startswith(action + ':'):
                    result = ack.split(':', 1)[1]
                    return {'ok': result == '0', 'action': action,
                            'restored_previous_ime': action == 'restore' and result == '0',
                            'error': None if result == '0' else 'android_ime_command_failed'}
                time.sleep(.05)
            return {'ok': False, 'error': 'clipboard_ime_control_timeout'}
        if op == 'close':
            slot = request.get('slot')
            if slot not in slot_presenters:
                return {'ok': False, 'error': 'invalid_slot'}
            process = slot_presenters.get(slot)
            if process is None:
                return {'ok': False, 'error': 'window_not_running'}
            return manager_request({'op': 'stop_app', 'slot': slot})
        if op == 'stop_app':
            slot = request.get('slot')
            if slot not in slot_packages or slot_packages[slot] is None:
                return {'ok': False, 'error': 'invalid_slot'}
            package = slot_packages[slot]
            process = slot_presenters.get(slot)
            if process is None or process.poll() is not None:
                return {'ok': False, 'error': 'window_not_running'}
            request_id = os.urandom(8).hex()
            atomic_control_write(ipc / f'app{slot}_stop_request',
                                 f'{request_id} {package}')
            deadline = time.monotonic() + 15
            ack = ''
            while time.monotonic() < deadline:
                ack = (ipc / f'app{slot}_stop_ack').read_text().strip()
                if ack.startswith((f'stopped {request_id} ',
                                   f'failed {request_id} ')):
                    break
                time.sleep(.05)
            if not ack.startswith(f'stopped {request_id} '):
                return {'ok': False, 'error': 'app_stop_failed',
                        'detail': ack[:160] or 'timeout'}
            return {'ok': True, 'slot': slot, 'package': package,
                    'state': 'STOPPING'}
        if op == 'install_apk':
            apk_value = request.get('path')
            try:
                apk = Path(apk_value)
                if (not apk.is_absolute() or apk.is_symlink() or not apk.is_file() or
                        apk.suffix.lower() != '.apk' or apk.stat().st_size > 512 * 1024 * 1024):
                    return {'ok': False, 'error': 'invalid_apk_file'}
                storage_root = Path(shared_storage_path).resolve(strict=True)
                if not storage_root.is_dir() or storage_root.is_symlink():
                    return {'ok': False, 'error': 'shared_storage_unavailable'}
            except (OSError, TypeError, ValueError) as error:
                return {'ok': False, 'error': 'invalid_apk_file',
                        'detail': str(error)[:160]}
            request_id = os.urandom(16).hex()
            staged = storage_root / f'.aaas-install-{request_id}.apk'
            request_path = ipc / 'apk_install_request'
            ack_path = ipc / 'apk_install_ack'
            try:
                descriptor = os.open(staged, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                with apk.open('rb') as source, os.fdopen(descriptor, 'wb') as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                encoded = base64.b64encode(
                    f'/storage/emulated/0/{staged.name}'.encode()).decode('ascii')
                ack_path.write_text('')
                atomic_control_write(request_path, f'{request_id} {encoded}')
            except OSError as error:
                staged.unlink(missing_ok=True)
                return {'ok': False, 'error': 'apk_stage_failed',
                        'detail': str(error)[:160]}
            try:
                deadline = time.monotonic() + 120
                fields = []
                while time.monotonic() < deadline:
                    try:
                        fields = ack_path.read_text().strip().split(maxsplit=2)
                    except OSError:
                        fields = []
                    if len(fields) == 3 and fields[0] == request_id:
                        break
                    time.sleep(.1)
                if len(fields) != 3 or fields[0] != request_id:
                    return {'ok': False, 'error': 'apk_install_timeout'}
                try:
                    detail = base64.b64decode(fields[2], validate=True).decode(
                        'utf-8', 'replace')
                    status_code = int(fields[1])
                except (ValueError, base64.binascii.Error):
                    return {'ok': False, 'error': 'apk_install_response_invalid'}
                return {'ok': status_code == 0 and 'Success' in detail,
                        'action': 'package_manager_install',
                        'detail': detail[:1000], 'package_manager_status': status_code}
            finally:
                staged.unlink(missing_ok=True)
        if op == 'package_catalog':
            if storage_scan_apk is None:
                return {'ok': False, 'error': 'package_catalog_helper_unavailable'}
            request_id = os.urandom(16).hex()
            request_path = ipc / 'catalog_request'
            ack_path = ipc / 'catalog_ack'
            result_path = ipc / f'catalog-{request_id}.tsv'
            try:
                descriptor = os.open(result_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                                     0o622)
                os.close(descriptor)
                result_path.chmod(0o622)
                ack_path.write_text('')
                atomic_control_write(request_path, request_id)
            except OSError as error:
                result_path.unlink(missing_ok=True)
                return {'ok': False, 'error': 'package_catalog_request_failed',
                        'detail': str(error)[:160]}
            deadline = time.monotonic() + 25
            ack = ''
            while time.monotonic() < deadline:
                ack = ack_path.read_text().strip()
                if ack.startswith(request_id + ' '):
                    break
                time.sleep(.05)
            if ack.split() != [request_id, '0']:
                result_path.unlink(missing_ok=True)
                return {'ok': False, 'error': 'package_catalog_query_failed',
                        'detail': ack[:160] or 'timeout'}
            try:
                content = result_path.read_bytes()
                if len(content) > 16 * 1024 * 1024:
                    raise ValueError('catalog exceeds 16 MiB limit')
                header = content.splitlines()[0].decode('ascii').split('\t')
                if (len(header) != 4 or header[:3] !=
                        ['AAAS-CATALOG', '1', request_id]):
                    raise ValueError('catalog header or request identity mismatch')
                count = max(0, len(content.splitlines()) - 1)
                return {'ok': True, 'catalog_path': str(result_path),
                        'count': count, 'truncated': header[3] == '1',
                        'request_id': request_id}
            except (OSError, ValueError, UnicodeError, IndexError) as error:
                result_path.unlink(missing_ok=True)
                return {'ok': False, 'error': 'package_catalog_response_invalid',
                        'detail': str(error)[:160]}
        if op == 'storage_scan':
            if storage_scan_apk is None:
                return {'ok': False, 'error': 'storage_scan_helper_unavailable'}
            try:
                relative_path = request.get('path')
                host_path = aaas_storage.validate_media_scan_path(
                    relative_path, shared_storage_path)
                relative_path = host_path.relative_to(
                    Path(shared_storage_path).resolve(strict=True)).as_posix()
            except (TypeError, ValueError, OSError) as error:
                return {'ok': False, 'error': 'invalid_storage_scan_path',
                        'detail': str(error)[:160]}
            android_path = '/storage/emulated/0/' + relative_path
            expected_present = host_path.is_file()
            request_id = os.urandom(8).hex()
            encoded_path = base64.b64encode(android_path.encode('utf-8')).decode('ascii')
            request_path = ipc / 'storage_scan_request'
            ack_path = ipc / 'storage_scan_ack'
            ack_path.write_text('')
            try:
                log_offset = logcat.stat().st_size
            except OSError:
                log_offset = 0
            atomic_control_write(request_path, f'{request_id} {encoded_path}')
            deadline = time.monotonic() + 12
            ack = ''
            while time.monotonic() < deadline:
                ack = ack_path.read_text().strip()
                if ack.startswith((f'started {request_id} ', f'failed {request_id} ')):
                    break
                time.sleep(.05)
            if not ack.startswith(f'started {request_id} '):
                return {'ok': False, 'error': 'storage_scan_launch_failed',
                        'detail': ack[:160] or 'timeout'}
            marker = f'ANDROID_FILE_SCAN_COMPLETE id={request_id} path={android_path} uri='
            deadline = time.monotonic() + 35
            uri = None
            while time.monotonic() < deadline:
                try:
                    with logcat.open('rb') as stream:
                        stream.seek(log_offset)
                        content = stream.read().decode('utf-8', 'replace')
                except OSError:
                    content = ''
                matches = [line for line in content.splitlines() if marker in line]
                if matches:
                    line = matches[-1]
                    uri = line.split(marker, 1)[1].strip()
                    break
                time.sleep(.1)
            if uri is None:
                return {'ok': False, 'error': 'storage_scan_timeout',
                        'path': relative_path}
            previous_uri = storage_scan_uris.get(relative_path)
            query_uri = uri if uri.startswith('content://media/') else previous_uri
            if query_uri is None:
                return {'ok': False, 'error': 'storage_scan_no_query_uri',
                        'path': relative_path, 'uri': uri}
            query_request = ipc / 'storage_scan_query_request'
            query_ack = ipc / 'storage_scan_query_ack'
            atomic_control_write(query_request,
                                 f'{request_id} {base64.b64encode(query_uri.encode()).decode()}')
            query_deadline = time.monotonic() + 15
            query_result = ''
            while time.monotonic() < query_deadline:
                query_result = query_ack.read_text().strip()
                if query_result.startswith(request_id + ' '):
                    break
                time.sleep(.05)
            query_parts = query_result.split(' ', 2)
            if len(query_parts) != 3 or query_parts[0] != request_id:
                return {'ok': False, 'error': 'storage_scan_query_timeout',
                        'path': relative_path}
            try:
                query_status = int(query_parts[1])
                query_output = base64.b64decode(query_parts[2]).decode(
                    'utf-8', 'replace')
            except (ValueError, base64.binascii.Error):
                return {'ok': False, 'error': 'storage_scan_query_invalid_response',
                        'path': relative_path}
            if query_status != 0:
                return {'ok': False, 'error': 'storage_scan_query_failed',
                        'path': relative_path, 'detail': query_output[:240]}
            present = 'No result found.' not in query_output
            if present != expected_present:
                return {'ok': False, 'error': 'storage_scan_reconciliation_pending',
                        'path': relative_path, 'uri': uri,
                        'expected_present': expected_present,
                        'mediastore_present': present,
                        'mediastore_query': query_output[:1000]}
            if present:
                storage_scan_uris[relative_path] = uri
            else:
                storage_scan_uris.pop(relative_path, None)
            return {'ok': True, 'path': relative_path, 'uri': uri,
                    'state': 'completed', 'mediastore_present': present,
                    'mediastore_query': query_output[:1000]}
        if op != 'launch':
            return {'ok': False, 'error': 'unsupported_operation'}
        try:
            package = validate_app_package(request.get('package'))
        except ValueError:
            return {'ok': False, 'error': 'invalid_package'}
        activation_token = request.get('activation_token', '')
        if (not isinstance(activation_token, str) or len(activation_token) > 2048 or
                any(ord(char) < 0x20 or ord(char) == 0x7f for char in activation_token)):
            return {'ok': False, 'error': 'invalid_activation_token'}
        existing_slot = next((slot for slot in slot_packages
                              if slot_packages[slot] == package and
                              slot_presenters[slot] is not None and
                              read_presenter_slot_state(ipc, slot) != 'CLOSED'), None)
        if existing_slot is not None:
            # A desktop-menu click on an already-running app should raise its
            # existing toplevel, not silently fail (or allocate a duplicate
            # Android display).  The one-shot token comes from the initiating
            # desktop launch and is consumed by the presenter via
            # xdg_activation_v1.
            try:
                identity = request_window_identity(existing_slot, package,
                                                   activation_token)
            except RuntimeError as error:
                return {'ok': False, 'error': 'existing_window_activation_failed',
                        'detail': str(error)[:240]}
            return {'ok': True, 'already_running': True, 'slot': existing_slot,
                    'package': package,
                    'display_id': int((ipc / ('vdisplay_id' if existing_slot == 1 else
                                             f'vdisplay{existing_slot}_id')).read_text().strip()),
                    'state': 'RUNNING', 'window_title': identity['title'],
                    'desktop_app_id': identity['app_id']}
        candidates = [slot for slot, process in slot_presenters.items()
                      if slot_packages[slot] is None and
                      (process is None or process.poll() is None)]
        if not candidates:
            return {'ok': False, 'error': 'capacity_exhausted'}
        slot = candidates[0]
        slot_lifecycle_generation[slot] += 1
        generation = slot_lifecycle_generation[slot]
        request_id = f'{os.urandom(8).hex()}'
        presenter_process = slot_presenters.get(slot)
        presenter_started_here = False
        display_created = False
        try:
            (ipc / f'vdisplay_focus_{slot}').write_text('')
            (ipc / f'vdisplay_focus_ack_{slot}').write_text('')
            if presenter_process is None:
                presenter_process = start_dynamic_presenter(slot, package)
                presenter_started_here = True
            create_path = ipc / f'vdisplay_create_{slot}'
            create_ack = ipc / f'vdisplay_create_ack_{slot}'
            (ipc / f'vdisplay_close_{slot}').write_text('')
            (ipc / f'vdisplay_control_ack_{slot}').write_text('')
            create_ack.write_text('')
            atomic_control_write(create_path,
                                 f'{generation} {display_size[0]} '
                                 f'{display_size[1]} {args.display_density}')
            deadline = time.monotonic() + 20
            response = ''
            while time.monotonic() < deadline:
                response = create_ack.read_text().strip()
                if response.startswith(('created ', 'failed ')):
                    break
                if presenter_process.poll() is not None:
                    raise RuntimeError('presenter exited during display creation')
                time.sleep(.05)
            if not response.startswith(f'created {generation} '):
                raise RuntimeError(f'Android display creation failed: {response or "timeout"}')
            display_id = int(response.split()[2])
            display_created = True
            display_id_path = ipc / ('vdisplay_id' if slot == 1 else f'vdisplay{slot}_id')
            if display_id_path.read_text().strip() != str(display_id):
                raise RuntimeError('broker display ID publication mismatch')
            launch_path = ipc / f'app{slot}_launch_request'
            launch_ack = ipc / f'app{slot}_launch_ack'
            # The Android watcher records the last force-stopped package per
            # slot so its task liveness check can distinguish a user close.
            # Clear that generation-local marker before reusing a display;
            # otherwise relaunching the same package is immediately treated
            # as already closed by the prior lifecycle.
            forced_closed_path = ipc / f'app{slot}_forced_closed'
            if forced_closed_path.is_symlink():
                raise RuntimeError('refusing a symlinked app-close marker')
            forced_closed_path.write_text('')
            launch_ack.write_text('')
            atomic_control_write(launch_path,
                                 f'{request_id} {package} {display_id}')
            deadline = time.monotonic() + 30
            response = ''
            while time.monotonic() < deadline:
                response = launch_ack.read_text().strip()
                if response.startswith((f'started {request_id} ',
                                        f'failed {request_id} ')):
                    break
                if presenter_process.poll() is not None:
                    raise RuntimeError('presenter exited during app launch')
                time.sleep(.1)
            if not response.startswith(f'started {request_id} '):
                raise RuntimeError(f'Android activity launch failed: {response or "timeout"}')
            state_path = ipc / f'app{slot}_state'
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if state_path.read_text().strip() == 'RUNNING':
                    break
                if presenter_process.poll() is not None:
                    raise RuntimeError('presenter exited before app became RUNNING')
                time.sleep(.1)
            else:
                raise RuntimeError('Android task did not reach RUNNING')
            # A newly started presenter has no Android frame until this
            # display's activity launches. Its initial title/app-id are
            # already supplied on argv; wait for the frame before requesting
            # the runtime identity update (otherwise the five-second request
            # can never be observed by a presenter with no decor frame).
            window_identity = request_window_identity(slot, package, activation_token)
            slot_presenters[slot] = presenter_process
            if slot == 1: virtual_presenter = presenter_process
            if slot == 2: virtual_presenter2 = presenter_process
            slot_packages[slot] = package
            window_hidden[slot] = False
            window_close_requested[slot] = None
            (ipc / f'vdisplay_close_{slot}').write_text('')
            (ipc / f'vdisplay_control_ack_{slot}').write_text('')
            return {'ok': True, 'slot': slot, 'package': package,
                    'display_id': display_id, 'state': 'RUNNING',
                    'window_title': window_identity['title'],
                    'desktop_app_id': window_identity['app_id']}
        except Exception as error:
            registration = slot_endpoint_registrations.get(slot)
            if registration is not None:
                registration.unlink(missing_ok=True)
                slot_endpoint_registrations[slot] = None
            if presenter_started_here and presenter_process is not None:
                terminate_process_group(presenter_process)
                slot_presenters[slot] = None
            if display_created:
                write_session_control(ipc / f'vdisplay_close_{slot}', 'close')
            return {'ok': False, 'error': 'launch_failed',
                    'detail': str(error)[:240]}

    if storage_scan_apk is not None:
        socket_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        if socket_dir.is_symlink() or socket_dir.stat().st_uid != os.getuid():
            raise RuntimeError(f'AaaS runtime socket directory is not user-owned: {socket_dir}')
        socket_dir.chmod(0o700)
        if control_path.exists() and not control_path.is_socket():
            raise RuntimeError(f'refusing to replace non-socket runtime path: {control_path}')
        control_path.unlink(missing_ok=True)
        control_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        control_server.bind(str(control_path))
        control_path.chmod(0o600)
        control_server.listen(4)
        control_server.setblocking(False)
        control_path_pointer.write_text(str(control_path) + '\n', encoding='utf-8')
        control_path_pointer.chmod(0o600)

    def transition(new_state):
        nonlocal state
        state = new_state
        # Keep the state journal and bind-mounted Android sentinel in step.
        try:
            write_session_state(session, status, new_state)
        except OSError as error:
            print(f'AaaS: session state could not be persisted: {error}',
                  file=sys.stderr, flush=True)
        print(f'AaaS: {new_state} ({session})', flush=True)

    next_workspace_health_check = 0.0

    def validate_runtime_workspace():
        nonlocal next_workspace_health_check
        now = time.monotonic()
        if now < next_workspace_health_check:
            return
        userdata_root = persistent_userdata_path.parent
        sentinels = (
            userdata_root / aaas_userdata.MANIFEST_NAME,
            persistent_userdata_path,
            aaas_storage.media_root_path(WORKSPACE),
            shared_storage_path,
        )
        try:
            android_workspace.validate_mounted_workspace(WORKSPACE, sentinels)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            raise RuntimeError(
                f'external workspace backing became unavailable; stopping Android: {error}'
            ) from error
        next_workspace_health_check = now + WORKSPACE_HEALTH_INTERVAL_SECONDS

    try:
        transition('PREPARING')
        with (session / 'presenter.log').open('wb') as presenter_log, (session / 'android.log').open('wb') as android_log:
            transition('PREPARING_HEADLESS_ANDROID' if args.headless_storage
                       else 'STARTING_PRESENTER')
            if primary_diagnostic:
                presenter = subprocess.Popen(
                    [str(PRESENTER), '--socket', str(ipc / 'wayland.sock'),
                     '--node', paths['AAAS_DRM_RENDER_NODE'],
                     *presenter_trace_args,
                     *presenter_geometry_args(presenter_size, display_size),
                     '--input-socket', str(ipc / 'input.sock'),
                     '--input-session', f'0x{input_session:016x}',
                     '--exit-on-close'],
                    stdout=presenter_log, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                deadline = time.monotonic() + 10
                while not (ipc / 'wayland.sock').exists():
                    if presenter.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('presenter did not start')
                    time.sleep(.1)
            else:
                if args.headless_storage:
                    print('AaaS: host Wayland presenter disabled for headless storage',
                          flush=True)
                else:
                    print('AaaS: primary diagnostic presenter suppressed in app mode',
                          flush=True)
            if args.experimental_virtual_display:
                primary_title, primary_app_id = window_identity_for_package(args.app)
                primary_identity_request = ipc / 'window_identity_1_request'
                primary_identity_ack = ipc / 'window_identity_1_ack'
                primary_socket_path, primary_input_path = prepare_presenter_sockets(1)
                virtual_log_path = session / 'virtual-presenter.log'
                with virtual_log_path.open('wb') as virtual_log:
                    virtual_presenter = subprocess.Popen(
                        [str(PRESENTER), '--socket', str(primary_socket_path),
                         '--node', paths['AAAS_DRM_RENDER_NODE'],
                         *presenter_trace_args,
                         *presenter_geometry_args(presenter_size, display_size),
                         '--input-socket', str(primary_input_path),
                         '--input-session', f'0x{input_session:016x}',
                         '--input-display-id-file', str(ipc / 'vdisplay_id'),
                         '--resize-request', str(ipc / 'vdisplay_resize_1'),
                         '--title', primary_title, '--app-id', primary_app_id,
                         '--identity-request', str(primary_identity_request),
                         '--identity-ack', str(primary_identity_ack)],
                        stdout=virtual_log, stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                deadline = time.monotonic() + 10
                while not primary_socket_path.exists():
                    if virtual_presenter.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('virtual display presenter did not start')
                    time.sleep(.1)
                register_presenter_endpoint(1, primary_socket_path)
                if args.app2:
                    second_title, second_app_id = window_identity_for_package(args.app2)
                    second_socket_path, second_input_path = prepare_presenter_sockets(2)
                    virtual2_log_path = session / 'virtual-presenter2.log'
                    with virtual2_log_path.open('wb') as virtual2_log:
                        virtual_presenter2 = subprocess.Popen(
                            [str(PRESENTER), '--socket',
                             str(second_socket_path), '--node',
                             paths['AAAS_DRM_RENDER_NODE'], *presenter_trace_args,
                             *presenter_geometry_args(presenter_size, display_size),
                             '--input-socket', str(second_input_path),
                             '--input-session', f'0x{input_session:016x}',
                             '--input-display-id-file', str(ipc / 'vdisplay2_id'),
                            '--resize-request', str(ipc / 'vdisplay_resize_2'),
                             '--title', second_title, '--app-id', second_app_id,
                             '--identity-request', str(ipc / 'window_identity_2_request'),
                             '--identity-ack', str(ipc / 'window_identity_2_ack')],
                            stdout=virtual2_log, stderr=subprocess.STDOUT,
                            start_new_session=True,
                        )
                    deadline = time.monotonic() + 10
                    while not second_socket_path.exists():
                        if virtual_presenter2.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError('second virtual display presenter did not start')
                        time.sleep(.1)
                    register_presenter_endpoint(2, second_socket_path)
                slot_presenters[1] = virtual_presenter
                if virtual_presenter2 is not None:
                    slot_presenters[2] = virtual_presenter2
                # No unused presenters are created. Composer consumes endpoint
                # registrations only when Android requests a virtual display.
            # Recheck the complete budget and mount identity immediately before
            # Android can write persistent userdata.
            android_workspace.check(WORKSPACE)
            if audio_hal_overlay is not None:
                audio_log_path = session / 'audio-bridge.log'
                with audio_log_path.open('wb') as audio_log:
                    audio_process = subprocess.Popen(
                        [sys.executable, str(ROOT / 'scripts/aaas_audio.py'),
                         '--socket', str(ipc / 'audio.sock'),
                         '--android-host-uid', str(aaas_idmap.android_host_id(1041)),
                         *(['--playback-sink', args.audio_playback_sink]
                           if args.audio_playback_sink else []),
                         *(['--capture-source', args.audio_capture_source]
                           if args.audio_capture_source else [])],
                        stdout=audio_log, stderr=subprocess.STDOUT,
                        env=env, start_new_session=True)
                audio_deadline = time.monotonic() + 5
                while not (ipc / 'audio.sock').exists():
                    if audio_process.poll() is not None or time.monotonic() >= audio_deadline:
                        raise RuntimeError('session audio bridge failed to create its endpoint')
                    time.sleep(.05)
            transition('STARTING_ANDROID')
            android = subprocess.Popen([sys.executable, str(runner)], env=env,
                                       stdout=android_log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            transition('WAITING_FOR_FRAMEWORK')
            storage_acl_preflight_done = False
            deadline = time.monotonic() + args.startup_timeout + 20
            while not stop:
                validate_runtime_workspace()
                if presenter is not None and presenter.poll() is not None:
                    raise RuntimeError(f'presenter exited before {args.app} became ready')
                if virtual_presenter is not None and virtual_presenter.poll() is not None:
                    raise RuntimeError('virtual display presenter exited before Android startup')
                if virtual_presenter2 is not None and virtual_presenter2.poll() is not None:
                    raise RuntimeError('second virtual display presenter exited before Android startup')
                if android.poll() is not None:
                    raise RuntimeError(f'Android exited before {args.app} became ready')
                if audio_process is not None and audio_process.poll() is not None:
                    raise RuntimeError('session audio bridge exited during Android startup')
                acl_request = ipc / 'storage_acl_request'
                acl_ack = ipc / 'storage_acl_ack'
                if (not storage_acl_preflight_done and shared_storage_path is not None
                        and acl_request.is_file()):
                    try:
                        request_value = acl_request.read_text().strip()
                        if request_value != 'check':
                            raise RuntimeError('invalid Android storage ACL preflight request')
                        aaas_storage.ensure_host_access(
                            aaas_storage.media_root_path(WORKSPACE))
                        aaas_storage.ensure_host_access(shared_storage_path)
                        acl_ack.write_text('ready')
                        storage_acl_preflight_done = True
                        print('AaaS shared storage ACL verified before app launch.',
                              flush=True)
                    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                        acl_ack.write_text('failed')
                        raise RuntimeError(
                            f'shared-storage ACL preflight failed before app launch: {error}') from error
                if not input_ready_reported and INPUT_ADAPTER.is_file():
                    try:
                        size = input_adapter_log.stat().st_size
                        with input_adapter_log.open('rb') as stream:
                            stream.seek(max(0, size - 8192))
                            input_ready_reported = b'"event":"hello"' in stream.read()
                    except OSError:
                        pass
                    if input_ready_reported:
                        print('AaaS input bridge ready; mouse and scroll can be used.',
                              flush=True)
                if status.read_text().strip() == 'RUNNING':
                    transition('RUNNING')
                    running_session = True
                    print(f'AaaS shared Android storage: {shared_storage_path}',
                          flush=True)
                    print('AaaS persistent Android userdata is active.', flush=True)
                    if policy is not None:
                        policy_monitor = aaas_cgroup.ProcessPolicyMonitor(
                            policy, policy_log)
                        policy_monitor.start()
                        print('AaaS: tracking Android memory priority classes', flush=True)
                    launched = args.app if not args.app2 else f'{args.app} and {args.app2}'
                    print(f'{launched} task(s) started. Close an app window to end that app; '
                          'press Ctrl+C to stop the shared runtime.', flush=True)
                    if args.experimental_virtual_display:
                        print(f'AaaS app control socket: {control_path} '
                              '(scripts/aaasctl.py list|launch|close|stop)', flush=True)
                        for extra_package in args.app_extra:
                            result = manager_request({'op': 'launch', 'package': extra_package})
                            if not result.get('ok'):
                                raise RuntimeError(f'launch {extra_package} failed: '
                                                   f'{result.get("error")} '
                                                   f'{result.get("detail", "")}')
                    if args.test_tombstone_capture:
                        (ipc / 'tombstone_capture_test').write_text('segv-child\n')
                        test_deadline = time.monotonic() + 20
                        test_pid = ''
                        while time.monotonic() < test_deadline:
                            try:
                                test_pid = (ipc / 'tombstone_capture_test_pid').read_text().strip()
                            except OSError:
                                pass
                            if tombstone_matches_test_process(tombstone_dir, test_pid):
                                print('AaaS: disposable child tombstone captured and verified',
                                      flush=True)
                                stop = True
                                break
                            if android.poll() is not None or status.read_text().strip() == 'FAILED':
                                break
                            time.sleep(.1)
                        if not stop:
                            try:
                                test_result = (ipc / 'tombstone_capture_test_result').read_text().strip()
                            except OSError:
                                test_result = 'unavailable'
                            raise RuntimeError(
                                'disposable child tombstone was not captured '
                                f'(pid={test_pid or "unknown"}, exit={test_result})')
                    break
                if status.read_text().strip() == 'FAILED' or time.monotonic() >= deadline:
                    raise RuntimeError(f'Android app {args.app} did not become ready')
                time.sleep(.25)
            warned_degraded = False
            while not stop and state == 'RUNNING':
                validate_runtime_workspace()
                if status.read_text().strip() == 'FAILED':
                    reason = classify_session_failure(session_commands)
                    raise RuntimeError(f'Android runtime failed: {reason}')
                clipboard_state_path = ipc / 'clipboard_state'
                try:
                    clipboard_runtime_state = aaas_clipboard.parse_runtime_state(
                        clipboard_state_path.read_text())
                except OSError:
                    clipboard_runtime_state = None
                selected_uid = (
                    clipboard_runtime_state[0]
                    if clipboard_runtime_state and clipboard_runtime_state[1]
                    else None
                )
                if (clipboard_process is not None and
                        (selected_uid != clipboard_active_uid or
                         clipboard_process.poll() is not None)):
                    if clipboard_process.poll() is not None:
                        clipboard_failed_uid = clipboard_active_uid
                        print('AaaS: clipboard bridge exited unexpectedly; '
                              'clipboard sync is disabled for this session',
                              file=sys.stderr, flush=True)
                    else:
                        terminate_process_group(clipboard_process)
                        print('AaaS: clipboard IME selection ended; '
                              'session clipboard bridge stopped', flush=True)
                    aaas_clipboard.clear_session_payloads(ipc)
                    clipboard_process = None
                    clipboard_active_uid = None
                if selected_uid is None:
                    clipboard_failed_uid = None
                elif clipboard_process is None and clipboard_failed_uid != selected_uid:
                    clipboard_log_path = session / 'clipboard-bridge.log'
                    try:
                        with clipboard_log_path.open('ab') as clipboard_log:
                            clipboard_process = aaas_clipboard.start_mapped_bridge(
                                [str(CLIPBOARD_BRIDGE), '--ipc-dir',
                                 str(clipboard_ipc_dir), '--android-uid',
                                 str(selected_uid)],
                                stdout=clipboard_log, env=env,
                            )
                        time.sleep(.1)
                        if clipboard_process.poll() is not None:
                            raise RuntimeError('Wayland clipboard endpoint exited at startup')
                        clipboard_active_uid = selected_uid
                        print('AaaS: Android clipboard IME is selected; '
                              'session Wayland clipboard bridge is active', flush=True)
                    except Exception as error:
                        if clipboard_process is not None:
                            terminate_process_group(clipboard_process)
                        clipboard_process = None
                        clipboard_active_uid = None
                        clipboard_failed_uid = selected_uid
                        aaas_clipboard.clear_session_payloads(ipc)
                        print(f'AaaS: clipboard bridge unavailable: '
                              f'{type(error).__name__}: {error}',
                              file=sys.stderr, flush=True)
                notification_state_path = ipc / 'notification_state'
                try:
                    notification_state = aaas_notifications.parse_runtime_state(
                        notification_state_path.read_text())
                except OSError:
                    notification_state = None
                notification_uid = aaas_notifications.authorized_listener_uid(
                    notification_state)
                if (notification_process is not None and
                        (notification_uid != notification_active_uid or
                         notification_process.poll() is not None)):
                    if notification_process.poll() is not None:
                        notification_failed_uid = notification_active_uid
                        print('AaaS: notification bridge exited unexpectedly; '
                              'forwarding is disabled for this session',
                              file=sys.stderr, flush=True)
                    else:
                        terminate_process_group(notification_process)
                        print('AaaS: Android notification listener authorization ended; '
                              'session adapter stopped', flush=True)
                    aaas_notifications.clear_session_events(ipc)
                    notification_process = None
                    notification_active_uid = None
                if notification_uid is None:
                    notification_failed_uid = None
                elif notification_process is None and notification_failed_uid != notification_uid:
                    notification_log_path = session / 'notification-bridge.log'
                    try:
                        with notification_log_path.open('ab') as notification_log:
                            notification_process = subprocess.Popen(
                                [sys.executable, str(ROOT / 'scripts/aaas_notifications.py'),
                                 '--ipc-dir', str(notification_ipc_dir), '--android-uid',
                                 str(notification_uid)],
                                stdout=notification_log, stderr=subprocess.STDOUT,
                                env=env, start_new_session=True)
                        time.sleep(.1)
                        if notification_process.poll() is not None:
                            raise RuntimeError('host notification D-Bus adapter exited at startup')
                        notification_active_uid = notification_uid
                        print('AaaS: authorized Android notification listener detected; '
                              'session D-Bus adapter is active', flush=True)
                    except Exception as error:
                        if notification_process is not None:
                            terminate_process_group(notification_process)
                        notification_process = None
                        notification_active_uid = None
                        notification_failed_uid = notification_uid
                        aaas_notifications.clear_session_events(ipc)
                        print(f'AaaS: notification adapter unavailable: '
                              f'{type(error).__name__}: {error}',
                              file=sys.stderr, flush=True)
                if control_server is not None:
                    try:
                        client, _ = control_server.accept()
                    except BlockingIOError:
                        client = None
                    if client is not None:
                        with client:
                            try:
                                client.settimeout(5)
                                raw = bytearray()
                                while b'\n' not in raw and len(raw) <= 4096:
                                    chunk = client.recv(min(1024, 4097 - len(raw)))
                                    if not chunk:
                                        break
                                    raw.extend(chunk)
                                if len(raw) > 4096:
                                    reply = {'ok': False, 'error': 'request_too_large'}
                                else:
                                    request = json.loads(bytes(raw).split(b'\n', 1)[0]
                                                         .decode('utf-8'))
                                    reply = manager_request(request)
                            except Exception as error:
                                reply = {'ok': False, 'error': 'invalid_request',
                                         'detail': type(error).__name__}
                            try:
                                client.settimeout(90)
                                client.sendall((json.dumps(reply, separators=(',', ':')) + '\n')
                                               .encode('utf-8'))
                            except OSError as error:
                                print(f'AaaS: control client disconnected: {error}',
                                      file=sys.stderr, flush=True)
                if presenter is not None and presenter.poll() is not None:
                    print('AaaS: presenter exited; stopping Android', flush=True)
                    break
                if args.experimental_virtual_display:
                    for index, process in list(slot_presenters.items()):
                        if process is None:
                            continue
                        app_state = (ipc / f'app{index}_state').read_text().strip()
                        ack = (ipc / f'vdisplay_control_ack_{index}').read_text().strip()
                        if app_state == 'CLOSED' and ack.startswith('released'):
                            if process.poll() is None:
                                terminate_process_group(process)
                            registration = slot_endpoint_registrations.get(index)
                            if registration is not None:
                                registration.unlink(missing_ok=True)
                                slot_endpoint_registrations[index] = None
                            slot_presenters[index] = None
                            slot_packages[index] = None
                            window_hidden[index] = True
                            (ipc / f'app{index}_state').write_text('CLOSED\n')
                            continue
                        exited = process.poll() is not None
                        if not exited and app_state != 'CLOSED':
                            continue
                        if exited:
                            print(f'AaaS: presenter output {index} exited with '
                                  f'status {process.returncode}', flush=True)
                        else:
                            print(f'AaaS: Android app slot {index} reported CLOSED',
                                  flush=True)
                        if window_close_requested[index] is None:
                            registration = slot_endpoint_registrations.get(index)
                            if registration is not None:
                                registration.unlink(missing_ok=True)
                                slot_endpoint_registrations[index] = None
                            write_session_control(ipc / f'vdisplay_close_{index}', 'close')
                            window_close_requested[index] = time.monotonic()
                            print(f'AaaS: closing Android output {index} independently',
                                  flush=True)
                        if not exited:
                            pass
                        ack = (ipc / f'vdisplay_control_ack_{index}').read_text().strip()
                        if ack.startswith('failed'):
                            raise RuntimeError(f'Android display {index} release failed: {ack}')
                        if ack.startswith('released'):
                            if slot_presenters.get(index) is process and exited:
                                slot_presenters[index] = None
                                (ipc / f'app{index}_state').write_text('CLOSED\n')
                                if index == 1: virtual_presenter = None
                                if index == 2: virtual_presenter2 = None
                        if (not ack.startswith('released') and
                                time.monotonic() - window_close_requested[index] > 8):
                            raise RuntimeError(f'Android display {index} release timed out')
                    if status.read_text().strip() == 'STOPPING':
                        break
                if android.poll() is not None or status.read_text().strip() == 'FAILED':
                    raise RuntimeError('Android runtime failed')
                if (policy_monitor is not None and policy_monitor.degraded
                        and not warned_degraded):
                    warned_degraded = True
                    print('AaaS: memory policy monitor degraded; Android continues',
                          file=sys.stderr, flush=True)
                if (resource_sample_log is not None and
                        periodic_sample_count < aaas_resources.MAX_PERIODIC_SAMPLES and
                        time.monotonic() >= next_resource_sample):
                    try:
                        aaas_resources.append_sample(
                            resource_sample_log,
                            aaas_resources.snapshot(
                                WORKSPACE, resource_policy_path,
                                tracked_packages=[package for package in (args.app, args.app2)
                                                  if package]))
                        periodic_sample_count += 1
                        next_resource_sample = time.monotonic() + args.resource_sample_interval
                    except OSError as error:
                        print(f'AaaS: periodic resource sample unavailable: {error}',
                              file=sys.stderr, flush=True)
                time.sleep(.25)
        transition('STOPPING')
        return 0
    except Exception as error:
        print(f'AaaS: {error}', file=sys.stderr, flush=True)
        try:
            failure_reason = classify_session_failure(session_commands)
        except UnboundLocalError:
            failure_reason = 'runtime_or_control_failure'
        try:
            failure_record = {
                'reason': failure_reason,
                'detail': f'{type(error).__name__}: {str(error)[:400]}',
                'monotonic_ns': time.monotonic_ns(),
            }
            failure_path = session / 'failure.json'
            failure_path.write_text(json.dumps(failure_record, indent=2) + '\n')
            failure_path.chmod(0o600)
        except (OSError, UnboundLocalError):
            pass
        transition('FAILED')
        return 1
    finally:
        cleanup_failed = False
        if collect_resource_diagnostics:
            try:
                aaas_resources.write_snapshot(
                    session / 'resources-shutdown-begin.json', workspace=WORKSPACE,
                    policy_cgroup=resource_policy_path,
                    tracked_packages=[package for package in (args.app, args.app2)
                                      if package])
            except OSError as error:
                print(f'AaaS: shutdown resource snapshot unavailable: {error}',
                      file=sys.stderr, flush=True)
        if policy_monitor is not None:
            try:
                policy_monitor.stop(timeout=12)
            except Exception as error:
                cleanup_failed = True
                print(f'AaaS: memory policy monitor cleanup failed: {error}',
                      file=sys.stderr, flush=True)
        if control_server is not None:
            control_server.close()
            try:
                control_path.unlink(missing_ok=True)
                control_path_pointer.unlink(missing_ok=True)
                socket_dir.rmdir()
            except OSError as error:
                print(f'AaaS: cannot remove session control socket: {error}',
                      file=sys.stderr, flush=True)
        try:
            failed_before_cleanup = (state == 'FAILED' or
                                     status.read_text().strip() == 'FAILED')
        except OSError:
            failed_before_cleanup = True

        if android is not None and android.poll() is None:
            # Exporting the bounded Android tombstone ring can take several
            # seconds when the runtime has unrelated crashing vendor services.
            # Keep the wait finite while allowing the watcher to finish copies.
            try:
                capture_status = request_tombstone_capture(ipc, timeout=10.0)
            except OSError as error:
                capture_status = 'workspace_unavailable'
                print(f'AaaS: tombstone capture request unavailable: {error}',
                      file=sys.stderr, flush=True)
        else:
            capture_status = 'runtime_unavailable'
        previous_ime = ipc / 'clipboard_ime_previous'
        settings_request = ipc / 'clipboard_settings_request'
        ime_ack = ipc / 'clipboard_ime_ack'
        if (android is not None and android.poll() is None and
                clipboard_ime_restore_pending(previous_ime) and
                not settings_request.is_symlink() and not ime_ack.is_symlink()):
            try:
                ime_ack.write_text('')
                settings_request.write_text('restore\n')
                restore_deadline = time.monotonic() + 5
                while time.monotonic() < restore_deadline:
                    if ime_ack.read_text().strip() == 'restore:0':
                        print('AaaS: restored the pre-session Android input method',
                              flush=True)
                        break
                    time.sleep(.05)
                else:
                    cleanup_failed = True
                    print('AaaS: could not restore the pre-session input method',
                          file=sys.stderr, flush=True)
            except OSError as error:
                cleanup_failed = True
                print(f'AaaS: input-method restoration failed: {error}',
                      file=sys.stderr, flush=True)
        if android is not None and android.poll() is None:
            try:
                write_status_sentinel(status, 'STOPPING')
            except OSError as error:
                print(f'AaaS: cannot persist STOPPING status: {error}',
                      file=sys.stderr, flush=True)

        if args.experimental_virtual_display and android is not None:
            shutdown_file = ipc / 'display_broker_shutdown'
            deadline = time.monotonic() + 5
            broker_released = False
            while time.monotonic() < deadline:
                try:
                    if shutdown_file.read_text().strip() == 'released':
                        print('AaaS: Android released its virtual display before shutdown',
                              flush=True)
                        broker_released = True
                        break
                except OSError:
                    pass
                time.sleep(.1)
            if not broker_released and android.poll() is None:
                print('AaaS: virtual display shutdown handshake timed out',
                      file=sys.stderr, flush=True)
                cleanup_failed = True
        cleanup_processes = [notification_process, clipboard_process, audio_process, android,
                             *slot_presenters.values(), virtual_presenter2,
                             virtual_presenter, presenter]
        seen_processes = set()
        for process in cleanup_processes:
            if process is not None and id(process) in seen_processes:
                continue
            if process is not None:
                seen_processes.add(id(process))
            try:
                terminate_process_group(process)
            except Exception as error:
                cleanup_failed = True
                print(f'AaaS: process cleanup failed: {error}',
                      file=sys.stderr, flush=True)
        if clipboard_ipc_dir is not None:
            try:
                aaas_clipboard.clear_session_payloads(ipc)
                if not aaas_clipboard.cleanup_session_ipc(ipc):
                    cleanup_failed = True
                    print('AaaS: clipboard IPC cleanup left an unexpected object',
                          file=sys.stderr, flush=True)
            except OSError as error:
                cleanup_failed = True
                print(f'AaaS: clipboard IPC cleanup failed: {error}',
                      file=sys.stderr, flush=True)
        if notification_ipc_dir is not None:
            try:
                if not aaas_notifications.clear_session_events(ipc):
                    cleanup_failed = True
                    print('AaaS: notification IPC cleanup left an unexpected object',
                          file=sys.stderr, flush=True)
            except OSError as error:
                cleanup_failed = True
                print(f'AaaS: notification IPC cleanup failed: {error}',
                      file=sys.stderr, flush=True)
        try:
            write_crash_artifact_manifest(session, tombstone_dir, capture_status,
                                          graphics_provenance)
        except OSError as error:
            print(f'AaaS: crash-artifact manifest unavailable: {error}',
                  file=sys.stderr, flush=True)
        if policy is not None:
            summary = policy_monitor.summary() if policy_monitor is not None else {}
            try:
                cleanup = policy.shutdown()
            except Exception as error:
                cleanup = {'removed': False,
                           'failures': {'shutdown': f'{type(error).__name__}: {error}'}}
            summary['cleanup'] = cleanup
            try:
                (session / 'policy-summary.json').write_text(
                    json.dumps(summary, indent=1, default=str) + '\n')
            except OSError as error:
                cleanup_failed = True
                print(f'AaaS: memory policy summary unavailable: {error}',
                      file=sys.stderr, flush=True)
            if cleanup['failures']:
                cleanup_failed = True
                print(f'AaaS: memory policy cleanup issues: {cleanup["failures"]}',
                      file=sys.stderr, flush=True)
            else:
                print(f'AaaS: memory policy hierarchy removed ({policy.session_dir})',
                      flush=True)
        if collect_resource_diagnostics:
            try:
                aaas_resources.write_snapshot(
                    session / 'resources-shutdown.json', workspace=WORKSPACE,
                    policy_cgroup=resource_policy_path,
                    tracked_packages=[package for package in (args.app, args.app2)
                                      if package])
                print(f'AaaS: resource snapshots recorded in {session}', flush=True)
            except OSError as error:
                print(f'AaaS: final resource snapshot unavailable: {error}',
                      file=sys.stderr, flush=True)
        if native_bridge_overlay is not None and native_bridge_overlay.exists():
            try:
                shutil.rmtree(native_bridge_overlay)
                print('AaaS: session-local Native Bridge overlay removed', flush=True)
            except OSError as error:
                cleanup_failed = True
                print(f'AaaS: Native Bridge overlay cleanup failed: {error}',
                      file=sys.stderr, flush=True)
        diagnostic_native_libs = session / 'diagnostic-apk-native-libs'
        if diagnostic_native_libs.exists():
            try:
                shutil.rmtree(diagnostic_native_libs)
                print('AaaS: session-local diagnostic APK libraries removed', flush=True)
            except OSError as error:
                cleanup_failed = True
                print(f'AaaS: diagnostic APK library cleanup failed: {error}',
                      file=sys.stderr, flush=True)
        terminal_failed = (failed_before_cleanup or state == 'FAILED' or cleanup_failed)
        if terminal_failed:
            if state != 'FAILED':
                transition('FAILED')
        elif state != 'STOPPED':
            transition('STOPPED')
        try:
            final_status = finalize_status_sentinel(status, failed=terminal_failed)
        except OSError as error:
            final_status = 'unavailable_workspace'
            cleanup_failed = True
            print(f'AaaS: terminal status could not be persisted: {error}',
                  file=sys.stderr, flush=True)
        print(f'AaaS: session status {final_status}', flush=True)
        print(f'AaaS logs: {session}', flush=True)
        os.close(lock_fd)


if __name__ == '__main__':
    sys.exit(main())
