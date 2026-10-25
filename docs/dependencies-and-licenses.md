# Preliminary dependency and license audit

This is a source-level planning matrix, not legal clearance. Full transitive SBOM and exact Android lock are blocked by the unmaterialized AOSP project graph and unavailable product build. Review LICENSE/COPYING and generated build dependency graphs before importing code.

The actual M0.1 Lipstick probe subset, including a 389-package isolated-image notice inventory and the unresolved Sailfish dependencies, is audited separately in `lipstick-m01.md`. That audit does not extend to the whole Android runtime.

| Component | Report license / status | Build/toolchain and dependencies | Privilege/hardware |
|---|---|---|---|
| AOSP 16 + drm_hwcomposer + Goldfish | Mostly Apache-2.0; transitive AOSP notices pending | repo/Soong, Android clang/JDK; exact manifest absent | Binder, render node, large build host |
| Lipstick | LGPLv2 according to report; verify files | qmake/Qt5, QtWayland and Sailfish MCE/DSME/Nemo/system services | Wayland server; nested compositor test |
| Qt HWC plugin | GPLv3/LGPLv2.1 exception per report; inspect exact files | qmake/Qt5, libhybris, Android headers/HWC ABI | HWC/EGL service for runtime probe |
| libhybris / libgbinder | mixed licenses / BSD-3-Clause respectively | Autotools/Meson and GLib; full dependency closure pending | Binder/HWC depending test |
| Digitalis/Teto/Berberis | Apache-2.0 plus upstream notices; inspect transitive | AOSP 16, repo/Soong, NDK, AArch64 toolchain; manifest pin absent | x86_64 Android image; ample disk/RAM |
| LXC | LGPL-2.1+ core, component notices pending | Autotools/Meson, libcap/seccomp/SELinux/AppArmor options | userns, cgroup2, Binder/render nodes |
| Waydroid | GPL-3.0; HAL Apache/Android mix | Python, LXC, Android image | container setup; host-wide install avoided |
| Droidloom | GPL-3.0-or-later original code per report | inspect pinned repository before build | Android image, Binder, GPU/Wayland |
| Mesa/Zink, PipeWire, portals | mixed permissive / LGPL ecosystem | distro-provided versions recorded in host logs | GPU and desktop services |

Competitor code remains external under ignored `sources/`. No competitor implementation has been copied into production modules. Toolchain exact versions and full transitive dependencies are unresolved until source build systems and an AOSP manifest are locked.
