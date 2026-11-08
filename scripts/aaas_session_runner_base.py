#!/usr/bin/env python3
"""Test Android 16 Zygote (app_process64) startup while property service is active."""

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
import aaas_idmap


def main():
    xdg_data = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    workspace = Path(os.environ.get('AAAS_WORKSPACE', xdg_data / 'aaas/workspace'))
    rootfs = Path(os.environ.get('AAAS_ROOTFS', workspace / 'rootfs_m1b1'))
    tmp_dir = workspace / 'tmp'
    prefix = os.environ.get("AAAS_LOG_PREFIX", "")
    kmsg_log = tmp_dir / f"{prefix}kmsg_zygote_test.log"
    kmsg_log.write_text("")
    os.chmod(kmsg_log, 0o666)
    full_logcat_log = tmp_dir / f"{prefix}full_logcat.log"
    full_logcat_log.write_text("")
    os.chmod(full_logcat_log, 0o666)
    keystore_trace_enabled = os.environ.get("AAAS_KEYSTORE_TRACE", "0") == "1"
    keystore_trace_log = tmp_dir / f"{prefix}keystore_ioctl_strace.log"
    live_logcat_log = tmp_dir / f"{prefix}continuous_logcat.log"
    if keystore_trace_enabled:
        for log in (keystore_trace_log, live_logcat_log):
            log.write_text("")
            os.chmod(log, 0o666)
    sf_strace_log = tmp_dir / f"{prefix}sf_strace.log"
    sf_strace_log.write_text("")
    os.chmod(sf_strace_log, 0o666)
    composer_log = tmp_dir / f"{prefix}composer.log"
    composer_log.write_text("")
    os.chmod(composer_log, 0o666)
    allocator_log = tmp_dir / f"{prefix}allocator.log"
    allocator_log.write_text("")
    os.chmod(allocator_log, 0o666)
    egl_test_log = tmp_dir / f"{prefix}egl_test.log"
    egl_test_log.write_text("")
    os.chmod(egl_test_log, 0o666)

    tombstone_dir = Path(os.environ.get(
        "AAAS_TOMBSTONE_EXPORT", str(tmp_dir / f"{prefix}tombstones")))
    tombstone_dir.mkdir(exist_ok=True)
    # Tombstones can contain process memory and paths. They are exported to
    # the owning host session only; never make the artifact directory public.
    os.chmod(tombstone_dir, 0o700)

    fake_kptr = tmp_dir / "fake_kptr"
    fake_sysrq = tmp_dir / "fake_sysrq"
    fake_modprobe = tmp_dir / "fake_modprobe"
    fake_mmap = tmp_dir / "fake_mmap_rnd_bits"
    fake_mmap_compat = tmp_dir / "fake_mmap_rnd_compat_bits"
    fake_cmdline = tmp_dir / "fake_cmdline"
    fake_kptr.write_text("0\n")
    fake_sysrq.write_text("0\n")
    fake_modprobe.write_text("\n")
    fake_mmap.write_text("32\n")
    fake_mmap_compat.write_text("16\n")
    fake_cmdline.write_text("console=tty0 androidboot.hardware=ranchu androidboot.fstab_suffix=ranchu androidboot.serialno=aaas001 androidboot.hardwareegl=angle androidboot.hardware.vulkan=pastel androidboot.hardware.egl=angle androidboot.vendor.hwcomposer.display_finder_mode=noop androidboot.vendor.hwcomposer.mode=client androidboot.hardware.hwcomposer.mode=client androidboot.hardware.hwcomposer.display_finder_mode=noop\n")

    cgroup_dir = Path("/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/aaas")
    cgroup_dir.mkdir(parents=True, exist_ok=True)

    fifo_path = tmp_dir / f"zygote_fifo_{os.getpid()}"
    if fifo_path.exists():
        fifo_path.unlink()
    os.mkfifo(fifo_path)

    overlay_mapper = tmp_dir / "mapper.drm.so"
    mapper_bind = f'  --bind "{overlay_mapper}" /vendor/lib64/hw/mapper.ranchu.so \\\n' if (overlay_mapper.exists() and os.environ.get("AAAS_USE_DRM_MAPPER", "1") == "1") else ""

    overlay_composer = Path(os.environ.get("AAAS_COMPOSER_OVERLAY", str(tmp_dir / "android.hardware.graphics.composer3-service.aaas")))
    composer_bind = f'  --bind "{overlay_composer}" /vendor/bin/hw/android.hardware.graphics.composer3-service.ranchu \\\n' if (overlay_composer.exists() and os.environ.get("AAAS_USE_AAAS_COMPOSER", "1") == "1") else ""

    overlay_allocator = tmp_dir / "android.hardware.graphics.allocator-service.aaas"
    allocator_bind = f'  --bind "{overlay_allocator}" /vendor/bin/hw/android.hardware.graphics.allocator-service.ranchu \\\n' if (overlay_allocator.exists() and os.environ.get("AAAS_USE_AAAS_ALLOCATOR", "1") == "1") else ""

    ipc_dir = tmp_dir / "aaas_ipc"
    ipc_dir.mkdir(parents=True, exist_ok=True)
    ipc_dir.chmod(0o777)
    ipc_bind = f'  --dir /dev/aaas \\\n  --bind "{ipc_dir}" /dev/aaas \\\n'

    overlay_vulkan = Path(os.environ.get("AAAS_VULKAN_OVERLAY", str(tmp_dir / "vulkan.pastel.so")))
    vulkan_bind = f'  --bind "{overlay_vulkan}" /vendor/lib64/hw/vulkan.pastel.so \\\n' if overlay_vulkan.exists() else ""

    overlay_libvulkan = tmp_dir / "libvulkan.so"
    libvulkan_bind = f'  --bind "{overlay_libvulkan}" /system/lib64/libvulkan.so \\\n' if overlay_libvulkan.exists() else ""

    overlay_angle = tmp_dir / "libGLESv2_angle.so"
    angle_bind = f'  --bind "{overlay_angle}" /system/lib64/libGLESv2_angle.so \\\n' if overlay_angle.exists() else ""

    probe_bin = tmp_dir / "surfaceflinger_probe"
    probe_bind = f'  --bind "{probe_bin}" /system/bin/surfaceflinger_probe \\\n' if probe_bin.exists() else ""

    overlay_egl_test = tmp_dir / "test_egl_image_import"
    egl_test_bind = f'  --bind "{overlay_egl_test}" /system/bin/test_egl_image_import \\\n' if overlay_egl_test.exists() else ""

    import xml.etree.ElementTree as ET
    active_apex_info = tmp_dir / "active-apex-info-list.xml"
    tree = ET.parse(rootfs / "apex/apex-info-list.xml")
    for entry in tree.getroot().findall("apex-info"):
        mod = entry.get("moduleName")
        if (rootfs / "apex" / mod).is_dir():
            entry.set("isActive", "true")
            entry.set("modulePath", f"/apex/{mod}")
        else:
            entry.set("isActive", "false")
    tree.write(active_apex_info, encoding="utf-8", xml_declaration=True)
    apex_info_bind = f'  --ro-bind "{active_apex_info}" /apex/apex-info-list.xml \\\n'
    ranging_jar_overlay = os.environ.get("AAAS_RANGING_JAR_OVERLAY")
    ranging_jar_bind = (
        f'  --ro-bind "{ranging_jar_overlay}" /apex/com.android.uwb/javalib/service-ranging.jar \\\n'
        if ranging_jar_overlay and Path(ranging_jar_overlay).is_file() else ""
    )
    networkstats_lib_overlay = os.environ.get("AAAS_NETWORKSTATS_LIB_OVERLAY")
    networkstats_lib_bind = (
        f'  --ro-bind "{networkstats_lib_overlay}" /apex/com.android.tethering/lib64/libnetworkstats.so \\\n'
        if networkstats_lib_overlay and Path(networkstats_lib_overlay).is_file() else ""
    )
    meminfo_lib_overlay = os.environ.get("AAAS_MEMINFO_LIB_OVERLAY")
    meminfo_lib_bind = (
        f'  --ro-bind "{meminfo_lib_overlay}" /system/lib64/libmeminfo.so \\\n'
        if meminfo_lib_overlay and Path(meminfo_lib_overlay).is_file() else ""
    )
    wifi_feature_overlay = os.environ.get("AAAS_WIFI_FEATURE_OVERLAY")
    wifi_feature_bind = "".join(
        f'  --ro-bind "{wifi_feature_overlay}" /vendor/etc/permissions/{name} \\\n'
        for name in (
            "android.hardware.wifi.xml",
            "android.hardware.wifi.passpoint.xml",
            "android.hardware.wifi.direct.xml",
        )
    ) if wifi_feature_overlay and Path(wifi_feature_overlay).is_file() else ""
    services_jar_overlay = os.environ.get("AAAS_SERVICES_JAR_OVERLAY")
    services_jar_bind = (
        f'  --ro-bind "{services_jar_overlay}" /system/framework/services.jar \\\n'
        if services_jar_overlay and Path(services_jar_overlay).is_file() else ""
    )
    keystore_sid_probe = os.environ.get("AAAS_KEYSTORE_SID_PROBE")
    keystore_sid_bind = ""
    keystore_sid_data_bind = ""
    if keystore_sid_probe and Path(keystore_sid_probe).is_file():
        keystore_rc = tmp_dir / f"{prefix}keystore2_sid_probe.rc"
        keystore_rc.write_text(
            (rootfs / "system/etc/init/keystore2.rc").read_text()
            + "    setenv LD_PRELOAD /data/local/tmp/libkeystore_sid_probe.so:/system/lib64/libselinux_shim.so\n"
        )
        keystore_sid_bind = (
            f'  --ro-bind "{keystore_rc}" /system/etc/init/keystore2.rc \\\n'
        )
        keystore_sid_data_bind = (
            "  --dir /data/local/tmp \\\n"
            + f'  --ro-bind "{keystore_sid_probe}" /data/local/tmp/libkeystore_sid_probe.so \\\n'
        )
    hwsm_sid_probe = os.environ.get("AAAS_HWSM_SID_PROBE")
    hwsm_sid_bind = ""
    hwsm_sid_data_bind = ""
    if hwsm_sid_probe and Path(hwsm_sid_probe).is_file():
        hwsm_rc = tmp_dir / f"{prefix}hwservicemanager_sid_probe.rc"
        hwsm_rc.write_text(
            (rootfs / "system_ext/etc/init/hwservicemanager.rc").read_text()
            .replace(
                "    user system\n",
                "    user system\n"
                "    setenv LD_PRELOAD /data/local/tmp/libhwsm_sid_probe.so:/system/lib64/libselinux_shim.so\n",
                1,
            )
        )
        hwsm_sid_bind = f'  --ro-bind "{hwsm_rc}" /system_ext/etc/init/hwservicemanager.rc \\\n'
        hwsm_sid_data_bind = (
            "  --dir /data/local/tmp \\\n"
            + f'  --ro-bind "{hwsm_sid_probe}" /data/local/tmp/libhwsm_sid_probe.so \\\n'
        )

    sf_probe_env = os.environ.get("AAAS_SF_PROBE", "0")
    sf_strace_env = os.environ.get("AAAS_SF_STRACE", "0")
    sf_gdbserver_env = os.environ.get("AAAS_SF_GDBSERVER", "0")
    bootanim_gdbserver_env = os.environ.get("AAAS_BOOTANIM_GDBSERVER", "0")
    host_debug_bind = "  --bind /usr /usr \\\n  --symlink /usr/lib64 /lib64 \\\n" if sf_gdbserver_env == "1" or bootanim_gdbserver_env == "1" or keystore_trace_enabled else ""
    keystore_trace_bind = (
        f'  --bind "{keystore_trace_log}" /keystore_ioctl_strace.log \\\n'
        f'  --bind "{live_logcat_log}" /continuous_logcat.log \\\n'
        if keystore_trace_enabled else ""
    )
    keystore_trace_start = (
        '    /system/bin/logcat -b all -v threadtime > /continuous_logcat.log 2>&1 &\n'
        '    KS_PID=$(/system/bin/toybox pidof keystore2)\n'
        '    if [ -n "$KS_PID" ]; then\n'
        '      LD_PRELOAD= /usr/bin/strace -f -ttt -e trace=ioctl -e raw=ioctl -s 0 -o /keystore_ioctl_strace.log -p "$KS_PID" &\n'
        '    fi\n'
        if keystore_trace_enabled else ""
    )
    bootanim_debug_bind = ""
    if bootanim_gdbserver_env == "1":
        debug_dir = tmp_dir / f"{prefix}debug"
        debug_dir.mkdir(exist_ok=True)
        debug_dir.chmod(0o777)
        (debug_dir / "bootanim.rc").write_text(
            "service bootanim /debug/bootanim_wrapper.sh\n"
            + (rootfs / "system/etc/init/bootanim.rc").read_text().split("\n", 1)[1]
        )
        wrapper = debug_dir / "bootanim_wrapper.sh"
        wrapper.write_text(
            "#!/system/bin/sh\n"
            "umask 000\n"
            "LD_PRELOAD= /usr/bin/gdbserver --once :12346 "
            "/system/bin/bootanimation > /debug/gdbserver.log 2>&1\n"
        )
        wrapper.chmod(0o755)
        bootanim_debug_bind = (
            f'  --bind "{debug_dir}" /debug \\\n'
            f'  --bind "{debug_dir / "bootanim.rc"}" /system/etc/init/bootanim.rc \\\n'
        )
    egl_test_env = os.environ.get("AAAS_EGL_TEST", "0")
    bootanim_env = os.environ.get("AAAS_BOOTANIM", "1")
    settings_sigquit = os.environ.get("AAAS_SETTINGS_SIGQUIT", "0")
    sf_sigquit = os.environ.get("AAAS_SF_SIGQUIT", "0")
    boot_wait = os.environ.get("AAAS_BOOT_WAIT", "60.0")
    boot_wait_int = int(float(boot_wait))
    tun_bind = "  --dir /dev/net \\\n  --dev-bind /dev/net/tun /dev/net/tun \\\n  --dev-bind /dev/net/tun /dev/tun \\\n" if Path("/dev/net/tun").exists() else ""

    runner_script = tmp_dir / f"run_zygote_probe_{os.getpid()}.sh"
    script_text = f"""#!/bin/sh
read line < "{fifo_path}"
mkdir -p /tmp/binder_mnt
mount -t binder binder /tmp/binder_mnt
python3 -c '
import fcntl, ctypes, os
class BinderctlNum(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char * 256), ("major", ctypes.c_uint32), ("minor", ctypes.c_uint32)]
ctl = os.open("/tmp/binder_mnt/binder-control", os.O_RDWR)
IOC_ADD = 0xc1086201
for name in [b"binder", b"hwbinder", b"vndbinder"]:
    req = BinderctlNum()
    req.name = name
    try: fcntl.ioctl(ctl, IOC_ADD, req)
    except Exception: pass
os.close(ctl)
for name in ["binder", "hwbinder", "vndbinder", "binder-control"]:
    p = f"/tmp/binder_mnt/{{name}}"
    if os.path.exists(p):
        os.chmod(p, 0o666)
'
exec bwrap \\
  --as-pid-1 \\
  --unshare-pid \\
  --bind "{rootfs}" / \\
{mapper_bind}{allocator_bind}{composer_bind}{vulkan_bind}{libvulkan_bind}{angle_bind}{probe_bind}{egl_test_bind}{host_debug_bind}{bootanim_debug_bind}{apex_info_bind}{ranging_jar_bind}{networkstats_lib_bind}{meminfo_lib_bind}{wifi_feature_bind}{services_jar_bind}{keystore_sid_bind}{hwsm_sid_bind}{keystore_trace_bind}  --proc /proc \\
  --bind "{fake_cmdline}" /proc/cmdline \\
  --dev /dev \\
{tun_bind}  --dev-bind /dev/dri /dev/dri \\
  --dev-bind /tmp/binder_mnt /dev/binderfs \\
  --symlink /dev/binderfs/binder /dev/binder \\
  --symlink /dev/binderfs/hwbinder /dev/hwbinder \\
  --symlink /dev/binderfs/vndbinder /dev/vndbinder \\
{ipc_bind}  --bind "{kmsg_log}" /dev/kmsg \\
  --bind "{full_logcat_log}" /data_logcat.log \\
  --bind "{sf_strace_log}" /data_sf_strace.log \\
  --bind "{composer_log}" /data_composer.log \\
  --bind "{allocator_log}" /data_allocator.log \\
  --bind "{egl_test_log}" /egl_test_result.log \\
  --bind "{cgroup_dir}" /sys/fs/cgroup \
  --ro-bind /sys/class/net /sys/class/net \\
  --bind "{fake_kptr}" /proc/sys/kernel/kptr_restrict \\
  --bind "{fake_sysrq}" /proc/sys/kernel/sysrq \\
  --bind "{fake_modprobe}" /proc/sys/kernel/modprobe \\
  --bind "{fake_mmap}" /proc/sys/vm/mmap_rnd_bits \\
  --bind "{fake_mmap_compat}" /proc/sys/vm/mmap_rnd_compat_bits \\
  --tmpfs /tmp \\
  --tmpfs /dev/socket \\
  --tmpfs /dev/__properties__ \\
  --tmpfs /data \\
{keystore_sid_data_bind}{hwsm_sid_data_bind}  --dir /tombstone_export \\
  --bind "{tombstone_dir}" /tombstone_export \\
  --setenv PATH /system/bin:/apex/com.android.art/bin \\
  --setenv ANDROID_ROOT /system \\
  --setenv ANDROID_DATA /data \\
  --setenv ANDROID_ART_ROOT /apex/com.android.art \\
  --setenv ANDROID_I18N_ROOT /apex/com.android.i18n \\
  --setenv ANDROID_TZDATA_ROOT /apex/com.android.tzdata \\
  --setenv LD_PRELOAD /system/lib64/libselinux_shim.so \\
  sh -c '
    sleep() {{ /system/bin/toybox sleep "$@"; }}
    /system/bin/init second_stage &
    INIT_PID=$!
    sleep 1.0
{keystore_trace_start}
    /system/bin/toybox ifconfig lo 127.0.0.1 up 2>/dev/null || true

    echo "=== STEP 0: PREPARING USER 0 AND APP DATA STORAGE ==="
    mkdir -p /data/user/0 \
             /data/user_de/0 \
             /data/misc_ce/0 \
             /data/misc_de/0 \
             /data/system_ce/0 \
             /data/system_de/0 \
             /data/system_de/0/powerstats \
             /data/misc/keystore \
             /data/misc/gatekeeper \
             /data/misc/profiles/cur/0 \
             /data/misc/profiles/ref \
             /data/system/users/0 \
             /data/system/dropbox \
             /data/user_de/0/com.android.providers.settings/databases \
             /data_mirror/data_ce/null/0 \
             /data_mirror/data_de/null/0 \
             /data_mirror/misc_ce/null/0 \
             /data_mirror/misc_de/null/0
    mkdir -p /data/data
    chown 1000:1000 /data/data /data/user/0 /data/user_de/0
    chown 1000:1000 /data/system_de/0 /data/system_de/0/powerstats
    chown 1000:1000 /data/system /data/system/users /data/system/users/0
    chmod 0775 /data/system /data/system/users
    chmod 0770 /data/system/users/0
    chmod 0771 /data /data/data /data/user/0 /data/user_de/0
    chmod 0700 /data/system_de/0 /data/system_de/0/powerstats
    chmod 0511 /data/user /data/user_de
    chown 1017:1017 /data/misc/keystore
    chmod 0700 /data/misc/keystore
    chown 1000:1000 /data/misc/gatekeeper
    chmod 0700 /data/misc/gatekeeper

    echo "=== STEP 1: SETTING APEX & KEYSTORE PROPS ==="
    /system/bin/setprop sys.use_memfd true
    /system/bin/setprop ro.hw_timeout_multiplier 4
    /system/bin/setprop ro.control_privapp_permissions disable
    /system/bin/setprop apexd.status activated
    /system/bin/setprop keystore.module_hash.sent true
    /system/bin/setprop log.tag.SurfaceFlinger VERBOSE
    /system/bin/setprop log.tag.HWComposer VERBOSE
    /system/bin/setprop log.tag.RanchuHwc VERBOSE
    /system/bin/setprop log.tag.Composer VERBOSE
    /system/bin/setprop log.tag.RenderEngine VERBOSE
    /system/bin/setprop log.tag.DisplayManagerService VERBOSE
    /system/bin/setprop log.tag.LocalDisplayAdapter VERBOSE
    /system/bin/setprop log.tag.DisplayManager VERBOSE
    /system/bin/setprop log.tag.WindowManager VERBOSE
    /system/bin/setprop log.tag.ActivityTaskManager VERBOSE
    /system/bin/setprop log.tag.PackageManager VERBOSE
    /system/bin/setprop service.sf.prime_shader_cache 0
    if [ "{bootanim_env}" = "1" ]; then
      /system/bin/setprop debug.sf.nobootanimation 0
      /system/bin/setprop service.bootanim.exit 0
    else
      /system/bin/setprop debug.sf.nobootanimation 1
      /system/bin/setprop service.bootanim.exit 1
    fi
    /system/bin/start apexd
    /system/bin/start installd
    /system/bin/start vendor.light-default
    /system/bin/start vendor.graphics.allocator
    /system/bin/start vendor.hwcomposer-3
    /system/bin/start vendor.power-default
    /system/bin/start vendor.power.stats-default
    /system/bin/start vendor.thermal-example
    /system/bin/start vendor.vibrator-default
    /system/bin/start vold
    /system/bin/start netd
    /system/bin/start vendor.gatekeeper_nonsecure
    /system/bin/start gatekeeperd
    /system/bin/start vendor.audio-hal
    /system/bin/start audioserver
    /system/bin/start cameraserver
    /system/bin/start mediametrics
    /system/bin/start mediaextractor
    /system/bin/start media
    if [ "{egl_test_env}" = "1" ]; then
      echo "=== RUNNING INDEPENDENT GRAPHICS IMPORT TEST ==="
      /system/bin/test_egl_image_import 2>&1 | tee /egl_test_result.log
      echo "=== INDEPENDENT GRAPHICS IMPORT TEST COMPLETE (exit=$?) ==="
    fi

    if [ "{sf_probe_env}" = "1" ]; then
      echo "=== STARTING DIAGNOSTIC SURFACEFLINGER PROBE ==="
      /system/bin/surfaceflinger_probe &
    elif [ "{sf_gdbserver_env}" = "1" ]; then
      LD_PRELOAD= /usr/bin/gdbserver --once :12345 /system/bin/surfaceflinger &
    elif [ "{sf_strace_env}" = "1" ]; then
      /system/bin/strace -f -tt -T -s 128 -o /data_sf_strace.log /system/bin/surfaceflinger &
    else
      /system/bin/surfaceflinger &
    fi
    sleep 2.0

    echo "=== STEP 2: SETTING ODSIGN DONE & STARTING ZYGOTE ==="
    /system/bin/setprop odsign.key.done 1
    /system/bin/setprop odsign.verification.done 1
    if [ "{bootanim_env}" = "1" ]; then
      /system/bin/start bootanim
    fi

    echo "=== WAITING FOR COMPOSER & FRAMEWORK SERVICES (max {boot_wait_int}s) ==="
    WAITED=0
    while [ $WAITED -lt {boot_wait_int} ]; do
      if [ "$(/system/bin/getprop sys.boot_completed 2>/dev/null)" = "1" ]; then
        echo "Framework fully booted after ${{WAITED}}s!"
        echo "Giving framework 5s to settle..."
        /system/bin/toybox sleep 5
        break
      fi
      if [ $((WAITED % 4)) -eq 0 ]; then
        echo "Waiting for framework (sys.boot_completed)... (${{WAITED}}s / {boot_wait_int}s)"
      fi
      /system/bin/toybox sleep 2
      WAITED=$((WAITED + 2))
    done

    echo "=== CHECKING BINDER SERVICES ==="
    /system/bin/service list

    echo "=== PROBING CORE BOOTSTRAP SERVICES ==="
    /system/bin/service check package
    /system/bin/service check activity
    /system/bin/service check window
    /system/bin/service check power
    /system/bin/service check display
    /system/bin/service check input
    /system/bin/service check apexservice

    echo "=== TESTING PACKAGE MANAGER COMMAND IPC ==="
    /system/bin/cmd package list packages

    echo "=== TESTING ACTIVITY LAUNCH (SETTINGS) ==="
    /system/bin/cmd activity start-activity -W -n com.android.settings/.Settings || /system/bin/am start -W -n com.android.settings/.Settings
    /system/bin/toybox sleep 3
    if [ "{settings_sigquit}" = "1" ]; then
      SETTINGS_PID=$(/system/bin/toybox pidof com.android.settings)
      if [ -n "$SETTINGS_PID" ]; then
        echo "=== REQUESTING SETTINGS JAVA THREAD DUMP (PID $SETTINGS_PID) ==="
        /system/bin/toybox kill -3 "$SETTINGS_PID"
        /system/bin/toybox sleep 2
      fi
    fi
    if [ "{sf_sigquit}" = "1" ]; then
      SF_DUMP_PID=$(/system/bin/toybox pidof surfaceflinger)
      if [ -n "$SF_DUMP_PID" ]; then
        echo "=== REQUESTING SURFACEFLINGER THREAD DUMP (PID $SF_DUMP_PID) ==="
        /system/bin/toybox kill -3 "$SF_DUMP_PID"
        /system/bin/toybox sleep 2
      fi
    fi
    echo "=== DUMPING SF LAYERS & SURFACES ==="
    /system/bin/dumpsys SurfaceFlinger --list
    echo "=== DUMPING WINDOW MANAGER ACTIVITIES ==="
    /system/bin/dumpsys window displays || /system/bin/dumpsys window visible-apps || /system/bin/dumpsys activity activities

    echo "=== CHECKING LINKERCONFIG ==="
    /system/bin/toybox ls -la /linkerconfig/

    echo "=== CHECKING PROCESSES (LOOKING FOR ZYGOTE) ==="
    /system/bin/toybox ps -ef

    echo "=== CHECKING /dev/socket ==="
    /system/bin/toybox ls -la /dev/socket

    echo "=== GETPROP HWCOMPOSER ==="
    /system/bin/getprop ro.vendor.hwcomposer.display_finder_mode
    /system/bin/getprop ro.vendor.hwcomposer.mode
    /system/bin/getprop ro.hardware.vulkan
    /system/bin/getprop ro.hardware.egl

    echo "=== SF DEBUG OUTPUT ==="
    SF_PID=$(/system/bin/toybox pidof surfaceflinger)
    echo "SF_PID: $SF_PID"
    if [ -n "$SF_PID" ]; then
      for tid in /proc/$SF_PID/task/*; do
        echo "--- TID: $tid ---"
        /system/bin/toybox cat "$tid/status" | grep -E "Name:|State:"
        echo -n "wchan: "
        /system/bin/toybox cat "$tid/wchan" 2>/dev/null; echo ""
        echo -n "stack: "
        /system/bin/toybox cat "$tid/stack" 2>/dev/null; echo ""
      done
    fi
    HWC_PID=$(/system/bin/toybox pidof android.hardware.graphics.composer3-service.ranchu)
    echo "HWC_PID: $HWC_PID"
    if [ -n "$HWC_PID" ]; then
      for tid in /proc/$HWC_PID/task/*; do
        echo "--- HWC TID: $tid ---"
        /system/bin/toybox cat "$tid/status" | grep -E "Name:|State:"
        echo -n "wchan: "
        /system/bin/toybox cat "$tid/wchan" 2>/dev/null; echo ""
        echo -n "stack: "
        /system/bin/toybox cat "$tid/stack" 2>/dev/null; echo ""
      done
    fi
    SS_PID=$(/system/bin/toybox pidof system_server)
    echo "SS_PID: $SS_PID"
    if [ -n "$SS_PID" ]; then
      for tid in /proc/$SS_PID/task/*; do
        echo "--- SS TID: $tid ---"
        /system/bin/toybox cat "$tid/status" | grep -E "Name:|State:"
        echo -n "wchan: "
        /system/bin/toybox cat "$tid/wchan" 2>/dev/null; echo ""
        echo -n "stack: "
        /system/bin/toybox cat "$tid/stack" 2>/dev/null; echo ""
      done
    fi

    # Skip debuggerd -b to avoid IPC deadlocks with tombstoned
    echo "=== SAVING FULL LOGCAT ==="
    /system/bin/logcat -d > /data_logcat.log

    echo "=== LOGCAT ZYGOTE / SYSTEM_SERVER ==="
    /system/bin/logcat -d | grep -iE "zygote|app_process|system_server|fatal|exception" | tail -n 60

    echo "=== TOMBSTONES SUMMARY ==="
    /system/bin/toybox cp /data/tombstones/* /tombstone_export/ 2>/dev/null
    if [ "{settings_sigquit}" = "1" ] || [ "{sf_sigquit}" = "1" ]; then
      /system/bin/toybox cp /data/anr/trace_* /tombstone_export/ 2>/dev/null
    fi
    for t in /data/tombstones/*.pb; do
      if [ -f "$t" ]; then
        echo "Tombstone: $t"
        /system/bin/toybox strings "$t" | grep -E "Cmdline:|pid:|signal |>>>|<<<" | head -n 10
      fi
    done
    for t in /data/tombstones/tombstone_[0-9][0-9]; do
      if [ -f "$t" ]; then
        echo "Tombstone Text: $t"
        /system/bin/toybox head -n 45 "$t"
      fi
    done

    kill -9 $INIT_PID 2>/dev/null
  '
"""
    runner_script.write_text(script_text)
    runner_script.chmod(0o755)

    p = subprocess.Popen(["unshare", "-U", "-m", "-p", "-n", "-f", str(runner_script)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True)
    uid = os.getuid()
    gid = os.getgid()
    # Wait until unshare has entered the new user namespace. Mapping the PID
    # while it still belongs to our host namespace fails with EPERM.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if p.poll() is not None:
            raise RuntimeError("unshare exited before user namespace mapping")
        try:
            if not Path(f"/proc/{p.pid}/uid_map").read_text().strip():
                break
        except FileNotFoundError:
            pass
        time.sleep(0.01)
    else:
        raise TimeoutError("unshare did not enter a new user namespace")
    uid_map, gid_map, _uid_range, _gid_range = aaas_idmap.map_commands(
        p.pid, host_uid=uid, host_gid=gid)
    subprocess.run(uid_map, check=True)
    subprocess.run(gid_map, check=True)

    with open(fifo_path, "w") as f:
        f.write("go\n")

    try:
        out, err = p.communicate(timeout=140)
    except subprocess.TimeoutExpired:
        # unshare -f may have exited while bwrap still holds these pipes.
        # Killing only p leaves the namespace child alive and communicate()
        # waiting forever for EOF. All descendants inherit this process group.
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, err = p.communicate(timeout=10)

    fifo_path.unlink(missing_ok=True)
    runner_script.unlink(missing_ok=True)

    print("STDOUT:")
    print(out.decode('utf-8', errors='replace'))
    if egl_test_log.exists() and egl_test_log.stat().st_size > 0:
        print("\n=== EGL TEST RESULT LOG ===")
        print(egl_test_log.read_text())
        print("=== END EGL TEST RESULT LOG ===\n")

    if err:
        print("STDERR:")
        print(err.decode('utf-8', errors='replace'))

    print("\nKMSG LOG TAIL:")
    for l in kmsg_log.read_text().splitlines()[-30:]:
        print("  ", l)

    return 0


if __name__ == '__main__':
    sys.exit(main())
