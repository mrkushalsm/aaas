#!/bin/sh
# Run stock Android servicemanager with real binderfs and no preload shim.
set -eu

if [ -z "${AAAS_WORKSPACE:-}" ]; then
    echo 'AAAS_WORKSPACE is required' >&2
    exit 2
fi
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 "$script_dir/android_workspace.py" --workspace "$AAAS_WORKSPACE" \
    --predict-gib 0.016 check >/dev/null

system_image=$AAAS_WORKSPACE/tmp/partitions/system.raw.img
payload=$AAAS_WORKSPACE/tmp/clean_runtime_payload.img
log=$AAAS_WORKSPACE/logs/clean-servicemanager-probe.log
kmsg=$AAAS_WORKSPACE/logs/clean-servicemanager-kmsg.log
if [ ! -f "$system_image" ]; then
    echo "missing system image: $system_image" >&2
    exit 2
fi

probe_dir=$(mktemp -d /tmp/aaas-clean-sm.XXXXXX)
system_mount=$probe_dir/system
runtime_mount=$probe_dir/runtime
binder_mount=$probe_dir/binder
mkdir "$system_mount" "$runtime_mount" "$binder_mount"
system_mounted=0
runtime_mounted=0
cleanup() {
    if [ "$runtime_mounted" -eq 1 ]; then guestunmount "$runtime_mount" || true; fi
    if [ "$system_mounted" -eq 1 ]; then guestunmount "$system_mount" || true; fi
    rmdir "$binder_mount" "$runtime_mount" "$system_mount" "$probe_dir" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

guestmount --ro -a "$system_image" -m /dev/sda "$system_mount"
system_mounted=1
python3 - "$system_mount/system/apex/com.android.runtime.apex" "$payload" <<'PY'
import hashlib
from pathlib import Path
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    data = archive.read('apex_payload.img')
target = Path(sys.argv[2])
if target.exists():
    if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(data).digest():
        raise SystemExit(f'conflicting cached APEX payload: {target}')
else:
    target.write_bytes(data)
PY
guestmount --ro -a "$payload" -m /dev/sda "$runtime_mount"
runtime_mounted=1
: > "$kmsg"

set +e
timeout 10 unshare -Ur -m sh -c '
    binder_mount=$1
    system_mount=$2
    runtime_mount=$3
    kmsg=$4
    mount -t binder binder "$binder_mount" || exit 3
    python3 - "$binder_mount" <<"PY"
import fcntl
import os
import struct
import sys

mount = sys.argv[1]
ctl = os.open(mount + "/binder-control", os.O_RDWR)
request = bytearray(struct.pack("256sII", b"binder", 0, 0))
fcntl.ioctl(ctl, 0xc1086201, request)
os.close(ctl)
os.chmod(mount + "/binder", 0o666)
PY
    exec bwrap --unshare-pid --unshare-net --clearenv \
      --setenv PATH /system/bin --setenv ANDROID_ROOT /system \
      --ro-bind "$system_mount" / --tmpfs /apex \
      --ro-bind "$runtime_mount" /apex/com.android.runtime \
      --dev /dev --bind "$kmsg" /dev/kmsg \
      --dir /dev/binderfs --dev-bind "$binder_mount" /dev/binderfs \
      --symlink /dev/binderfs/binder /dev/binder \
      --proc /proc --tmpfs /tmp /system/bin/servicemanager
' sh "$binder_mount" "$system_mount" "$runtime_mount" "$kmsg" > "$log" 2>&1
probe_exit=$?
set -e
printf 'stock servicemanager exit=%s\n' "$probe_exit"
printf 'log=%s\nkmsg=%s\n' "$log" "$kmsg"
exit "$probe_exit"
