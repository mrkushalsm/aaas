#!/usr/bin/env python3
"""Run an Android 16 application as a foreground AaaS session.

The M1B.8 framework runner has inherited, uncommitted experiments. This
launcher transforms a hash-checked copy rather than editing that runner.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shlex
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aaas_cgroup
import aaas_bluetooth
import aaas_resources


ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = Path('/run/media/mrkus/Homework/aaas-workspace')
TMP = WORKSPACE / 'tmp'
RUNNER = ROOT / 'scripts/aaas_session_runner_base.py'
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
FRAMEWORK_TRANSITION_BUILDER = ROOT / 'scripts/build_m1e_transition_input_overlay.py'
VDC_OVERLAY = TMP / 'm1d_vdc_overlay/vdc'
RUNNER_SHA256 = '2e93ad37536fc0cd84b434a646545583115bdd84d67eb0439fa05ae6e7e73b8e'
SWIFTSHADER_RUNTIME_OVERLAY = TMP / 'm1e_swiftshader_fixed_notrace_v2.so'
SWIFTSHADER_RUNTIME_SHA256 = 'e42a0bd8dfe3e0eea6c3d6753f9f9fa254d348366847241ca3c7e4b9ac9affee'
SWIFTSHADER_RUNTIME_SOURCE_DIFF_SHA256 = '49c1ce42f0cb09dd69a81645c9a3bec91a390c958ac3d49ff2bd3edf4df86ece'
LMKD_DIAGNOSTIC_SHA256 = '9780759ba36e50d061064f05c77520809f3291edad6a43a1495e9d91f21d54bd'
LMKD_SOURCE_BUILT_SHA256 = 'a36135b6948342163186fe57acb9de0245fe00aeafcb9556c48a2e4c52f291ce'
COMPOSER_PORTRAIT_SHA256 = 'cd55e7418a469e84c839bfec287b1bce238a43daa28f50900acf3174c17e3a46'
VDC_OVERLAY_SHA256 = 'b91c93e100f3892880665f9b47630d1170dc1fce4ee3cf249ec8f20e583fd764'
DEFAULT_APP_PACKAGE = 'com.android.settings'
APP_PACKAGE_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+')
SESSION_STATUS_VALUES = {'STARTING', 'RUNNING', 'STOPPING', 'STOPPED', 'FAILED'}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
        subprocess.run(
            ['newuidmap', str(process.pid), '0', str(os.getuid()), '1',
             '1', '100000', '65535'], check=True,
        )
        subprocess.run(
            ['newgidmap', str(process.pid), '0', str(os.getgid()), '1',
             '1', '100000', '65535'], check=True,
        )
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
                        input_response_probe_apk2=None):
    if sha256(RUNNER) != RUNNER_SHA256:
        raise RuntimeError('inherited runtime runner changed; review the session transformation')
    app_package = validate_app_package(app_package)
    if app_package2 is not None:
        app_package2 = validate_app_package(app_package2)
        if app_package2 == app_package:
            raise ValueError('app2 must differ from app')
        if not experimental_virtual_display:
            raise ValueError('app2 requires --experimental-virtual-display')
    input_response_probe_binds = ""
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
        input_response_probe_binds += (
            f'  --dir /product/app/{overlay_name} \\\n'
            f'  --ro-bind "{probe_apk}" '
            f'/product/app/{overlay_name}/{overlay_name}.apk \\\n'
        )
    timeout = '140'
    source = RUNNER.read_text()
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
        input_response_probe_binds + '{mapper_bind}{allocator_bind}',
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
        '    kill -9 $INIT_PID 2>/dev/null\n  \'\n"""',
        '    :\n    ) &\n    exec /system/bin/init second_stage\n  \'\n"""',
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
    source = replace_once(
        source, '    exec /system/bin/init second_stage',
        tombstone_capture_worker + '    exec /system/bin/init second_stage',
    )
    source = replace_once(source, '    ipc_dir = tmp_dir / "aaas_ipc"',
                          '    ipc_dir = Path(os.environ["AAAS_SESSION_IPC"])')
    if experimental_virtual_display:
        source = replace_once(
            source,
            '    ipc_dir = Path(os.environ["AAAS_SESSION_IPC"])',
            '    vdisplay_dex = Path(os.environ["AAAS_VDISPLAY_DEX"])\n'
            '    vdisplay_rc = Path(os.environ["AAAS_VDISPLAY_RC"])\n'
            '    session_commands = Path(os.environ["AAAS_SESSION_COMMANDS"])\n'
            '    vdisplay_broker_bind = (\n'
            '        f\'  --ro-bind "{vdisplay_dex}" /system/framework/aaas-display-broker.dex \' + chr(92) + "\\n"\n'
            '        f\'  --ro-bind "{vdisplay_rc}" /system/etc/init/aaas-display-broker.rc \' + chr(92) + "\\n"\n'
            '        f\'  --bind "{session_commands}" /aaas_session_commands \' + chr(92) + "\\n")\n'
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
        + '{vdc_bind}{framework_ime_bind}{lmkd_bind}{status_bind}{logcat_bind}{input_adapter_bind}'
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
    source = replace_once(
        source,
        '    echo "=== TESTING ACTIVITY LAUNCH (SETTINGS) ==="\n'
        '    /system/bin/cmd activity start-activity -W -n com.android.settings/.Settings || '
        '/system/bin/am start -W -n com.android.settings/.Settings',
        '    echo "=== RESOLVING AND LAUNCHING ANDROID APPLICATION ==="\n'
        '    APP_COMPONENT=$(/system/bin/cmd package resolve-activity --brief --user 0 '
        '-a android.intent.action.MAIN -c android.intent.category.LAUNCHER '
        f'-p {app_package} 2>&1 | /system/bin/toybox tee -a /aaas_session_commands '
        '| /system/bin/toybox tail -n 1)\n'
        '    case "$APP_COMPONENT" in */*) ;; *) echo "No launchable activity for '
        f'{app_package}"; echo FAILED > /aaas_session_status; exit 1 ;; esac\n'
        '    /system/bin/cmd activity start-activity -W -n "$APP_COMPONENT" || '
        '/system/bin/am start -W -n "$APP_COMPONENT"',
    )
    if experimental_virtual_display:
        source = replace_once(
            source,
            '    echo "=== RESOLVING AND LAUNCHING ANDROID APPLICATION ==="',
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
        '      /system/bin/dumpsys activity activities | '
        '/system/bin/toybox grep -F "u0 $APP_PACKAGE/" >/dev/null 2>&1\n'
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
    if experimental_virtual_display:
        readiness_and_watch = readiness_and_watch.replace(
            '    echo RUNNING > /aaas_session_status\n',
            '    echo RUNNING > /aaas_session_status\n'
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
            '      /system/bin/dumpsys activity activities | '
            '/system/bin/toybox grep -F "u0 $APP_PACKAGE2/" >/dev/null 2>&1\n'
            '    }}\n'
            '    /system/bin/toybox sleep 3\n'
            '    if [ "$(/system/bin/getprop sys.boot_completed)" != "1" ] || '
            '! aaas_app_task_alive || ! aaas_app2_task_alive; then\n'
        )
        readiness_and_watch = readiness_and_watch.replace(
            '&& aaas_app_task_alive',
            '&& (aaas_app_task_alive || aaas_app2_task_alive)', 1)
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
        if app_package2 is not None:
            for slot in (1, 2):
                suffix = '' if slot == 1 else '2'
                app_variable = 'APP_PACKAGE' + suffix
                display_variable = 'VD_ID' + suffix
                adapter_pid_variable = 'VDISPLAY' + ('2' if slot == 2 else '') + '_INPUT_ADAPTER_PID'
                socket_name = 'input-vdisplay' + ('-2' if slot == 2 else '') + '.sock'
                log_name = 'aaas_vdisplay' + ('2' if slot == 2 else '') + '_input_adapter.log'
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
                    '          else\n'
                    f'            echo "failed $REQ_ID launch" > /dev/aaas/app{slot}_launch_ack\n'
                    '          fi\n'
                    '          ;;\n'
                    '        esac\n'
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
                '      /system/bin/toybox sleep 1\n'
            )
        else:
            readiness_and_watch += '      /system/bin/toybox sleep 2\n'
        readiness_and_watch += '    done\n'
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
    else:
        readiness_and_watch += (
            '; do\n'
            '      /system/bin/toybox sleep 2\n'
            '    done\n'
            '    echo FAILED > /aaas_session_status\n'
        )
    readiness_and_watch += (
        '    exit 1\n'
        '    if [ "{settings_sigquit}"'
    )
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
        )
    except (OSError, ValueError, KeyError):
        return False


def framework_transition_overlay_is_current():
    source = WORKSPACE / 'rootfs_m1b1/system/framework/framework.jar'
    try:
        receipt = json.loads(FRAMEWORK_TRANSITION_RECEIPT.read_text())
        return (
            receipt.get('revision') == '99b01a65cc4c104933788b3143285ab6bae65827'
            and receipt.get('input') == str(source.resolve())
            and receipt.get('input_sha256') == sha256(source)
            and receipt.get('apktool_sha256') == sha256(APKTOOL)
            and receipt.get('builder') == str(FRAMEWORK_TRANSITION_BUILDER.resolve())
            and receipt.get('builder_sha256') == sha256(FRAMEWORK_TRANSITION_BUILDER)
            and receipt.get('overlay') == str(FRAMEWORK_TRANSITION_OVERLAY.resolve())
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
        '--original', str(WORKSPACE / 'rootfs_m1b1/system/framework/framework.jar'),
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
                        diagnostic_framework_sha256=None):
    check = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/android_workspace.py'),
         '--workspace', str(WORKSPACE), 'check'],
        capture_output=True, text=True,
    )
    if check.returncode:
        raise RuntimeError(check.stdout + check.stderr)
    mount = json.loads(check.stdout)['mount']
    if mount['source'] != '/dev/sda2' or mount['filesystem'] != 'ntfs3':
        raise RuntimeError(f'unexpected workspace mount: {mount}')
    if not PRESENTER.is_file():
        raise RuntimeError(f'build the presenter first: {PRESENTER}')
    if not INPUT_ADAPTER.is_file():
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
    return paths


def build_multi_output_composer():
    """Build the two-endpoint Composer required by the two-app session."""
    command = [
        'make', '-C', str(ROOT / 'experiments/m1b/composer_aaas'),
        f'BIN={COMPOSER_MULTI_OUTPUT}',
        'AAAS_ENABLE_VIRTUAL_DISPLAY=1',
        'AAAS_VIRTUAL_DISPLAY_CAPACITY=2',
        'AAAS_DISPLAY_WIDTH=720',
        'AAAS_DISPLAY_HEIGHT=1280',
        'all',
    ]
    subprocess.run(command, check=True)
    if not COMPOSER_MULTI_OUTPUT.is_file():
        raise RuntimeError(f'two-output Composer build missing: {COMPOSER_MULTI_OUTPUT}')
    return COMPOSER_MULTI_OUTPUT


def show_primary_diagnostic(args):
    """Keep the primary Wayland window for diagnostics, not normal app mode."""
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
    parser.add_argument('--software-keyboard', action='store_true',
                        help='Allow Android to show its software keyboard (mobile/accessibility mode)')
    parser.add_argument('--experimental-virtual-display', action='store_true',
                        help='Use the isolated M1E trusted virtual-display prototype')
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
    parser.add_argument('--resource-sample-interval', type=float, default=0.0,
                        help='Opt in to host/cgroup resource snapshots; optionally sample every N seconds (0 disables periodic samples, max 3600 samples)')
    parser.add_argument('--test-tombstone-capture', action='store_true',
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
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
    if args.startup_timeout < 1:
        parser.error('startup timeout must be positive')
    if args.test_tombstone_capture and args.app2:
        parser.error('--test-tombstone-capture requires a single-app disposable session')
    if not 0.0 <= args.resource_sample_interval <= 3600.0:
        parser.error('resource sample interval must be between 0 and 3600 seconds')
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
    if not args.diagnostic_framework_overlay and not framework_transition_overlay_is_current():
        if not APKTOOL.is_file():
            raise RuntimeError(f'missing pinned apktool for Android transition input overlay: {APKTOOL}')
        build_framework_transition_overlay()
    paths = verify_requirements(use_source_lmkd=args.use_source_lmkd,
                                orientation=args.orientation,
                                diagnostic_vulkan_overlay=args.diagnostic_vulkan_overlay,
                                diagnostic_framework_overlay=args.diagnostic_framework_overlay,
                                diagnostic_framework_sha256=args.diagnostic_framework_sha256)
    if args.experimental_virtual_display:
        if not COMPOSER_VDISPLAY.is_file() or not VDISPLAY_BROKER_DEX.is_file():
            raise RuntimeError('build the M1E virtual-display Composer and broker first')
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
                build_multi_output_composer() if args.app2 else COMPOSER_VDISPLAY)
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
    bluetooth_policy_dir = session / 'bluetooth-policy'
    bluetooth_policy_manifest = aaas_bluetooth.create_unavailable_policy(
        WORKSPACE / 'rootfs_m1b1', bluetooth_policy_dir)
    (session / 'bluetooth-policy.json').write_text(
        json.dumps(bluetooth_policy_manifest, indent=2) + '\n')
    (session / 'bluetooth-policy.json').chmod(0o600)
    provenance_path = session / 'runtime-graphics-provenance.json'
    provenance_path.write_text(json.dumps(graphics_provenance, indent=2) + '\n')
    provenance_path.chmod(0o600)
    prefix = f'm1b84_session_{os.getpid()}_'
    tombstone_dir = session / 'tombstones'
    tombstone_dir.mkdir(mode=0o700)
    ipc = session / 'ipc'
    ipc.mkdir(mode=0o711)
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
        (ipc / 'vdisplay2_id').write_text('enabled\n' if args.app2 else '')
        (ipc / 'vdisplay2_id').chmod(0o666)
        (ipc / 'display_broker_shutdown').write_text('')
        (ipc / 'display_broker_shutdown').chmod(0o666)
        for index in (1, 2):
            for name in (f'vdisplay_resize_{index}', f'vdisplay_close_{index}',
                         f'vdisplay_control_ack_{index}', f'app{index}_state',
                         f'vdisplay_focus_{index}', f'vdisplay_focus_ack_{index}',
                         f'vdisplay_create_{index}', f'vdisplay_create_ack_{index}',
                         f'app{index}_launch_request', f'app{index}_launch_ack'):
                path = ipc / name
                path.write_text('')
                path.chmod(0o666)
    for name in ('tombstone_capture_request', 'tombstone_capture_ack',
                 'tombstone_capture_test_pid',
                 'tombstone_capture_test_result'):
        path = ipc / name
        path.write_text('')
        path.chmod(0o600)
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
    runner = make_session_runner(session, desktop_ime=not args.software_keyboard,
                                 app_package=args.app,
                                 experimental_virtual_display=args.experimental_virtual_display,
                                 app_package2=args.app2,
                                 bluetooth_policy_dir=bluetooth_policy_dir,
                                 input_response_probe_apk=args.input_response_probe_apk,
                                 input_response_probe_apk2=args.input_response_probe_apk2)
    env = os.environ.copy()
    env.update(paths)
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
               AAAS_INPUT_ADAPTER=str(INPUT_ADAPTER) if INPUT_ADAPTER.is_file() else '',
               AAAS_INPUT_ADAPTER_LOG=str(input_adapter_log))
    if args.experimental_virtual_display:
        env.update(AAAS_VDISPLAY_DEX=str(VDISPLAY_BROKER_DEX),
                   AAAS_VDISPLAY_RC=str(VDISPLAY_BROKER_RC),
                   AAAS_SESSION_COMMANDS=str(session_commands),
                   AAAS_VDISPLAY_INPUT_ADAPTER_LOG=str(vdisplay_input_adapter_log))
        if args.app2:
            env['AAAS_VDISPLAY2_INPUT_ADAPTER_LOG'] = str(vdisplay2_input_adapter_log)
    presenter = virtual_presenter = virtual_presenter2 = android = None
    presenter_trace_args = []
    if args.diagnostic_composer_overlay:
        presenter_trace_args.append('--trace-buffer-identities')
    if args.trace_staging_stages:
        presenter_trace_args.append('--trace-staging-stages')
    if args.trace_input_response_roi:
        presenter_trace_args.extend(['--trace-input-response-roi', args.trace_input_response_roi])
    state = 'CREATED'
    input_ready_reported = False
    running_session = False
    window_close_requested = {1: None, 2: None}
    slot_packages = {1: args.app, 2: args.app2}
    slot_lifecycle_generation = {1: 0, 2: 0}
    control_path = ipc / 'aaas-control.sock'
    control_server = None
    capture_status = 'not_requested'

    def atomic_control_write(path, value):
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_text(value + '\n')
        temporary.chmod(0o666)
        os.replace(temporary, path)

    def start_dynamic_presenter(slot, package):
        socket_path = ipc / ('wayland-vdisplay.sock' if slot == 1
                             else 'wayland-vdisplay.sock-2')
        input_path = ipc / ('input-vdisplay.sock' if slot == 1
                            else 'input-vdisplay-2.sock')
        display_path = ipc / f'vdisplay{2 if slot == 2 else ""}_id'
        resize_path = ipc / f'vdisplay_resize_{slot}'
        log_path = session / ('virtual-presenter.log' if slot == 1
                              else 'virtual-presenter2.log')
        # A released slot may retain the last xdg_toplevel configure. A new
        # Android display starts at presenter_size, so never replay the old
        # lifecycle's request into its new VirtualDisplay.
        resize_path.write_text('')
        socket_path.unlink(missing_ok=True)
        with log_path.open('ab') as presenter_log:
            process = subprocess.Popen(
                [str(PRESENTER), '--socket', str(socket_path), *presenter_trace_args,
                 '--width', presenter_size[0], '--height', presenter_size[1],
                 '--display-width', display_size[0],
                 '--display-height', display_size[1],
                 '--input-socket', str(input_path),
                 '--input-session', f'0x{input_session:016x}',
                 '--input-display-id-file', str(display_path),
                 '--resize-request', str(resize_path),
                 '--title', f'AaaS: {package}', '--app-id',
                 'org.aaas.' + package.replace('.', '-'), '--exit-on-close'],
                stdout=presenter_log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + 10
        while not socket_path.exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                terminate_process_group(process)
                raise RuntimeError(f'presenter for slot {slot} did not start')
            time.sleep(.05)
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
                         'state': (ipc / f'app{slot}_state').read_text().strip(),
                         'presenter_pid': (proc.pid if proc is not None and
                                           proc.poll() is None else None)}
                        for slot, proc in ((1, virtual_presenter),
                                           (2, virtual_presenter2))
                        if slot_packages[slot] is not None or proc is not None]}
        if op == 'stop':
            stop = True
            return {'ok': True, 'state': 'STOPPING'}
        if op == 'close':
            slot = request.get('slot')
            if slot not in (1, 2):
                return {'ok': False, 'error': 'invalid_slot'}
            process = virtual_presenter if slot == 1 else virtual_presenter2
            if process is None:
                return {'ok': False, 'error': 'window_not_running'}
            terminate_process_group(process)
            return {'ok': True, 'slot': slot, 'state': 'CLOSING'}
        if op != 'launch':
            return {'ok': False, 'error': 'unsupported_operation'}
        try:
            package = validate_app_package(request.get('package'))
        except ValueError:
            return {'ok': False, 'error': 'invalid_package'}
        if args.app2 is None:
            return {'ok': False, 'error': 'capacity_requires_two_output_session'}
        if any(slot_packages[slot] == package and
               ((virtual_presenter if slot == 1 else virtual_presenter2) is not None)
               for slot in (1, 2)):
            return {'ok': False, 'error': 'package_already_running'}
        candidates = [slot for slot, proc in ((1, virtual_presenter),
                                               (2, virtual_presenter2))
                      if proc is None and
                      (ipc / f'vdisplay_control_ack_{slot}').read_text().strip().startswith('released')]
        if not candidates:
            return {'ok': False, 'error': 'capacity_exhausted'}
        slot = candidates[0]
        slot_lifecycle_generation[slot] += 1
        generation = slot_lifecycle_generation[slot]
        request_id = f'{os.urandom(8).hex()}'
        presenter_process = None
        display_created = False
        try:
            (ipc / f'vdisplay_focus_{slot}').write_text('')
            (ipc / f'vdisplay_focus_ack_{slot}').write_text('')
            presenter_process = start_dynamic_presenter(slot, package)
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
            display_id_path = ipc / f'vdisplay{2 if slot == 2 else ""}_id'
            if display_id_path.read_text().strip() != str(display_id):
                raise RuntimeError('broker display ID publication mismatch')
            launch_path = ipc / f'app{slot}_launch_request'
            launch_ack = ipc / f'app{slot}_launch_ack'
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
            if slot == 1:
                virtual_presenter = presenter_process
            else:
                virtual_presenter2 = presenter_process
            slot_packages[slot] = package
            window_close_requested[slot] = None
            (ipc / f'vdisplay_close_{slot}').write_text('')
            (ipc / f'vdisplay_control_ack_{slot}').write_text('')
            return {'ok': True, 'slot': slot, 'package': package,
                    'display_id': display_id, 'state': 'RUNNING'}
        except Exception as error:
            if presenter_process is not None:
                terminate_process_group(presenter_process)
            if display_created:
                write_session_control(ipc / f'vdisplay_close_{slot}', 'close')
            return {'ok': False, 'error': 'launch_failed',
                    'detail': str(error)[:240]}

    if args.experimental_virtual_display:
        control_path.unlink(missing_ok=True)
        control_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        control_server.bind(str(control_path))
        control_path.chmod(0o600)
        control_server.listen(4)
        control_server.setblocking(False)

    def transition(new_state):
        nonlocal state
        state = new_state
        # Keep the state journal and bind-mounted Android sentinel in step.
        write_session_state(session, status, new_state)
        print(f'AaaS: {new_state} ({session})', flush=True)

    try:
        transition('PREPARING')
        with (session / 'presenter.log').open('wb') as presenter_log, (session / 'android.log').open('wb') as android_log:
            transition('STARTING_PRESENTER')
            if primary_diagnostic:
                presenter = subprocess.Popen(
                    [str(PRESENTER), '--socket', str(ipc / 'wayland.sock'),
                     *presenter_trace_args,
                     '--width', presenter_size[0], '--height', presenter_size[1],
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
                print('AaaS: primary diagnostic presenter suppressed in app mode',
                      flush=True)
            if args.experimental_virtual_display:
                virtual_log_path = session / 'virtual-presenter.log'
                with virtual_log_path.open('wb') as virtual_log:
                    virtual_presenter = subprocess.Popen(
                        [str(PRESENTER), '--socket', str(ipc / 'wayland-vdisplay.sock'),
                         *presenter_trace_args,
                         '--width', presenter_size[0], '--height', presenter_size[1],
                     '--display-width', display_size[0],
                     '--display-height', display_size[1],
                         '--input-socket', str(ipc / 'input-vdisplay.sock'),
                         '--input-session', f'0x{input_session:016x}',
                         '--input-display-id-file', str(ipc / 'vdisplay_id'),
                         '--resize-request', str(ipc / 'vdisplay_resize_1'),
                         '--title', f'AaaS: {args.app}', '--app-id',
                         'org.aaas.' + args.app.replace('.', '-'), '--exit-on-close'],
                        stdout=virtual_log, stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                deadline = time.monotonic() + 10
                while not (ipc / 'wayland-vdisplay.sock').exists():
                    if virtual_presenter.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('virtual display presenter did not start')
                    time.sleep(.1)
                if args.app2:
                    virtual2_log_path = session / 'virtual-presenter2.log'
                    with virtual2_log_path.open('wb') as virtual2_log:
                        virtual_presenter2 = subprocess.Popen(
                            [str(PRESENTER), '--socket',
                             str(ipc / 'wayland-vdisplay.sock-2'), *presenter_trace_args,
                             '--width', presenter_size[0], '--height', presenter_size[1],
                             '--display-width', display_size[0],
                             '--display-height', display_size[1],
                             '--input-socket', str(ipc / 'input-vdisplay-2.sock'),
                             '--input-session', f'0x{input_session:016x}',
                             '--input-display-id-file', str(ipc / 'vdisplay2_id'),
                            '--resize-request', str(ipc / 'vdisplay_resize_2'),
                             '--title', f'AaaS: {args.app2}', '--app-id',
                             'org.aaas.' + args.app2.replace('.', '-'),
                             '--exit-on-close'],
                            stdout=virtual2_log, stderr=subprocess.STDOUT,
                            start_new_session=True,
                        )
                    deadline = time.monotonic() + 10
                    while not (ipc / 'wayland-vdisplay.sock-2').exists():
                        if virtual_presenter2.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError('second virtual display presenter did not start')
                        time.sleep(.1)
            transition('STARTING_ANDROID')
            android = subprocess.Popen([sys.executable, str(runner)], env=env,
                                       stdout=android_log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            transition('WAITING_FOR_FRAMEWORK')
            deadline = time.monotonic() + args.startup_timeout + 20
            while not stop:
                if presenter is not None and presenter.poll() is not None:
                    raise RuntimeError(f'presenter exited before {args.app} became ready')
                if virtual_presenter is not None and virtual_presenter.poll() is not None:
                    raise RuntimeError('virtual display presenter exited before Android startup')
                if virtual_presenter2 is not None and virtual_presenter2.poll() is not None:
                    raise RuntimeError('second virtual display presenter exited before Android startup')
                if android.poll() is not None:
                    raise RuntimeError(f'Android exited before {args.app} became ready')
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
                if status.read_text().strip() == 'FAILED':
                    reason = classify_session_failure(session_commands)
                    raise RuntimeError(f'Android runtime failed: {reason}')
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
                    app1_state = (ipc / 'app1_state').read_text().strip()
                    app2_state = (ipc / 'app2_state').read_text().strip() if args.app2 else ''
                    for index, process, app_state in (
                            (1, virtual_presenter, app1_state),
                            (2, virtual_presenter2, app2_state)):
                        if process is None or (index == 2 and not args.app2):
                            continue
                        exited = process.poll() is not None
                        if not exited and app_state != 'CLOSED':
                            continue
                        if window_close_requested[index] is None:
                            write_session_control(ipc / f'vdisplay_close_{index}', 'close')
                            window_close_requested[index] = time.monotonic()
                            print(f'AaaS: closing Android output {index} independently',
                                  flush=True)
                        if not exited:
                            terminate_process_group(process)
                            if index == 1:
                                virtual_presenter = None
                            else:
                                virtual_presenter2 = None
                        ack = (ipc / f'vdisplay_control_ack_{index}').read_text().strip()
                        if ack.startswith('failed'):
                            raise RuntimeError(f'Android display {index} release failed: {ack}')
                        if ack.startswith('released'):
                            if index == 1 and virtual_presenter is process:
                                virtual_presenter = None
                            elif index == 2 and virtual_presenter2 is process:
                                virtual_presenter2 = None
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
            control_path.unlink(missing_ok=True)
        try:
            failed_before_cleanup = (state == 'FAILED' or
                                     status.read_text().strip() == 'FAILED')
        except OSError:
            failed_before_cleanup = True

        if android is not None and android.poll() is None:
            # Exporting the bounded Android tombstone ring can take several
            # seconds when the runtime has unrelated crashing vendor services.
            # Keep the wait finite while allowing the watcher to finish copies.
            capture_status = request_tombstone_capture(ipc, timeout=10.0)
        else:
            capture_status = 'runtime_unavailable'
        if android is not None and android.poll() is None:
            write_status_sentinel(status, 'STOPPING')

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
        for process in (android, virtual_presenter2, virtual_presenter, presenter):
            try:
                terminate_process_group(process)
            except Exception as error:
                cleanup_failed = True
                print(f'AaaS: process cleanup failed: {error}',
                      file=sys.stderr, flush=True)
        write_crash_artifact_manifest(session, tombstone_dir, capture_status,
                                      graphics_provenance)
        if policy is not None:
            summary = policy_monitor.summary() if policy_monitor is not None else {}
            try:
                cleanup = policy.shutdown()
            except Exception as error:
                cleanup = {'removed': False,
                           'failures': {'shutdown': f'{type(error).__name__}: {error}'}}
            summary['cleanup'] = cleanup
            (session / 'policy-summary.json').write_text(
                json.dumps(summary, indent=1, default=str) + '\n')
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
        terminal_failed = (failed_before_cleanup or state == 'FAILED' or cleanup_failed)
        if terminal_failed:
            if state != 'FAILED':
                transition('FAILED')
        elif state != 'STOPPED':
            transition('STOPPED')
        final_status = finalize_status_sentinel(status, failed=terminal_failed)
        print(f'AaaS: session status {final_status}', flush=True)
        print(f'AaaS logs: {session}', flush=True)
        os.close(lock_fd)


if __name__ == '__main__':
    sys.exit(main())
