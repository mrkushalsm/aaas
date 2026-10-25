#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
out=results/m0/components.log
{
  for package in wayland-client wayland-server wayland-egl libdrm gbm egl glesv2 Qt5Core Qt5WaylandCompositor Qt5Sensors hwcomposer2 android-headers libgbinder libpipewire-0.3 lxc; do
    if pkg-config --exists "$package"; then
      printf '%s available %s\n' "$package" "$(pkg-config --modversion "$package")"
    else
      printf '%s unavailable\n' "$package"
    fi
  done
  for command in repo adb qemu-aarch64 lxc-start weston waydroid droidloom; do
    command -v "$command" || printf '%s unavailable\n' "$command"
  done
} > "$out" 2>&1
cat "$out"
