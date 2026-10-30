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
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aaas_cgroup


ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = Path('/run/media/mrkus/Homework/aaas-workspace')
TMP = WORKSPACE / 'tmp'
RUNNER = ROOT / 'scripts/aaas_session_runner_base.py'
PRESENTER = ROOT / 'experiments/m1a/build/wayland-host-presenter'
INPUT_ADAPTER = ROOT / 'experiments/m1c/input_adapter/build/aaas-input-adapter'
COMPOSER_PORTRAIT = TMP / 'm1b84_composer_portrait_720x1280'
COMPOSER_LANDSCAPE = TMP / 'android.hardware.graphics.composer3-service.aaas'
COMPOSER_VDISPLAY = TMP / 'm1e_composer_vdisplay_experimental'
VDISPLAY_BROKER_DEX = TMP / 'm1e_aaas_display_broker.dex'
VDISPLAY_BROKER_RC = ROOT / 'experiments/m1e/display_broker/aaas-display-broker.rc'
VDISPLAY_SERVICES_OVERLAY = TMP / 'm1e_services_display_content_mode.jar'
VDISPLAY_SERVICES_RECEIPT = TMP / 'm1e_services_display_content_mode.json'
APKTOOL = TMP / 'apktool_3.0.3.jar'
VDC_OVERLAY = TMP / 'm1d_vdc_overlay/vdc'
RUNNER_SHA256 = '63987b632cfc28f15eaa406f8b6fedc2f80f0c7c63fa2d8a751558d02267e396'
VULKAN_SHA256 = '1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181'
LMKD_DIAGNOSTIC_SHA256 = '9780759ba36e50d061064f05c77520809f3291edad6a43a1495e9d91f21d54bd'
LMKD_SOURCE_BUILT_SHA256 = 'a36135b6948342163186fe57acb9de0245fe00aeafcb9556c48a2e4c52f291ce'
COMPOSER_PORTRAIT_SHA256 = 'cd55e7418a469e84c839bfec287b1bce238a43daa28f50900acf3174c17e3a46'
VDC_OVERLAY_SHA256 = 'b91c93e100f3892880665f9b47630d1170dc1fce4ee3cf249ec8f20e583fd764'
FRAMEWORK_IME_SHA256 = '701d2fd4afe62e4b02a3f2da603daab492a4369dea3bd4d3baefe52789623a0b'
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


def make_session_runner(session, desktop_ime=True, app_package=DEFAULT_APP_PACKAGE,
                        experimental_virtual_display=False):
    if sha256(RUNNER) != RUNNER_SHA256:
        raise RuntimeError('inherited runtime runner changed; review the session transformation')
    app_package = validate_app_package(app_package)
    timeout = '140'
    source = RUNNER.read_text()
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
    source = replace_once(source, '    ipc_dir.chmod(0o777)', '    ipc_dir.chmod(0o711)')
    input_adapter_log_placeholder = '{input_adapter_log_bind}'
    if experimental_virtual_display:
        input_adapter_log_placeholder += '{vdisplay_input_adapter_log_bind}'
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
    readiness_and_watch = (
        f'    APP_PACKAGE={app_package}\n'
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
    if experimental_virtual_display:
        readiness_and_watch += (
            ' && [ "$(/system/bin/toybox cat /aaas_session_status)" != "STOPPING" ]; do\n'
            '      /system/bin/toybox sleep 2\n'
            '    done\n'
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
        )
    except (OSError, ValueError, KeyError):
        return False


def verify_requirements(use_source_lmkd=False, orientation='portrait'):
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
        'AAAS_FRAMEWORK_JAR_OVERLAY': ('m1d_framework_desktop_ime.jar', FRAMEWORK_IME_SHA256),
        'AAAS_VULKAN_OVERLAY': ('m1b83_sampling_lock_vulkan.so', VULKAN_SHA256),
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
        path = TMP / name
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--startup-timeout', type=int, default=90)
    parser.add_argument('--use-source-lmkd', action='store_true',
                        help='Use the source-built Android 16 LMKD binary instead of diagnostic overlay')
    parser.add_argument('--memory-policy', choices=('none', 'cgroup'), default='none',
                        help='Apply a rootless delegated cgroup v2 memory policy')
    parser.add_argument('--orientation', choices=('portrait', 'landscape'),
                        default='portrait',
                        help='Android display profile (default: portrait)')
    parser.add_argument('--app', default=DEFAULT_APP_PACKAGE,
                        help='installed package with a MAIN/LAUNCHER activity '
                             '(default: com.android.settings)')
    parser.add_argument('--software-keyboard', action='store_true',
                        help='Allow Android to show its software keyboard (mobile/accessibility mode)')
    parser.add_argument('--experimental-virtual-display', action='store_true',
                        help='Use the isolated M1E trusted virtual-display prototype')
    args = parser.parse_args()
    if args.startup_timeout < 1:
        parser.error('startup timeout must be positive')
    try:
        validate_app_package(args.app)
    except ValueError as error:
        parser.error(str(error))
    paths = verify_requirements(use_source_lmkd=args.use_source_lmkd,
                                orientation=args.orientation)
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
        paths['AAAS_COMPOSER_OVERLAY'] = str(COMPOSER_VDISPLAY)
        paths['AAAS_SERVICES_JAR_OVERLAY'] = str(VDISPLAY_SERVICES_OVERLAY)
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
    if args.experimental_virtual_display:
        vdisplay_input_adapter_log.touch()
        vdisplay_input_adapter_log.chmod(0o666)
    input_session = int.from_bytes(os.urandom(8), 'little') or 1
    (ipc / 'input_session').write_text(f'0x{input_session:016x}\n')
    (ipc / 'input_session').chmod(0o600)
    if args.experimental_virtual_display:
        (ipc / 'vdisplay_id').write_text('')
        (ipc / 'vdisplay_id').chmod(0o666)
        (ipc / 'display_broker_shutdown').write_text('')
        (ipc / 'display_broker_shutdown').chmod(0o666)
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
    runner = make_session_runner(session, desktop_ime=not args.software_keyboard,
                                 app_package=args.app,
                                 experimental_virtual_display=args.experimental_virtual_display)
    prefix = f'm1b84_session_{os.getpid()}_'
    env = os.environ.copy()
    env.update(paths)
    presenter_size = (('720', '1280') if args.orientation == 'portrait'
                      else ('1280', '720'))
    boot_wait = (min(args.startup_timeout, 180)
                 if args.experimental_virtual_display else args.startup_timeout)
    env.update(AAAS_LOG_PREFIX=prefix, AAAS_BOOTANIM='0',
               AAAS_BOOT_WAIT=str(boot_wait),
               AAAS_SESSION_IPC=str(ipc), AAAS_SESSION_STATUS=str(status),
               AAAS_SESSION_LOGCAT=str(logcat),
               AAAS_INPUT_ADAPTER=str(INPUT_ADAPTER) if INPUT_ADAPTER.is_file() else '',
               AAAS_INPUT_ADAPTER_LOG=str(input_adapter_log))
    if args.experimental_virtual_display:
        env.update(AAAS_VDISPLAY_DEX=str(VDISPLAY_BROKER_DEX),
                   AAAS_VDISPLAY_RC=str(VDISPLAY_BROKER_RC),
                   AAAS_SESSION_COMMANDS=str(session_commands),
                   AAAS_VDISPLAY_INPUT_ADAPTER_LOG=str(vdisplay_input_adapter_log))
    presenter = virtual_presenter = android = None
    state = 'CREATED'
    input_ready_reported = False
    running_session = False

    def transition(new_state):
        nonlocal state
        state = new_state
        print(f'AaaS: {new_state} ({session})', flush=True)
        with (session / 'state.jsonl').open('a') as stream:
            stream.write(json.dumps({'state': state, 'monotonic_ns': time.monotonic_ns()}) + '\n')

    try:
        transition('PREPARING')
        with (session / 'presenter.log').open('wb') as presenter_log, (session / 'android.log').open('wb') as android_log:
            transition('STARTING_PRESENTER')
            presenter = subprocess.Popen(
                [str(PRESENTER), '--socket', str(ipc / 'wayland.sock'),
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
            if args.experimental_virtual_display:
                virtual_log_path = session / 'virtual-presenter.log'
                with virtual_log_path.open('wb') as virtual_log:
                    virtual_presenter = subprocess.Popen(
                        [str(PRESENTER), '--socket', str(ipc / 'wayland-vdisplay.sock'),
                         '--width', presenter_size[0], '--height', presenter_size[1],
                         '--input-socket', str(ipc / 'input-vdisplay.sock'),
                         '--input-session', f'0x{input_session:016x}',
                         '--input-display-id-file', str(ipc / 'vdisplay_id'),
                         '--title', f'AaaS virtual output: {args.app}', '--exit-on-close'],
                        stdout=virtual_log, stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                deadline = time.monotonic() + 10
                while not (ipc / 'wayland-vdisplay.sock').exists():
                    if virtual_presenter.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('virtual display presenter did not start')
                    time.sleep(.1)
            transition('STARTING_ANDROID')
            android = subprocess.Popen([sys.executable, str(runner)], env=env,
                                       stdout=android_log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            transition('WAITING_FOR_FRAMEWORK')
            deadline = time.monotonic() + args.startup_timeout + 20
            while not stop:
                if presenter.poll() is not None:
                    raise RuntimeError(f'presenter exited before {args.app} became ready')
                if virtual_presenter is not None and virtual_presenter.poll() is not None:
                    raise RuntimeError('virtual display presenter exited before Android startup')
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
                    print(f'{args.app} process started. Close its window or press Ctrl+C to stop.', flush=True)
                    break
                if status.read_text().strip() == 'FAILED' or time.monotonic() >= deadline:
                    raise RuntimeError(f'Android app {args.app} did not become ready')
                time.sleep(.25)
            warned_degraded = False
            while not stop and state == 'RUNNING':
                if presenter.poll() is not None:
                    print('AaaS: presenter exited; stopping Android', flush=True)
                    break
                if virtual_presenter is not None and virtual_presenter.poll() is not None:
                    raise RuntimeError('virtual display presenter exited')
                if android.poll() is not None or status.read_text().strip() == 'FAILED':
                    raise RuntimeError('Android runtime failed')
                if (policy_monitor is not None and policy_monitor.degraded
                        and not warned_degraded):
                    warned_degraded = True
                    print('AaaS: memory policy monitor degraded; Android continues',
                          file=sys.stderr, flush=True)
                time.sleep(.25)
        transition('STOPPING')
        return 0
    except Exception as error:
        print(f'AaaS: {error}', file=sys.stderr, flush=True)
        transition('FAILED')
        return 1
    finally:
        cleanup_failed = False
        if policy_monitor is not None:
            try:
                policy_monitor.stop(timeout=12)
            except Exception as error:
                cleanup_failed = True
                print(f'AaaS: memory policy monitor cleanup failed: {error}',
                      file=sys.stderr, flush=True)
        try:
            failed_before_cleanup = (state == 'FAILED' or
                                     status.read_text().strip() == 'FAILED')
        except OSError:
            failed_before_cleanup = True

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
        for process in (android, virtual_presenter, presenter):
            try:
                terminate_process_group(process)
            except Exception as error:
                cleanup_failed = True
                print(f'AaaS: process cleanup failed: {error}',
                      file=sys.stderr, flush=True)
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
        if state != 'FAILED':
            transition('STOPPED')
        final_status = finalize_status_sentinel(
            status, failed=failed_before_cleanup or state == 'FAILED' or cleanup_failed)
        print(f'AaaS: session status {final_status}', flush=True)
        print(f'AaaS logs: {session}', flush=True)
        os.close(lock_fd)


if __name__ == '__main__':
    sys.exit(main())
