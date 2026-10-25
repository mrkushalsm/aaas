# Android 16 runtime integrity gate

The SDK image identified in `manifests/android-images.json` is the provenance
baseline. The extracted `rootfs_m1b1` on the external disk is a diagnostic
experiment, **not** an installable Android runtime. Do not copy it into an
installer or infer boot success from its service registrations.

## Verified modifications

`scripts/audit_android_runtime.py` compares critical files byte-for-byte with
the original raw LP partitions using `debugfs`. Its 2026-10-26 run returned 1:
16 files modified and stock `/system/bin/surfaceflinger` identical. The
machine-readable report is retained outside Git at
`$AAAS_WORKSPACE/logs/runtime-integrity.json`. Important modifications include:

- Binary edits to `servicemanager`, `hwservicemanager`, `libbinder.so`,
  `libhidlbase.so`, `libandroid_runtime.so`, and `apexd.real`.
- Scripts replacing `apexd` bootstrap, `vdc`, and `vold` behavior. The apexd
  wrapper sets its own status properties during bootstrap; these properties do
  not prove package activation.
- Init `.rc` edits disabling several `reboot_on_failure` directives, changing
  hardware properties, adding preload exceptions, and skipping Ranchu mounts.
- A local `libselinux_shim.so` that returns success for SELinux calls, selected
  mounts, and failed priority changes, and strips a Binder security flag.

The separate SwiftShader checkout at `$AAAS_WORKSPACE/sources/swiftshader`
contains four locally edited files. Its added Vulkan functions return success
while discarding acquire fence FDs, and its release function returns no fence.
This invalidates any claim that the Android rendering path honors explicit
synchronization. The M1A.1 synthetic host transport experiment is separate;
its results do not validate this modified Android Vulkan stack.

The untracked `experiments/m1b/surfaceflinger_minimal.cpp` is a diagnostic
stub. Its `main()` returns before the service-registration code. The staged
rootfs currently has the genuine SurfaceFlinger binary, but the rest of the
staged image is modified.

## Repeatable integrity check

```sh
export AAAS_WORKSPACE=/run/media/mrkus/Homework/aaas-workspace
python3 scripts/android_workspace.py --workspace "$AAAS_WORKSPACE" check
python3 scripts/audit_android_runtime.py \
  --rootfs "$AAAS_WORKSPACE/rootfs_m1b1" \
  --partitions "$AAAS_WORKSPACE/tmp/partitions" \
  --output "$AAAS_WORKSPACE/logs/runtime-integrity.json"
```

Exit 0 means every listed critical file matches the source image. Exit 1
means modified, missing, or unreadable files. The checker never repairs or
deletes anything. It is deliberately a critical-file gate, not a complete
filesystem attestation. A clean install path must also checksum the source
archive and use a fresh extraction, with an inventory of every intentional
overlay and its license.

## Upstream graphics path and exact blocker

The Android 16 SDK image declares Ranchu AIDL allocator v2 and native Mapper
5. Its `mapper.ranchu.so` aborts when Goldfish address-space hardware is
absent. Intercepting `/dev/goldfish_*` opens would fake an emulator device and
would not implement buffer allocation or synchronization.

The source-verified upstream candidate in
`manifests/android-graphics-candidates.json` contains **both**
`android.hardware.graphics.allocator-service.minigbm` and
`mapper.minigbm`, with their init and VINTF fragments. The pinned source was
fetched to `$AAAS_WORKSPACE/sources/minigbm` and its commit verified. Its
Soong build depends on matching Android platform libraries and generated
interfaces including allocator-V2-ndk, libbinder_ndk, libgralloctypes,
libhidlbase, libimapper_stablec, libminigbm_gralloc, and DRM libraries.
The SDK image is an earlier Android 16 build than the pinned QPR2 source;
binary ABI compatibility is **unverified**. No allocator or mapper binary was
built, swapped, or run. This is the current technical stop boundary.

The next experiment is a matched Android source build of the allocator,
mapper, their dependency closure, init/VINTF fragments, and a Composer3
implementation against the **same image ABI**. Validate native-handle layout,
DMA-BUF export/import, format/modifier negotiation, and real acquire/release
fences before starting stock SurfaceFlinger. If the SDK image cannot be
matched, use a source-built product or verified image from the same build
graph. Do not use a binary patch or success-returning shim to pass this gate.

## Installation boundary

Current container runners contain fixed user paths, subuid ranges, cgroup
paths, Ranchu boot properties, and a global `LD_PRELOAD`. Several diagnostic
runners return exit 0 even when the Android process fails. They are not an
installer. An installable runtime needs capability detection, configurable
paths, per-distribution prerequisites, and fail-closed checks for Binder,
namespaces, cgroups, security policy, and the graphics stack. No host-wide
security setting should be weakened by setup or runtime scripts.
