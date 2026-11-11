# M1B.2: Android 16 init and framework boot boundary

**Determination: fail / blocked at clean service management and APEX activation.**
The smallest practical shared-kernel runtime is still the target. The retained
Gemini rootfs is a diagnostic artifact, not a validated Android product.

## Runtime and host interfaces

The clean baseline uses the verified Android 16 SDK `system.raw.img` and its
own `com.android.runtime.apex`, mounted read-only by libguestfs. An unprivileged
user/mount/PID namespace exposes stock Bionic and a real binderfs device.
No VM, fake Binder, SELinux preload, or host security change is involved in
that baseline. The external NTFS3 disk remains guarded by
`scripts/android_workspace.py`; the main Git repository remains on the host
filesystem. LXC is intended for the eventual lifecycle, but is not installed
and an LXC boot has not been tested. It would use the same host kernel Binder,
cgroup, and LSM capabilities.

The diagnostic rootfs instead runs Android init with global `LD_PRELOAD` of
`libselinux_shim.so`, copied APEX payload trees, replaced services, and edited
binaries. Its logs demonstrate that real ART/Zygote code executed, not that
an installable or secure framework boot succeeded.

## Security review

The experimental shim returns success from `selinux_check_access`,
`setexeccon`, `setcon`, `setfilecon`, `selinux_android_setcontext`, and related
label operations. It supplies fabricated process/file contexts, suppresses
some `/apex` and `/boot` mounts, reports success for some priority/ashmem
operations, and strips `FLAT_BINDER_FLAG_TXN_SECURITY_CTX` from one Binder
ioctl. Thus it bypasses service find/add/list authorization, process-domain
transitions, file labeling, and parts of mount and buffer behavior. The
diagnostic runners pass it to init; children may inherit it unless their RC
service explicitly clears `LD_PRELOAD`. The exact per-process loaded-library
inventory was not retained. The source and affected runner commands are in
`experiments/m1b/shim_selinux.c`, `scripts/run_container_init.py`,
`scripts/test_property_service.py`, `scripts/test_binder_ipc.py`, and
`scripts/test_zygote_startup.py`. No additional bypass was added here.

The host kernel compiled SELinux but does not have it in its active LSM list.
The clean stock `servicemanager` opened real Binder, then exited 134 at
`selinux_status_open(true) >= 0`. A disposable kernel probe separately
confirmed that `BINDER_SET_CONTEXT_MGR_EXT` with the security-context flag is
accepted; it did not test caller labels or transactions. A user namespace
does not instantiate a new SELinux policy. A source-level service policy
adaptation would therefore require explicit authorization rules and hostile
UID tests. The permissive diagnostic shim cannot be used for untrusted apps.
The clean service-manager probe was rerun for M1B.2 and again exited 134;
its fresh logs are `$AAAS_WORKSPACE/logs/m1b2-clean-servicemanager-probe.log`
and `m1b2-clean-servicemanager-kmsg.log`. Read-only image mounts were cleaned
up afterward.

## Init, cgroups, properties, and lifecycle

`python3 scripts/probe_cgroup_delegation.py` ran in a transient
`systemd-run --user --scope -p Delegate=yes` scope. It received `cpu`,
`memory`, and `pids`, created a child cgroup, moved a process into it, and
removed the child and scope. Log:
`$AAAS_WORKSPACE/logs/cgroup-delegation-probe.json`. This proves limited
unprivileged cgroup v2 delegation. It does not satisfy the SDK image's
`/system/etc/cgroups.json` and task profiles, which also reference legacy
`/dev/blkio` and `/dev/cpuset` paths. The retained init log repeatedly shows
failed task-profile writes to those paths. No global cgroup mount or host
sysctl was changed. The diagnostic runners' fake proc files and setexeccon
success responses cannot count as native init compatibility.

The diagnostic init log shows a `property_service` socket and property
triggers. Its runner injected `apexd.status=activated` and other readiness
properties manually. The retained evidence does not show a clean set/get
round trip with access enforcement, so G1 is not passed. The runner terminates
init with `SIGKILL`; orderly restart and cleanup of Android services were not
validated.

## APEX and ART

`scripts/audit_m1b2_apex.py` found 35 extracted payload trees, 47 declared
APEX modules, zero marked active, and 48 log lines matching failed
loop-control activation (including summary lines). Both runtime and ART were
staged, neither was marked active. The exact audit is
`$AAAS_WORKSPACE/logs/m1b2-apex-audit.json`. The retained `apexd.real` log
reports failure to activate 47 packages because `/dev/loop-control` was
absent. `linkerconfig` output and Bionic/ART execution from staged paths do
not establish authenticated APEX activation. The extraction script also
normalizes symlinks in a modified, uncommitted version; extracted ownership,
labels, signature verification, versioned mount semantics, and dependency
activation have not been validated. Preserve signed source packages and
never publish the flattened diagnostic layout as the product format.

## Binder, Zygote, and framework gates

| Gate | Result | Evidence and remaining requirement |
| --- | --- | --- |
| G1 init/property service | **Fail** | Diagnostic init parsed RC and exposed a socket; clean property authorization/round trip absent. |
| G2 Binder services/transactions | **Fail** | Real binderfs and context-manager ioctl work; clean `servicemanager` aborts before a service registration/transaction test. |
| G3 runtime/APEX for ART | **Fail** | Stock Bionic runs and diagnostic ART loads; all declared APEX modules are inactive. |
| G4 Zygote operational | **Fail** | Diagnostic `ZygoteInit` completed preload; subsequent `system_server` spawn failed and a stable Zygote lifecycle was not verified. |
| G5 system_server operational | **Fail** | Retained run reports `system_server` termination; no stable readiness trace. |
| G6 package/activity responsive | **Fail** | No clean registration and command response from both services. |
| G7 restart/shutdown | **Fail** | Diagnostic scripts used forced termination; no orderly service recovery trace. |

The older `scripts/test_binder_ipc.py` checks a service list and an
*unregistered* name, not service registration, a transaction, death
notification, or permission denial. Its exit code cannot establish G2.
Likewise, process presence cannot establish G4 through G6. No third-party
APK was run.

## Composer3 feasibility

The pinned `hardware/interfaces` tree declares
`android.hardware.graphics.composer3` as a frozen VINTF-stable AIDL interface
with version 4 and an NDK backend. The SDK image contains
`android.hardware.graphics.composer3-V4-ndk.so`, `libbinder_ndk.so`, and
`libui.so`. These shared libraries do not supply the generated interface
headers or matched platform build graph needed to implement a vendor HAL.
No ordinary installed NDK headers for this HAL were found. The bounded Soong
probe reached global Blueprint dependency failures before minigbm or
Composer3 compilation; QPR2 source compatibility with the older SDK image
remains unverified. No Composer3 implementation was begun for M1B.2.

## Reproduction and next experiment

```sh
export AAAS_WORKSPACE=$AAAS_WORKSPACE
python3 scripts/android_workspace.py --workspace "$AAAS_WORKSPACE" check
python3 scripts/probe_clean_bionic.py --workspace "$AAAS_WORKSPACE"
AAAS_WORKSPACE="$AAAS_WORKSPACE" scripts/probe_clean_servicemanager.sh
python3 scripts/probe_binder_context_manager.py
python3 scripts/probe_cgroup_delegation.py
python3 scripts/audit_m1b2_apex.py \
  --rootfs "$AAAS_WORKSPACE/rootfs_m1b1" \
  --apex-log "$AAAS_WORKSPACE/tmp/kmsg_zygote_test.log"
python3 -m unittest discover -s tests -v
```

The service-manager command is expected to exit 134 and log the SELinux
assertion. The APEX audit is expected to report `activation_verified: false`.
M1B.2 cannot pass these gates on the current stock image and host without a
new, reviewed service-access design and an APEX activation design that works
in the selected isolation model. The smallest next experiment is a
source-level, **development-only** service-manager access policy with
default-deny rules and real Binder registration/denial tests, built from a
coherent Android source snapshot. In parallel, determine whether verified
APEX activation can be supported without privileged loop devices. Neither
change should be made by extending the preload shim or inventing successful
status properties.
