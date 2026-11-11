# M1B.4: source-coherent Android runtime decision

**Decision milestone: pass. Android runtime boot: not attempted and not passed.**
This decision selects a source graph and an implementation path. It does not
claim that the present laptop can build or securely boot a complete Android
16 system.

## Verified Android 16 source baseline

The primary source baseline is AOSP `android-16.0.0_r1`, resolved from the
official `platform/manifest` tag. Its peeled manifest commit is
`2e764235335a27ee8cc8efc16baef4c0f6a5b3fe`; the manifest file SHA-256
is `b84e9005591ec5b224c1bc65cd8b5908956c1ffc099b0b8ce75830e6e05e8732`.
It explicitly sets `refs/tags/android-16.0.0_r1` as the default project
revision and declares the same superproject ref. The selected 16 project
tags were resolved individually to immutable commits in
`manifests/android16-r1-subset.json`. The lock covers:

| Runtime concern | Pinned project paths |
| --- | --- |
| init, properties, cgroups, Binder setup | `system/core` |
| ServiceManager, SurfaceFlinger, Binder | `frameworks/native` |
| Framework services and APIs | `frameworks/base` |
| ART and Bionic | `art`, `bionic` |
| APEX activation and policy | `system/apex`, `system/sepolicy` |
| Composer3 interface and gralloc candidate | `hardware/interfaces`, `external/minigbm` |
| Build graph and tools | `build/make`, `build/blueprint`, `build/release`, `build/soong`, `external/protobuf`, `prebuilts/clang/host/linux-x86`, `prebuilts/go/linux-x86` |

The official manifest tags `android-16.0.0_r1` through `r4` exist; `r1` is
the chosen fixed baseline. This is a **component inventory**, not a complete
minimal-product dependency closure. The manifest has many other projects;
the subset cannot be passed to Soong as a complete Android tree. The
published SDK emulator image has a different `BE2A.250530.026.D1` build ID
and is not assumed binary-compatible. The QPR2 source checkouts remain a
separate exploratory graph. No r1 binary was installed into the SDK image.

## Controlled source-build evidence

`scripts/probe_android16_apex_schema.py` fetches
`system/apex/proto/apex_manifest.proto` by the pinned r1 commit and verifies
its SHA-256 before compiling generated C++ with host `protoc` and `clang++`.
The resulting **host-only** parser correctly read the runtime and ART
manifests from the diagnostic rootfs. The retained report is
`results/m1b4/apex-schema-probe.json` and generated code/binary are under
`$AAAS_WORKSPACE/m1b4/apex-proto/`.

| Measurement | Result |
| --- | --- |
| Source | `system/apex` `9921a73777f97def1d8851dd0a1529f1c45bcc72` |
| Source schema SHA-256 | `e9505454f5fa759c6364e8680542f48b219f1b57d394a63deadfcfc6e8268ce7` |
| Toolchain | `clang++ 23.1.1`, `protoc 36.1`, host protobuf `36.1.0` |
| Compile | exit 0, 3.236 s, observed child peak RSS 229,484 KiB |
| Build files | 206,560 bytes |
| Linkage | host `libprotobuf.so.36.1.0`, Abseil libraries, glibc, libstdc++ |
| Parsed samples | runtime version 1; ART version 360499999 |

This establishes that a small pinned AOSP interface can be built and used as
a host inspection tool. It does **not** establish target Bionic linkage,
ServiceManager or `apexd` build closure, Android ABI compatibility, or full
product feasibility. The earlier bounded QPR2 Soong probe stopped at missing
global Blueprint providers before reaching minigbm compilation. That failure
is retained at `$AAAS_WORKSPACE/logs/graphics-build-probe-20261025T204150197637Z.log`.
No r1 Soong build was claimed.

The external workspace is NTFS3 (`nosuid,nodev`) and does not support sparse
files or reflinks. It can hold downloads and small host tools; a direct AOSP
product build needs a suitable Linux filesystem. The enforced workspace
ceiling is 80 GiB with 20 GiB free reserve. At the decision point it used
about 14.47 GB. The host has 15 GiB RAM, with swap nearly full during this
investigation. Google's current AOSP workstation guidance specifies at least
400 GB free and 64 GB RAM for checkout and build. A deliberately reduced
product could be smaller, but no measured closure demonstrates that it fits
80 GiB and 15 GiB RAM. Therefore a complete local product build is **not
authorized by current measurements**. Use a properly provisioned isolated
builder, or measure a complete pruned graph and resource use before changing
the local budget.

## Container image candidates and security

| Candidate | Source/ABI and framework | APEX, init, graphics | Isolation and decision |
| --- | --- | --- | --- |
| Android 16 SDK emulator image | Verified archive, but no matching public source tag; diagnostic framework never reached readiness | Stock `apexd` needs loop activation; Ranchu mapper/HWC need Goldfish devices; init expects SELinux and legacy task profiles | Reject as runtime baseline. Keep as immutable comparison artifact. |
| Minimal AOSP r1 x86_64 product | Coherent pinned source is available; product graph and boot are unbuilt | Can select native minigbm pair and Composer3 v4 in one graph; APEX and init still require explicit container design | **Primary strategy.** Build only on a qualified builder after closure and security gates. |
| Redroid Android 16 amd64 | OCI image exists at per-platform digest `sha256:18eaf7058f1fbe17378106daa9c02936a7d293e71325db432462086854d9e9f0`; build-source correspondence and Composer3 ABI not verified | Container-oriented init changes and image already exist; APEX state and HAL must be inspected from the image | **Conditional fallback/reference.** Published quick start uses `--privileged`; r2 patch set bypasses SELinux and minijail seccomp. Cannot run as an AaaS security baseline without replacing and validating those choices. |
| Waydroid published image | Official project currently describes its minimal image as Android 13/LineageOS 20; no official Android 16 x86_64 image was verified | Has a container graphics HAL but its published `lineage-20` source does not prove Composer3 v4 compatibility | Benchmark/reference only for this Android 16 milestone. |

The Redroid image tag is mutable; the digest above is the observed amd64
platform manifest from `docker manifest inspect`, not a pulled or audited
filesystem. Its Android 16 source patch repository at commit
`a5c70c0dd89c12b5027c902ab4182f31d38f3bb7` contains explicit
`ignore-selinux`, `disable-seccomp`, Binder SID fabrication, and init bypass
patches. We did not apply them. The Redroid platform manifest branch head
`f12358e83fef301eee116d7e1d3d4f54e75ec237` was observed, but no
evidence connects that exact commit to the published digest. A container
image alone cannot establish source coherence or secure confinement.

The host has usable binderfs in a user namespace and scoped cgroup v2 CPU,
memory, and PID delegation. Its active LSM list is
`capability,landlock,lockdown,yama,bpf`; SELinux is compiled but inactive.
Android SELinux policy cannot be made active only inside an ordinary user
namespace. Stock ServiceManager fails at `selinux_status_open`; stock init
expects transitions and labeling. A default-deny development ServiceManager
would restrict one Binder registry, but would not enforce Android process,
file, socket, property, and service domains. The required host-side
substitute confinement remains unproved. We will not disable host security,
run a privileged container, or execute untrusted APKs under a partial policy.

## Next implementation gates

1. **Graph and builder:** define a minimal r1 x86_64 product including init,
   ServiceManager, ART, Bionic, APEX, framework services, minigbm allocator/
   mapper, and Composer3 v4. Generate a complete immutable `repo` lock and
   measure source/build sizes and peak memory on a qualified isolated builder.
   Stop if the product graph or resource estimate exceeds the builder budget.
2. **Security design:** enumerate every Android SELinux dependency in the
   selected product. Demonstrate an unprivileged LXC/user-namespace device,
   mount, UID, Binder, cgroup, and host LSM policy before starting framework
   services. Stop if equivalent confinement cannot be justified for trusted
   tests; untrusted APKs remain prohibited.
3. **APEX activation:** with signed packages from the *same* build, prove
   package verification, correct versioned mounts, linker namespaces, and
   cleanup in an isolated mount namespace. Stop on loop/device or permission
   failure; do not relabel extraction as activation.
4. **Service management:** build the smallest r1 ServiceManager variant with
   an explicitly selected default-deny development backend and test real
   Binder add/find/list denial, UID mapping, death, and restart. Keep stock
   behavior as the control. This is only one security gate.
5. **Framework and graphics:** after the preceding gates, verify init,
   Zygote, system_server, PackageManager and ActivityManager readiness, then
   allocator/mapper import and Composer3/Wayland presentation with real fence
   semantics. Process existence and compilation alone do not pass.

## Reproduce this decision's local checks

```sh
export AAAS_WORKSPACE=$AAAS_WORKSPACE
python3 scripts/android_workspace.py --workspace "$AAAS_WORKSPACE" check
python3 scripts/lock_android16_subset.py --output manifests/android16-r1-subset.json
python3 scripts/probe_android16_apex_schema.py \
  --workspace "$AAAS_WORKSPACE" \
  --output results/m1b4/apex-schema-probe.json
python3 -m unittest discover -s tests -v
```

The lock command requires network and can be compared with the committed
lock; it must not silently update it during a build. The probe uses an
already present diagnostic APEX manifest as parser input, without running
the diagnostic Android runtime. Neither command modifies the SDK image,
host security configuration, or pre-existing Gemini files.

## Primary sources

- [AOSP build numbers](https://source.android.com/docs/setup/reference/build-numbers) and [workstation requirements](https://source.android.com/docs/setup/start/requirements).
- [AOSP r1 manifest](https://android.googlesource.com/platform/manifest/+/2e764235335a27ee8cc8efc16baef4c0f6a5b3fe/default.xml).
- [Redroid documentation](https://github.com/remote-android/redroid-doc) and [Android 16 r2 patch tree](https://github.com/remote-android/redroid-patches/tree/a5c70c0dd89c12b5027c902ab4182f31d38f3bb7/android-16.0.0_r2).
- [Waydroid project](https://github.com/waydroid/waydroid) and [Waydroid HAL](https://github.com/waydroid/android_hardware_waydroid).
