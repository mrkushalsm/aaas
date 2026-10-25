# Captured host capabilities, 2026-10-25

Raw commands and output: `results/m0/host/`; component package checks: `results/m0/components.log`. This is a single-machine snapshot.

| Area | Observation |
|---|---|
| OS/kernel | EndeavourOS rolling; Linux 7.2.9-arch1-1 x86_64; systemd version in raw log |
| CPU | Intel Core i5-12450H, VT-x |
| Session | KDE/KWin Wayland, `wayland-0` |
| GPU | Intel Alder Lake-P UHD (`i915`) and NVIDIA GeForce RTX 2050; Vulkan reports NVIDIA physical GPU and llvmpipe; GLX reports Intel. Cross-GPU behavior untested. |
| Graphics userspace | Wayland 1.26.0, libdrm 2.4.134, GBM 26.2.4, PipeWire dev 1.6.9; full EGL/Vulkan details in raw logs |
| Wayland globals | `xdg_wm_base` v6, `zwp_linux_dmabuf_v1` v5, `wp_presentation` v2, `wp_linux_drm_syncobj_manager_v1` v1, fractional scale v1 advertised. Import/fence operation not tested. |
| Device access | `/dev/dri/renderD128` and `renderD129` visible with read/write permission. No Binder device nodes were observed; `/proc/filesystems` advertises binder filesystem. Binder mount and Android operation untested. |
| Isolation | Unprivileged userns sysctl is 1; cgroup v2 mounted; controllers include cpu, cpuset, io, memory, pids. Userns creation, cgroup delegation and LXC runtime operation untested. |
| Toolchains | clang/cmake/make/qmake Qt 5.15.19 and qmake6 Qt 6.11.2 present. Qt5WaylandCompositor pkg-config present; Qt5Sensors, Android headers, libgbinder, LXC, repo and adb absent. QEMU AArch64 user executable present. |

No security control was changed and no host-wide package was installed.
