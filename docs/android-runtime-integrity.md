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
  --swiftshader-source "$AAAS_WORKSPACE/sources/swiftshader" \
  --output "$AAAS_WORKSPACE/logs/runtime-integrity.json"
```

Exit 0 means every listed critical file matches the source image. Exit 1
means modified, missing, or unreadable files, known extra shims, or local
SwiftShader source edits. The checker never repairs or deletes anything. It
is deliberately a critical-file gate, not a complete
filesystem attestation. A clean install path must also checksum the source
archive and use a fresh extraction, with an inventory of every intentional
overlay and its license.

## Workspace filesystem-health gate

`scripts/android_workspace.py check` validates mount identity and capacity,
then applies the UUID-scoped policy in
`manifests/workspace-health.json` before recursive workspace accounting.
`DEVICE_FAILURE_SUSPECTED`, `REPAIR_REQUIRED`, `INTEGRITY_WARNING`, and
`HEALTH_UNKNOWN` block NTFS3 runtime use. The separate `health` action performs
bounded, read-only current-boot journal inspection and a passive `smartctl`
information query; it does not run a consistency check or repair. A clean
mount or empty recent journal cannot clear a pause. Recovery requires explicit
offline-check, device-health, and post-mount evidence. Current volume status
and recovery criteria are recorded in
[`ntfs3-health-assessment-2026-11-07.md`](storage/ntfs3-health-assessment-2026-11-07.md).

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

### Bounded upstream build probe (2026-10-26)

The pinned AOSP superproject revision in the graphics candidate manifest maps
minigbm, frameworks/native, hardware/interfaces, build/make, build/soong,
build/blueprint, and prebuilts/go/linux-x86 to specific commits. Each commit
was verified against a local Git checkout and the superproject tree, and the projects were fetched unchanged
to the external workspace. These checkouts use about 1.2 GiB, dominated by
the pinned Go prebuilt. They are an internally consistent **partial** QPR2
source snapshot, not the source tree that produced the older SDK image.
The Go prebuilt is used only by AOSP's Soong microfactory during build
bootstrap. AaaS runtime and host transport do not depend on Go.

The SDK image contains many runtime shared libraries required by minigbm,
including allocator-V2-ndk, libbinder_ndk, libdrm, libdmabufheap, libsync,
and libgralloctypes. It does not contain minigbm's own libraries. Their
build requires Soong and platform headers; `libarect` is provided by the
pinned frameworks/native checkout, while Mapper 5 provider headers come
from the pinned hardware/interfaces checkout. Presence of runtime `.so`
files does not supply matching build headers or prove ABI compatibility.

```sh
export AAAS_WORKSPACE=/run/media/mrkus/Homework/aaas-workspace
python3 scripts/probe_android_graphics_build.py \
  --workspace "$AAAS_WORKSPACE" --prepare-only
python3 scripts/probe_android_graphics_build.py \
  --workspace "$AAAS_WORKSPACE"
```

The second command exited 1 after Soong's microfactory started. Its first
unresolved dependency is `external/golang-protobuf/proto`, required while
building `android/soong/cmd/soong_ui`. The full output and live budget samples
remain in `$AAAS_WORKSPACE/logs/graphics-build-probe.log` and
`graphics-build-budget.jsonl`. No minigbm object or binary was produced.
This establishes that the selected modules cannot be built from the seven
project partial tree. Resolving one Go package alone would not prove the
remaining Soong and Android dependency closure; a locked, compatible build
graph is required before a meaningful allocator/mapper build attempt.

The original `system.raw.img` was mounted read-only with `guestmount` and
unmounted without modification. Its stock SurfaceFlinger SHA-256 is
`a6d1ddc34b15c5841ac7e89fd57e6210b718013cf4888cecb9c397f858d64848`;
its stock `libbinder.so` SHA-256 is
`7f355db5308449a1d5015aeedf73ce33557bb5eec0c49f8930fbc20927da06f2`.
The latter differs from the patched library in the diagnostic rootfs. The
raw LP partitions remain the clean read-only baseline; no new rootfs copy was
created.

## Installation boundary

Current container runners contain fixed user paths, subuid ranges, cgroup
paths, Ranchu boot properties, and a global `LD_PRELOAD`. Several diagnostic
runners return exit 0 even when the Android process fails. They are not an
installer. An installable runtime needs capability detection, configurable
paths, per-distribution prerequisites, and fail-closed checks for Binder,
namespaces, cgroups, security policy, and the graphics stack. No host-wide
security setting should be weakened by setup or runtime scripts.

## Reconstructed-rootfs security gate (2026-11-08)

The retained Android 16 SDK archive was re-read and verified against the
recorded package size and SHA-1; its locally measured SHA-256 also matches the
manifest. The SHA-256 is local evidence, not a Google-published digest. This
validates the input archive only, not a runnable or secure AaaS image.

A fresh read-only comparison of `rootfs_m1b1` against the extracted `system`,
`system_ext`, and `vendor` partitions found 16 changed critical files, one
unchanged critical file (`surfaceflinger`), two `libselinux_shim.so` overlays,
and a modified SwiftShader checkout with 11 worktree entries (10 tracked
changes and one untracked backup). The exact original/current hashes and
classification for each finding are in
[`android16-diagnostic-rootfs-audit.json`](../../manifests/android16-diagnostic-rootfs-audit.json).
All 16 critical changes remain `UNRESOLVED`: the diagnostic source image
shows their outputs, but no reviewed source patch/build recipe establishes
their provenance or security behavior. The diagnostic rootfs is not a
reconstruction input.

The two SELinux shim overlays are an explicit security failure. The source in
`experiments/m1b/shim_selinux.c` returns success for `selinux_check_access`,
policy-loading/status calls, and context/label operations, fabricates SELinux
contexts, and alters Binder flags. It cannot be included in a reconstructed
runtime for third-party applications. The current host kernel's
`/sys/kernel/security/lsm` reports `capability,landlock,lockdown,yama,bpf`;
`/sys/fs/selinux/load` and `/sys/fs/selinux/enforce` are absent. AOSP's SELinux
bring-up requires a kernel built with SELinux support and Android init loading
policy into the kernel; see the [AOSP SELinux implementation
guide](https://source.android.com/docs/security/features/selinux/implement)
and [policy validation guidance](https://source.android.com/docs/security/features/selinux/validate).
This shared-kernel rootless session therefore cannot establish an independent
Android enforcing policy on this host. No SELinux enforcement or app-domain
isolation claim is made for the diagnostic runtime.

The read-only APEX audit parsed 47 package records, found no active claims,
and reports `activation_verified: false`. The diagnostic `/system/bin/apexd`
wrapper sets `apexd.status` properties and exits successfully for bootstrap
requests; that is not package verification, mount activation, or linker
namespace setup. APEX activation remains unresolved. No APEX library is copied
into a new rootfs as a substitute for activation.

The profile inspector now reports known SELinux bypass artifacts and preload
references. It labels enforcement `UNVERIFIED` even when no known shim is
found, because static image inspection cannot prove kernel policy state. The
CLI requires explicit verified enforcement before an image can be considered
ready. The Android 16 profile remains `automatically_installable: false`.

The two missing extracted comparison inputs (`system_ext` and `vendor`) were
recreated from the retained `tmp/system.img` with
`scripts/extract_super_partitions.py`; the old rootfs and userdata were not
modified. Current storage still has limited headroom under the workspace
ceiling. A complete 1,015-project Android source checkout and platform build
was not started: the repository has no resolved full source lock, and the
documented graphics-source probe previously stopped at an incomplete Soong
dependency graph. The independent secure rootfs and live M2/M3/M4 acceptance
remain open.

The profile inspector returned `compatibility: MATCH` but
`provenance: UNVERIFIED`, `security: BYPASS_DETECTED`,
`enforcement: UNVERIFIED`, and `provisionable: false` for the diagnostic
rootfs. With the configured workspace enrolled, both `aaas verify` and
`aaas start` exited 2; `start` refused before launching a session. No fresh
Android session was started. The full Python suite passed 423 tests with one
existing skip; the focused profile tests passed six. Python compilation, JSON
validation, and `git diff --check` passed.

The re-extracted `system_ext` and `vendor` comparison images occupy 318,361,600
bytes. Workspace guard accounting after extraction was 74,472,550,400 bytes
used against an 85,899,345,920-byte ceiling; filesystem availability was
43,698,237,440 bytes against a 21,474,836,480-byte reserve. Health remains
`HEALTHY_FOR_CONTROLLED_TESTING`; historical device incidents are retained.

## Rootless security decision and QPR2 graphics probe (2026-11-08)

The shared-kernel security decision is recorded in
[`rootless-android-architecture.md`](security/rootless-android-architecture.md).
The runtime keeps its rootless container design, but no experimental launch path
is enabled: host namespaces and Android framework permissions do not establish
SELinux equivalence, and the diagnostic rootfs has not been shown to work
without its authorization shims. The current profile is explicitly
`DIAGNOSTIC_LEGACY`; CLI readiness now additionally requires a
`SECURITY_VALIDATED` or `DISTRIBUTABLE` classification. Neither label can be
inferred from static files.

The graphics source probe recovered from a prior mountpoint change by replacing
only verified-generated dangling source links. The pinned QPR2 source snapshot
was extended with `kernel/configs` revision
`82c305fe2a7af49cbe9928e9b2fe1416f7810a41` and `system/sepolicy` revision
`43e4494a5a78317819dcc2766a11927c12ef3dfd`, resolved from superproject
`cc66c82349f536b77341e13862a548c01b048963`. Soong bootstrap then completed,
but module discovery first failed with unrecognized `hidl_interface`,
`hidl_package_root`, `aidl_interface`, and `xsd_config` types. The resolver now
maps these types to their AOSP plugin projects, fetched at exact superproject
revisions: `system/tools/hidl`
`9ea202c0fba585c2884a6bb2b1ba2dab46e98a8f`, `system/tools/aidl`
`3747384b876442e7ea0c355fe5adc75b29362833`, and `system/tools/xsdc`
`ef55c63066afcba5fd8781c2b056ccbe4c6ce687`. On retry those parser errors
disappeared. Soong then reported undefined platform modules across the partial
graph, including `llvm-build-host-tools-defaults`,
`libvintf_static_user_defaults`, `latest_android_media_audio_common_types_import_interface`,
and test defaults. The build exited 1 before compiling minigbm; no allocator
or mapper artifact was produced or installed. Expanding to a complete Android
source checkout is not safe within the workspace's remaining 10 GiB quota
headroom. This QPR2 graph also does not match the SDK image's earlier build ABI
and cannot be overlaid onto it without a matched build and compatibility
evidence.

Added tests preserve existing graphics resolver/probe assertions, cover repair
of stale generated links, and require source projects to be copied for Soong
module discovery while keeping large prebuilts linked. Profile tests now
validate trust-classification values, and the production `verify` readiness
predicate rejects experimental classifications. No Android session was
started. Workspace health remains accepted by the existing guard; the current
mount is ext4 UUID `094120c3-e1f8-4a61-a95a-c347ecb711d1`, with 75,820,453,888
bytes accounted against the 85,899,345,920-byte workspace ceiling and
42,350,333,952 bytes free. No matching new kernel storage errors were observed
in the post-build journal window. The build output remains a bounded diagnostic
cache in the workspace and is not a runtime artifact.

## Fresh source-image rootfs assembly (2026-11-08)

`scripts/assemble_android_rootfs.py` now assembles an independent candidate
from the retained `x86_64-36_r02.zip`. It verifies the archive size, recorded
SHA-1, and locally measured SHA-256; verifies each required logical partition
against the source super-image extents; exports and hashes `system`,
`system_ext`, `product`, `vendor`, and `system_dlkm`; materializes numeric
ownership in a mapped user namespace; unpacks the SDK ramdisk; and writes a
machine-readable inventory and manifest. It does not read `rootfs_m1b1` or
include Android userdata.

The first candidate has 4,347 inventory entries, 1,621,372,225 logical
partition-file bytes, and 2,393,317,376 allocated bytes. The 16 original
critical-file hashes match the clean SDK partitions. SELinux labels are kept
in the retained source partition tarballs, but are not materialized as host
SELinux xattrs. The rootfs candidate is `ASSEMBLED_INCOMPLETE`, not activated,
and not provisionable.

Historical work is summarized in
[`android16-reconstruction-transformations.json`](../manifests/android16-reconstruction-transformations.json).
M1D evidence establishes that the diagnostic `vdc` is a broken exit-0 stub;
the correct runtime behavior uses the original verified `vdc` in a read-only
session overlay. The diagnostic `apexd` wrapper fabricates status properties
and is excluded. The remaining critical binary/init transformations are not
reconstructed and must not be copied. Both SELinux success shims and the
locally modified SwiftShader source are excluded. See the [assembly
procedure](android-rootfs-reconstruction.md) and its structured
[`result`](../results/m6/android16-rootfs-assembly-2026-11-08.json).

Static profile inspection reports the candidate's Android 16 build identity
as matching, its base assembly provenance as verified, and its SELinux
enforcement as unverified. The candidate remains blocked from runtime use.
No APEX activation, graphics, Native Bridge, audio, desktop integration, or
live Android boot is claimed.
