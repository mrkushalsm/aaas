#!/usr/bin/env python3
"""Bounded probe testing Binder service registration, lookup, and IPC transactions."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    workspace = Path(os.environ.get("AAAS_WORKSPACE", Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "aaas/workspace"))
    rootfs = workspace / "rootfs_m1b1"
    tmp_dir = workspace / "tmp"
    if not rootfs.is_dir():
        raise SystemExit(f"Android rootfs not found: {rootfs}; set AAAS_WORKSPACE")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    kmsg_log = tmp_dir / "kmsg_binder_test.log"
    kmsg_log.write_text("")

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
    fake_cmdline.write_text("console=tty0 androidboot.hardware=ranchu androidboot.fstab_suffix=ranchu androidboot.serialno=aaas001\n")

    cgroup_dir = Path("/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/aaas")
    cgroup_dir.mkdir(parents=True, exist_ok=True)

    fifo_path = tmp_dir / f"binder_fifo_{os.getpid()}"
    if fifo_path.exists():
        fifo_path.unlink()
    os.mkfifo(fifo_path)

    runner_script = tmp_dir / f"run_binder_probe_{os.getpid()}.sh"
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
'
exec bwrap \\
  --as-pid-1 \\
  --unshare-pid \\
  --bind "{rootfs}" / \\
  --proc /proc \\
  --bind "{fake_cmdline}" /proc/cmdline \\
  --dev /dev \\
  --dev-bind /tmp/binder_mnt /dev/binderfs \\
  --symlink /dev/binderfs/binder /dev/binder \\
  --symlink /dev/binderfs/hwbinder /dev/hwbinder \\
  --symlink /dev/binderfs/vndbinder /dev/vndbinder \\
  --bind "{kmsg_log}" /dev/kmsg \\
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
    sleep 1.5

    # Start servicemanager if not yet started by trigger
    /system/bin/servicemanager &
    SM_PID=$!
    sleep 0.5

    echo "=== PROBE 1: SERVICE LIST ==="
    
    /system/bin/hwservicemanager &
    HW_PID=$!
    sleep 0.5
    /system/bin/service list


    echo "=== PROBE 2: SERVICE CHECK UNREGISTERED ==="
    /system/bin/service check test_service_unregistered

    echo "=== PROBE 3: SERVICE CHECK REGISTERED ==="
    /system/bin/service check manager
    /system/bin/service check android.system.suspend.ISystemSuspend/default

    kill -9 $SM_PID $INIT_PID 2>/dev/null
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
        out, err = p.communicate(timeout=8)
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

    return 0


if __name__ == '__main__':
    sys.exit(main())
