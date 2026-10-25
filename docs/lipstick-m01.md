# Lipstick M0.1 dependency and build audit

**Verdict:** blocked before an x86_64 `simplecompositor` executable. No nested runtime test was run. Build failures are kept as failures; none demonstrates compositor behavior.

## Source and toolchain boundary

The pinned Lipstick `b220a976699b30d69e00b5a6480ade809fca55ae` RPM spec is the authoritative immediate dependency list. `scripts/audit_lipstick_deps.py` extracts 43 direct `BuildRequires`/`Requires` entries. It does not resolve RPM transitive dependencies. `results/m01/lipstick/dependencies-host.json` and `dependencies-container.json` record pkg-config checks.

The host has Qt 5.15.19, QtWaylandCompositor, and its private module, but **not** Qt Sensors or qmake modules `compositor`/`compositor-private`. Those legacy module names and the `QtCompositor/QWaylandSurfaceInterface` API come from Sailfish's `qtwayland` fork at `f377218d71c1c2de7b0cf71f0acd551309d8e86b`; its `.qmake.conf` declares module version **5.6.3**. Stock QtWaylandCompositor 5.15 is not a source-compatible substitute by mere module renaming. The fork's license tree includes LGPLv2.1, LGPLv3, GPLv3, and FDL texts; individual source files also carry BSD notices. No blanket license conclusion is inferred from one file.

The `simple-compositor.pro` target links `liblipstick-qt5` and directly requests `mlite5`, `dsme_dbus_if`, `thermalmanager_dbus_if`, and `usb_moded`. The library additionally requests MCE, MCE Qt bindings, keepalive, resource Qt, NGF, Nemo device lock/connectivity, systemsettings, USB ModeD Qt, Sailfish user manager, GLib, D-Bus, systemd, Qt Sensors, and the legacy compositor modules. This is a library dependency closure even though the simple tool avoids full homescreen QML. The upstream spec also lists runtime MCE, Nemo PulseAudio main volume, user-managerd, and sailjail-daemon. These are **not** satisfied in the isolated x86_64 image.

The official Sailfish SDK documents Docker build engines, but its public generic targets are i486, ARMv7, and AArch64, not x86_64. Installing an i486 target would not demonstrate the required x86_64 ELF. The SDK is not installed here. [SDK installation](https://docs.sailfishos.org/Tools/Sailfish_SDK/Installation/), [target list](https://docs.sailfishos.org/Tools/Platform_SDK/Target_Installation/).

## Isolated environment and attempts

`experiments/lipstick/Dockerfile` uses Debian bookworm-slim base digest `sha256:7ff6ba31527b9e336162fa061746c366c4b2032f4d2cff2078bea43f78efe3f8`, an archived Debian package snapshot dated 2026-10-20, and a contained x86_64 Qt 5.15.8 toolchain. The first `ca-certificates` bootstrap comes from the base image's live Debian mirror because that minimal image lacks trusted TLS roots; the observed package version and all installed package versions are recorded in `image-packages-and-notices.json`. The built image ID is in `image-id.txt`. Rebuilds should compare package inventory and image ID; a later live bootstrap drift must be reported.

```sh
experiments/lipstick/build-isolated.sh
python3 scripts/audit_lipstick_deps.py --source sources/lipstick-m01 \
  --output results/m01/lipstick/dependencies-host.json
```

Docker runs the builds with no network, no added capabilities, `no-new-privileges`, source bind mounts read-only, and output only under `results/m01/lipstick/`. No host package or Qt installation changed. The image contains 389 installed packages; all have a Debian copyright file and SHA-256 recorded in `image-packages-and-notices.json`. This is a notice and version inventory, **not** legal clearance for all 389 packages. Direct license review: Lipstick's spec says LGPLv2 while its bundled text is LGPLv2.1; Debian Qt packages expose mixed LGPL/GPL/BSD options; Wayland uses X11; D-Bus and GLib carry mixed notices. Sailfish-only missing packages and their transitive closure remain unreviewed.

| Probe | Exact result | Evidence |
|---|---|---|
| Fresh host upstream qmake/make | `make` exit 2; missing `compositor`, `compositor-private`, `sensors` | `upstream-host.log` |
| Isolated upstream qmake/make | missing `compositor`, `compositor-private` with Qt Sensors resolved; exit 2 | `upstream-container.log` |
| Isolated Sailfish QtWayland full build | configure succeeds; build stops at missing `QT_PRIVATE: platformsupport-private` | `qtwayland-fork.log` |
| Isolated QtCompositor-only target | generated headers then C++ compile fails on missing generated `QtCompositor/private/qwayland-server-wayland.h` in include tree; exit 2 | `qtwayland-compositor-only.log` |
| Isolated `simplecompositor` qmake/make | configure fails at missing `mlite5`; no binary | `simplecompositor-container.log` |

The QtCompositor-only generated protocol headers are not exposed under the `QtCompositor/private` include path expected by this Qt 5.6.3 fork when built with Qt 5.15.8. This is a build-system/toolchain incompatibility **observed at compile time**; later source-level compatibility is untested. No stub or upstream source patch was used.

## Runtime gate preparation

`experiments/lipstick/test-client/` provides an x86_64 Qt Wayland client that records focus, resize, close, and expose events. It compiled on the host. `nested_test.py` launches a compositor command and two clients, checks focus/geometry/close evidence, then kills the compositor while client B remains to test disconnect cleanup. It requires a working `simplecompositor` binary and a known nested Wayland socket. Its event validator has a synthetic unit test. It has **not** been run against Lipstick.

Stop point: obtain a coherent x86_64 Sailfish Qt 5.6.3/QtCompositor build and the real Sailfish development packages, or document a source-level port with its own test gates. Do not substitute Qt 5.15 modules by name or remove dependencies to make the probe green.
