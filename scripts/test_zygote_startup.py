#!/usr/bin/env python3
"""Test Android 16 Zygote (app_process64) startup while property service is active."""

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def main():
    rootfs = Path("/run/media/mrkus/Homework/aaas-workspace/rootfs_m1b1")
    tmp_dir = Path("/run/media/mrkus/Homework/aaas-workspace/tmp")
    prefix = os.environ.get("AAAS_LOG_PREFIX", "")
    kmsg_log = tmp_dir / f"{prefix}kmsg_zygote_test.log"
    kmsg_log.write_text("")
    os.chmod(kmsg_log, 0o666)
    full_logcat_log = tmp_dir / f"{prefix}full_logcat.log"
    full_logcat_log.write_text("")
    os.chmod(full_logcat_log, 0o666)
    sf_strace_log = tmp_dir / f"{prefix}sf_strace.log"
    sf_strace_log.write_text("")
    os.chmod(sf_strace_log, 0o666)

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

    overlay_composer = tmp_dir / "android.hardware.graphics.composer3-service.aaas"
    composer_bind = f'  --bind "{overlay_composer}" /vendor/bin/hw/android.hardware.graphics.composer3-service.ranchu \\\n' if (overlay_composer.exists() and os.environ.get("AAAS_USE_AAAS_COMPOSER", "1") == "1") else ""

    probe_bin = tmp_dir / "surfaceflinger_probe"
    probe_bind = f'  --bind "{probe_bin}" /system/bin/surfaceflinger_probe \\\n' if probe_bin.exists() else ""
    sf_probe_env = os.environ.get("AAAS_SF_PROBE", "0")

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
{mapper_bind}{composer_bind}{probe_bind}  --proc /proc \\
  --bind "{fake_cmdline}" /proc/cmdline \\
  --dev /dev \\
  --dev-bind /dev/dri /dev/dri \\
  --dev-bind /tmp/binder_mnt /dev/binderfs \\
  --symlink /dev/binderfs/binder /dev/binder \\
  --symlink /dev/binderfs/hwbinder /dev/hwbinder \\
  --symlink /dev/binderfs/vndbinder /dev/vndbinder \\
  --bind "{kmsg_log}" /dev/kmsg \\
  --bind "{full_logcat_log}" /data_logcat.log \\
  --bind "{sf_strace_log}" /data_sf_strace.log \\
  --bind "{cgroup_dir}" /sys/fs/cgroup \\
  --bind "{fake_kptr}" /proc/sys/kernel/kptr_restrict \\
  --bind "{fake_sysrq}" /proc/sys/kernel/sysrq \\
  --bind "{fake_modprobe}" /proc/sys/kernel/modprobe \\
  --bind "{fake_mmap}" /proc/sys/vm/mmap_rnd_bits \\
  --bind "{fake_mmap_compat}" /proc/sys/vm/mmap_rnd_compat_bits \\
  --tmpfs /tmp \\
  --tmpfs /dev/socket \\
  --tmpfs /dev/__properties__ \\
  --tmpfs /data \\
  --setenv PATH /system/bin:/apex/com.android.art/bin \\
  --setenv ANDROID_ROOT /system \\
  --setenv ANDROID_DATA /data \\
  --setenv ANDROID_ART_ROOT /apex/com.android.art \\
  --setenv ANDROID_I18N_ROOT /apex/com.android.i18n \\
  --setenv ANDROID_TZDATA_ROOT /apex/com.android.tzdata \\
  --setenv LD_PRELOAD /system/lib64/libselinux_shim.so \\
  sh -c '
    /system/bin/init second_stage &
    INIT_PID=$!
    sleep 1.0

    echo "=== STEP 1: SETTING APEX & KEYSTORE PROPS ==="
    /system/bin/setprop sys.use_memfd true
    /system/bin/setprop ro.hw_timeout_multiplier 4
    /system/bin/setprop apexd.status activated
    /system/bin/setprop keystore.module_hash.sent true
    /system/bin/setprop log.tag.SurfaceFlinger VERBOSE
    /system/bin/setprop log.tag.HWComposer VERBOSE
    /system/bin/setprop log.tag.RanchuHwc VERBOSE
    /system/bin/setprop log.tag.Composer VERBOSE
    /system/bin/setprop log.tag.RenderEngine VERBOSE
    /system/bin/setprop service.sf.prime_shader_cache 0
    /system/bin/setprop debug.sf.nobootanimation 1
    /system/bin/setprop service.bootanim.exit 1
    /system/bin/start apexd
    /system/bin/start installd
    /system/bin/start vendor.light-default
    /system/bin/start vendor.hwcomposer-3
    if [ "{sf_probe_env}" = "1" ]; then
      echo "=== STARTING DIAGNOSTIC SURFACEFLINGER PROBE ==="
      /system/bin/surfaceflinger_probe &
    else
      /system/bin/strace -f -tt -T -s 128 -o /data_sf_strace.log /system/bin/surfaceflinger &
    fi
    sleep 2.0

    echo "=== STEP 2: SETTING ODSIGN DONE & STARTING ZYGOTE ==="
    /system/bin/setprop odsign.key.done 1
    /system/bin/setprop odsign.verification.done 1
    
    echo "=== WAITING FOR SYSTEM_SERVER BOOTSTRAP (5s) ==="
    sleep 5.0

    echo "=== CHECKING BINDER SERVICES ==="
    /system/bin/service list

    echo "=== PROBING CORE BOOTSTRAP SERVICES ==="
    /system/bin/service check package
    /system/bin/service check activity
    /system/bin/service check power
    /system/bin/service check display
    /system/bin/service check apexservice

    echo "=== TESTING PACKAGE MANAGER COMMAND IPC ==="
    /system/bin/cmd package list packages

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

    echo "=== SAVING FULL LOGCAT ==="
    /system/bin/logcat -d > /data_logcat.log

    echo "=== LOGCAT ZYGOTE / SYSTEM_SERVER ==="
    /system/bin/logcat -d | grep -iE "zygote|app_process|system_server|fatal|exception" | tail -n 60

    echo "=== TOMBSTONES SUMMARY ==="
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

    p = subprocess.Popen(["unshare", "-U", "-m", "-p", "-f", str(runner_script)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    uid = os.getuid()
    gid = os.getgid()
    subprocess.run(["newuidmap", str(p.pid), "0", str(uid), "1", "1", "100000", "65535"], check=True)
    subprocess.run(["newgidmap", str(p.pid), "0", str(gid), "1", "1", "100000", "65535"], check=True)

    with open(fifo_path, "w") as f:
        f.write("go\n")

    try:
        out, err = p.communicate(timeout=80)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()

    fifo_path.unlink(missing_ok=True)
    runner_script.unlink(missing_ok=True)

    print("STDOUT:")
    print(out.decode('utf-8', errors='replace'))
    if err:
        print("STDERR:")
        print(err.decode('utf-8', errors='replace'))

    print("\nKMSG LOG TAIL:")
    for l in kmsg_log.read_text().splitlines()[-30:]:
        print("  ", l)

    return 0


if __name__ == '__main__':
    sys.exit(main())
