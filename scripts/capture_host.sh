#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
out=results/m0/host
mkdir -p "$out"
for entry in 'uname -a' 'cat /etc/os-release' 'systemd --version' 'lscpu' 'lspci -nnk' 'wayland-info' 'vulkaninfo --summary' 'glxinfo -B' 'eglinfo' 'find /dev/dri -maxdepth 1 -ls' 'cat /proc/filesystems' 'cat /proc/self/uid_map' 'cat /proc/self/gid_map' 'cat /proc/sys/kernel/unprivileged_userns_clone' 'cat /sys/fs/cgroup/cgroup.controllers' 'cat /sys/fs/cgroup/cgroup.subtree_control' 'lsmod' 'findmnt -t cgroup2,binder' 'loginctl show-session "$XDG_SESSION_ID" -p Type -p Desktop -p Name'; do
  name=$(printf '%s' "$entry" | tr ' /$"' '_____ ' | tr -cd '[:alnum:]_.-')
  { printf '$ %s\n' "$entry"; bash -c "$entry"; } >"$out/$name.log" 2>&1
done
printf 'WAYLAND_DISPLAY=%s\nXDG_CURRENT_DESKTOP=%s\nXDG_SESSION_TYPE=%s\n' "${WAYLAND_DISPLAY:-}" "${XDG_CURRENT_DESKTOP:-}" "${XDG_SESSION_TYPE:-}" > "$out/session.env"
printf 'Captured host evidence in %s\n' "$out"
