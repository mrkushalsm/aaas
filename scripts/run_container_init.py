#!/usr/bin/env python3
"""Runner for Android 16 container init and service lifecycle experiments.

Establishes unprivileged user, mount, and PID namespaces with subuid delegation,
masked sysctls, cgroup v2 subtree delegation, and unprivileged binderfs.
"""

import argparse
import ctypes
import fcntl
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class BinderctlNum(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char * 256),
        ("major", ctypes.c_uint32),
        ("minor", ctypes.c_uint32)
    ]


IOC_BINDER_ADD = 0xc1086201


def prepare_dummy_sysctls(tmp_dir: Path) -> dict:
    files = {
        'kptr': tmp_dir / 'fake_kptr',
        'sysrq': tmp_dir / 'fake_sysrq',
        'modprobe': tmp_dir / 'fake_modprobe',
        'mmap_rnd_bits': tmp_dir / 'fake_mmap_rnd_bits',
        'mmap_rnd_compat_bits': tmp_dir / 'fake_mmap_rnd_compat_bits',
        'cmdline': tmp_dir / 'fake_cmdline',
    }
    files['kptr'].write_text("0\n")
    files['sysrq'].write_text("0\n")
    files['modprobe'].write_text("\n")
    files['mmap_rnd_bits'].write_text("32\n")
    files['mmap_rnd_compat_bits'].write_text("16\n")
    files['cmdline'].write_text("console=tty0 androidboot.hardware=ranchu androidboot.fstab_suffix=ranchu androidboot.serialno=aaas001\n")
    return files


def run_init_container(rootfs: Path, target_cmd: list, timeout_sec: int = 5) -> tuple:
    tmp_dir = Path("/run/media/mrkus/Aaas/aaas-workspace/tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    kmsg_log = tmp_dir / "kmsg_boot.log"
    kmsg_log.write_text("")

    sysctls = prepare_dummy_sysctls(tmp_dir)

    cgroup_dir = Path("/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/aaas")
    cgroup_dir.mkdir(parents=True, exist_ok=True)

    fifo_path = tmp_dir / f"init_fifo_{os.getpid()}"
    if fifo_path.exists():
        fifo_path.unlink()
    os.mkfifo(fifo_path)

    # Shell script executed inside unshare (child namespace)
    child_script = tmp_dir / f"child_runner_{os.getpid()}.sh"
    target_cmd_str = " ".join(f'"{c}"' for c in target_cmd)
    script_content = f"""#!/bin/sh
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
  --bind "{sysctls['cmdline']}" /proc/cmdline \\
  --dev /dev \\
  --dev-bind /tmp/binder_mnt /dev/binderfs \\
  --symlink /dev/binderfs/binder /dev/binder \\
  --symlink /dev/binderfs/hwbinder /dev/hwbinder \\
  --symlink /dev/binderfs/vndbinder /dev/vndbinder \\
  --bind "{kmsg_log}" /dev/kmsg \\
  --bind "{cgroup_dir}" /sys/fs/cgroup \\
  --bind "{sysctls['kptr']}" /proc/sys/kernel/kptr_restrict \\
  --bind "{sysctls['sysrq']}" /proc/sys/kernel/sysrq \\
  --bind "{sysctls['modprobe']}" /proc/sys/kernel/modprobe \\
  --bind "{sysctls['mmap_rnd_bits']}" /proc/sys/vm/mmap_rnd_bits \\
  --bind "{sysctls['mmap_rnd_compat_bits']}" /proc/sys/vm/mmap_rnd_compat_bits \\
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
  {target_cmd_str}
"""
    child_script.write_text(script_content)
    child_script.chmod(0o755)

    p = subprocess.Popen(["unshare", "-U", "-m", "-p", "-f", str(child_script)])
    uid = os.getuid()
    gid = os.getgid()
    subprocess.run(["newuidmap", str(p.pid), "0", str(uid), "1", "1", "100000", "65535"], check=True)
    subprocess.run(["newgidmap", str(p.pid), "0", str(gid), "1", "1", "100000", "65535"], check=True)

    with open(fifo_path, "w") as f:
        f.write("go\n")

    time.sleep(timeout_sec)
    poll_ret = p.poll()
    is_running = (poll_ret is None)
    if is_running:
        p.terminate()
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            p.kill()

    log_content = kmsg_log.read_text() if kmsg_log.exists() else ""
    fifo_path.unlink(missing_ok=True)
    child_script.unlink(missing_ok=True)

    return is_running, poll_ret, log_content


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rootfs', default='/run/media/mrkus/Aaas/aaas-workspace/rootfs_m1b1')
    ap.add_argument('--timeout', type=int, default=4)
    ap.add_argument('cmd', nargs='*', default=['/system/bin/init', 'second_stage'])
    args = ap.parse_args()

    rootfs = Path(args.rootfs)
    print(f"Launching Android container command: {args.cmd}")
    running, ret, kmsg = run_init_container(rootfs, args.cmd, args.timeout)

    print(f"Result: still_running={running}, return_code={ret}")
    print(f"Captured {len(kmsg.splitlines())} KMSG lines:")
    for l in kmsg.splitlines()[-40:]:
        print(f"  {l}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
