# Android 16 shared-kernel boot boundary (2026-10-26)

The earlier diagnostic run reached real Bionic, ART, and Zygote code, but its
rootfs contains patched Android binaries, service-replacing scripts, and a
preload library that reports success for security and synchronization-related
operations. Keep that run as evidence of component behavior, not as an
installable boot baseline. The current retained `test_zygote_out.txt` shows
Zygote startup and subsequent `system_server` termination. A later complete
`system_server` bootstrap trace described in the handoff is not retained in
the current results, so that exact stage is not independently verified here.

## Stock, read-only baseline

The verified SDK `system.raw.img` and its own `com.android.runtime.apex` were
mounted read-only with libguestfs. No extracted rootfs copy, binary edit,
`LD_PRELOAD`, fake Binder driver, or host security change was involved.

```sh
export AAAS_WORKSPACE=$AAAS_WORKSPACE
python3 scripts/probe_clean_bionic.py --workspace "$AAAS_WORKSPACE"
AAAS_WORKSPACE="$AAAS_WORKSPACE" scripts/probe_clean_servicemanager.sh
```

The Bionic probe exited 0: stock `/system/bin/sh` ran stock toybox and printed
`Linux` and the namespace UID. Its runtime APEX payload SHA-256 is
`0040cc4a7e4005e3f2efe43da12530a52b4a4ab5cf05d68e93395c87de9f12cb`.
The service-manager probe mounted the host's real binderfs inside an
unprivileged user namespace, created a Binder node via `BINDER_CTL_ADD`, and
ran the stock `/system/bin/servicemanager` with stock libraries. It exited
134. Its captured Android log states:

```text
servicemanager: Starting sm instance on /dev/binder
servicemanager: Check failed: selinux_status_open(true ) >= 0
```

The exact logs are retained at `$AAAS_WORKSPACE/logs/clean-bionic-shell.log`,
`clean-servicemanager-probe.log`, and `clean-servicemanager-kmsg.log`.
The source image and APEX were unmounted after each run. The host kernel has
SELinux compiled (`CONFIG_SECURITY_SELINUX=y`) but its active LSM list is
`capability,landlock,lockdown,yama,bpf`; SELinux is not active. Android's
pinned upstream `frameworks/native/cmds/servicemanager/Access.cpp` checks
`selinux_status_open(true)` and a process context during construction. The
clean probe demonstrates this check is the first verified stock-service stop
on this host, after Binder opened successfully.

The separate kernel-only probe below created a disposable binderfs node in an
unprivileged user and mount namespace, then issued the same
`BINDER_SET_CONTEXT_MGR_EXT` request with
`FLAT_BINDER_FLAG_TXN_SECURITY_CTX` used by pinned AOSP `libbinder`:

```sh
python3 scripts/probe_binder_context_manager.py \
  | tee "$AAAS_WORKSPACE/logs/binder-context-manager-probe.json"
```

On this host it returned `{"accepted": true, "errno": null}`. The kernel
accepts the context-manager registration request despite inactive SELinux.
This does not prove that Binder transactions carry useful security labels or
that Android service access checks work. The probe mounts and unmounts its own
binderfs and does not alter Android files. Transaction security and caller
authorization still require separate tests.

## What can be retained from the diagnostic work

| Component | Diagnostic finding | Production direction |
| --- | --- | --- |
| Bionic and ART | Stock binaries execute and Zygote reached preload in the modified runtime. | Keep stock binaries; test from pristine partitions and signed APEX content. |
| Binder | Host binderfs works in a user namespace. | Keep the real kernel driver and Android Binder libraries; resolve security-context behavior explicitly. |
| APEX | The old wrapper set `apexd.status` without full activation. | Require genuine package activation and `apexservice`; no status-property substitute. |
| Vold and vdc | Scripts replaced real binaries in the diagnostic rootfs. | Use actual services or a purpose-built product configuration that omits them with verified dependency closure. |
| SurfaceFlinger | Stock binary is present, but Ranchu mapper needs Goldfish hardware. | Keep stock SurfaceFlinger; replace allocator/mapper and Composer3 with compatible upstream/source-built components. |
| SwiftShader | Local source edits return false Vulkan fence success. | Reject these edits; require real acquire/release fences and Android-compatible Vulkan driver behavior. |

## Architecture decision under test

The shared-kernel direct-namespace path cannot currently run this stock
Android image unchanged on this host: Binder is available but Android's
service manager requires an active SELinux interface. A user namespace does
not provide its own SELinux policy instance. Running the existing preload
shim would bypass Android's access checks; its success cannot count as a
secure or portable solution. No host LSM settings will be changed for this
experiment.

The next source-based path is a *purpose-built Android container product*
whose changes are explicit and reviewed at source level: define a substitute
service-access policy for hosts without Android SELinux and support real APEX
activation or a verified source-built alternative. The kernel accepts Binder's
security-context request, but caller-label behavior remains unverified. This is a security design decision,
not a compiler workaround. It must retain Linux namespace/cgroup isolation
and be tested against hostile app UIDs before an installer can rely on it.

LXC is the intended container manager for this path. It is available as a
distribution package but is not currently installed. The Binder probe already
uses the native kernel user/mount namespace and binderfs mechanisms that an
unprivileged LXC configuration would need; an LXC boot is not yet claimed.

## Minimal Android product gate

The intended product is a small Android compatibility runtime inside LXC,
using the host Linux kernel and the existing desktop compositor. The current
SDK image is a diagnostic source of stock components, not the final service
inventory. Keep Bionic, ART, Zygote, Binder service registration, the minimum
framework services needed to start an app, SurfaceFlinger, and only the HALs
those services demonstrably require. The Composer3 and gralloc path must use
the independent host graphics transport already under development.

Build the service list from source init declarations, VINTF entries, package
dependencies, and observed boot failures. For each included daemon or APEX,
record its consumer and a boot/app-launch test that fails when it is absent.
For each omitted component, record the evidence that no retained service
requires it. Start by evaluating telephony, media, camera, location, update,
emulator, and device-storage services for omission; their absence is a
hypothesis until dependency and runtime traces confirm it. Do not replace a
required service with a success-returning stub or alter a binary to remove
the dependency. An explicit source product configuration is the target.

The first runtime gates are: Zygote starts from pristine Bionic/ART; a genuine
service manager enforces a documented caller policy; the smallest viable
`system_server` set stays alive; a test app launches and renders through the
real graphics path. Passing an earlier gate does not imply the later ones.

A guest-kernel experiment could retain stock Android SELinux and APEX
semantics, but it is a different isolation architecture and is not adopted
here. The direct-namespace path remains the research target.

The Go prebuilt fetched for the separate Soong source-build probe is only an
upstream Android build toolchain. The AaaS runtime remains native/Linux and
does not require Go or Python services at runtime. Python and shell in this
repository orchestrate reproducible research probes.
