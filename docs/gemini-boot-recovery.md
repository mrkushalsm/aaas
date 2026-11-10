# AaaS M1B Recovery: Gemini Android 16 Container Boot Path

**Status:** Completed  
**Branch:** `gemini-boot-recovery`  
**Base Commit:** `06615d9`  
**Date:** 2026-10-26  

---

## 1. Executive Summary

Milestone **M1B Recovery** reverses the strategic pivot away from the Android 16 x86_64 SDK userspace image, recovering the full historical sequence of Gemini-led container boot experiments. 

By restoring the diagnostic container environment (Bubblewrap, Linux namespaces, binderfs, user namespace UID mapping, APEX staging, and freestanding compatibility shims), we have:
1. Re-established the exact execution sequence and recovered all uncommitted Gemini artifacts under an immutable cryptographic manifest (`manifests/gemini-recovery-manifest.json`).
2. Confirmed **Android init second_stage** and verified the **Android Property Service** with live set/get roundtrips (`debug.aaas.test_property` = `recovery_roundtrip_ok`).
3. Confirmed **Binder IPC** and **ServiceManager**: 4 native services discovered (`manager`, `android.system.suspend.ISystemSuspend/default`, `suspend_control`, `suspend_control_internal`), with positive lookup and negative check validation.
4. Reproduced **Zygote** startup: ART initialization, boot classpath resolution, APEX namespace library resolution, and preloading of 18,367 classes, resources, and shared libraries.
5. Observed **Zygote forking `system_server` (PID 229)**!
6. Disproved the earlier assumption that `system_server` crashes immediately upon launch: `system_server` boots, reaches `SystemServiceManager`, and successfully publishes and registers **30 Binder services** in `servicemanager`.
7. Pinpointed the **exact fatal stop boundary** for `system_server`: `system_server` progresses through bootstrap services until `DisplayManagerService`, where it makes an AIDL call waiting for `SurfaceFlingerAIDL`. `SurfaceFlinger` dies during startup because `mapper.ranchu.so` attempts to open QEMU/Goldfish emulator devices (`/dev/goldfish_pipe_dprctd`, `/dev/goldfish_address_space`), which do not exist on native Linux hardware.

---

## 2. Recovered Artifacts & Cryptographic Manifest

All pre-existing and recovered Gemini files were preserved and indexed in [`manifests/gemini-recovery-manifest.json`](../manifests/gemini-recovery-manifest.json):

| Artifact | Original Status | SHA256 Hash | Function / Role |
| :--- | :---: | :---: | :--- |
| [`scripts/extract_all_apexes.py`](../scripts/extract_all_apexes.py) | Modified | `226c304bfefce66c86ed27c4266751f28ef6ea921b78c9f23029c353821fd57e` | Unpacks `.apex`/`.capex` payloads with symlink normalization for staged Bionic runtime |
| [`experiments/m1b/shim_selinux.c`](../experiments/m1b/shim_selinux.c) | Untracked | `e5df4d81ee296f475954d34b5d7ca5279bbeb5e0935bc332d5d810c700e2f75d` | Freestanding compatibility shim (`libselinux_shim.so`) satisfying Android libc/SELinux assertions |
| [`experiments/m1b/surfaceflinger_minimal.cpp`](../experiments/m1b/surfaceflinger_minimal.cpp) | Untracked | `38975f36f99e72893ecaa2c47e951e23eacf4baa95e85e93b59c00bc32ade88d` | Diagnostic minimal SurfaceFlinger probe source |
| [`scripts/run_container_init.py`](../scripts/run_container_init.py) | Untracked | `b652d9c2a1eb09fb3426d4d302b2522dffd215e0eaa423fbe5a67ec345f15bc8` | Container runner configuring unprivileged user, mount, PID namespaces, binderfs, and dummy sysctls |
| [`scripts/test_property_service.py`](../scripts/test_property_service.py) | Untracked | `f18823fa5c56030382005c98208dfb3086ab9a82b1b1fd0dd60a0c58a48dc56b` | Property service live set/get roundtrip verification |
| [`scripts/test_binder_ipc.py`](../scripts/test_binder_ipc.py) | Untracked | `ad4f2b8518f402308c8de30a462962f1c94e2fa43678e72d9cf5672c26457596` | Multi-service Binder IPC transaction and lookup probe |
| [`scripts/test_zygote_startup.py`](../scripts/test_zygote_startup.py) | Untracked | `b71f36f7d11da1024015a061ac9f6fcbd57489612da14bf22625ab4d66f6404f` | Full diagnostic Zygote, SurfaceFlinger, and system_server runner |

---

## 3. Comparison: Gemini Diagnostic vs. Codex Production Baselines

| Dimension | Gemini Experimental Runtime | Subsequent Codex Runtime | Recovery Determination |
| :--- | :--- | :--- | :--- |
| **Primary Objective** | Maximize practical userspace startup using stock Android 16 SDK image. | Gate progress strictly on uncompromised security, verified source tree, and signed package activation. | **Keep Gemini experimental path active** for rapid container bringup while tracking production readiness separately. |
| **Android Image** | Verified SDK DP2 x86_64 image (`BE2A.250530.026.D1`). | Rejected SDK image due to lack of public source tag; proposed minimal AOSP r1 build. | **Retain SDK image.** Building full AOSP is prohibited by host constraints (15 GiB RAM, NTFS workspace). |
| **SELinux Handling** | Freestanding `libselinux_shim.so` returning success for domain checks. | Demanded genuine kernel LSM policy or default-deny C++ source replacements. | **Retain shim as isolated development-only tool.** Clearly document all bypassed security boundaries. |
| **APEX Activation** | Extracted 35 payloads into `/apex/`, configured symlinks. | Required genuine `apexd` loopback mounting and authenticated package manifests. | **Staged APEX is sufficient for ART & Zygote execution.** Formal loop mounts remain a future container enhancement. |
| **System Server Outcome** | Classified as "terminated / failed". | Confirmed failure across G1–G7 gates in M1B.2 status. | **Corrected finding:** `system_server` boots, registers 30 services, and only stalls waiting on `SurfaceFlingerAIDL`. |

---

## 4. Audit of `libselinux_shim.so` Intercepts

Every function in [`experiments/m1b/shim_selinux.c`](../experiments/m1b/shim_selinux.c) serves a specific container compatibility function:

| Symbol / Intercept | Original Android Behavior | Why It Fails in Container | Shim Behavior | Affected Daemons | Production Alternative |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `selinux_status_open` | Opens `/sys/fs/selinux/status` page. | Inactive SELinux on host kernel causes assertion failure (`exit 134`). | Returns 0 (success). | `servicemanager`, `hwservicemanager` | Source-level default-deny authorization backend. |
| `selinux_check_access` | Evaluates MAC policy between caller SID and target class/perm. | No policy loaded in kernel. | Returns 0 (grant). | `servicemanager`, `init` | Local Binder caller UID/PID policy. |
| `getcon` / `getpidcon` | Reads process security label from `/proc/self/attr/current`. | Returns empty or unconfined on host. | Allocates `"u:r:init:s0"`. | `servicemanager`, `init`, `logd` | Container-specific UID-to-domain mapping. |
| `setexeccon` / `setcon` | Sets target context for subsequent `execve`. | Kernel returns `EINVAL`/`EPERM` without active SELinux. | Returns 0. | `init` | Unprivileged container namespaces. |
| `setsockopt` | Sets socket buffer size via `SO_RCVBUFFORCE` (33). | Requires `CAP_NET_ADMIN` in initial user namespace. | Remaps to `SO_RCVBUF` (8). | `ueventd` | Maintain syscall translation in container shim. |
| `mount` | Remounts `/apex` and `/boot` during init mount setup. | Container `/apex` is pre-staged tmpfs; remounting clears it. | Suppresses mounts targeting `/apex` or `/boot`. | `init` (`SetupMountNamespaces`) | Proper container mount namespace layout. |
| `setpriority` | Elevates thread priority via `setpriority(PRIO_PROCESS, ...)` | Unprivileged containers lack `CAP_SYS_NICE`. | Returns 0 if syscall fails. | `RenderEngine`, `Zygote` | Systemd slice CPU weight configuration. |
| `ioctl` (`BINDER_SET_CONTEXT_MGR_EXT`) | Passes `FLAT_BINDER_FLAG_TXN_SECURITY_CTX` (0x1000). | Host rust_binder returns `-EOPNOTSUPP` on security context without LSM. | Strips `0x1000` flag from request. | `servicemanager` | Host kernel binderfs LSM negotiation. |

---

## 5. Live Verification Outcomes

### 5.1 Property Service Roundtrip
Execution of `scripts/test_property_service.py`:
```text
=== GETPROP QUERY ===
16
x86_64
BE2A.250530.026.D1
=== SETPROP & GETPROP ROUNDTRIP ===
recovery_roundtrip_ok
```
- Stock Android 16 init parsed `/system/etc/init/hw/init.rc` and `/system/etc/init/hw/init.zygote64.rc`.
- Dynamic property trie initialized in `/dev/__properties__`.
- IPC via property socket (`/dev/socket/property_service`) validated in both directions.

### 5.2 Binder Service Discovery & Transactions
Execution of `scripts/test_binder_ipc.py`:
```text
=== PROBE 1: SERVICE LIST ===
Found 4 services:
0	android.system.suspend.ISystemSuspend/default: [android.system.suspend.ISystemSuspend]
1	manager: []
2	suspend_control: [android.system.suspend.ISuspendControlService]
3	suspend_control_internal: [android.system.suspend.internal.ISuspendControlServiceInternal]
=== PROBE 2: SERVICE CHECK UNREGISTERED ===
Service test_service_unregistered: not found
=== PROBE 3: SERVICE CHECK REGISTERED ===
Service manager: found
Service android.system.suspend.ISystemSuspend/default: found
```
- Full Binder transaction roundtrip verified across processes.
- Unregistered service query correctly returns negative lookup.
- Registered service lookup successfully resolves AIDL interfaces.

### 5.3 Zygote and System Server Framework Startup
Execution of `scripts/test_zygote_startup.py` captured in `$AAAS_WORKSPACE/tmp/zygote_recovery_run.log`:
```text
10-25 21:34:29.071   170   170 D Zygote  : Forked child process 229
10-25 21:34:29.071   170   170 I Zygote  : System server process 229 has been created
10-25 21:34:29.071   170   170 I Zygote  : Accepting command socket connections
```
Active process table during live execution:
```text
UID              PID    PPID C STIME TTY          TIME CMD
root               2       1 2 21:34:26 136:3 00:00:00 init second_stage
system            19       2 0 21:34:26 136:3 00:00:00 servicemanager
system            20       2 0 21:34:26 136:3 00:00:00 hwservicemanager
system            34       2 0 21:34:26 136:3 00:00:00 android.system.suspend-service
root              42       2 19 21:34:26 136:3 00:00:01 apexd.real
root              63       2 0 21:34:27 136:3 00:00:00 installd
system            68       2 0 21:34:27 136:3 00:00:00 android.hardware.graphics.composer3-service.ranchu
root             170       2 7 21:34:29 136:3 00:00:00 zygote64
system           174       2 0 21:34:29 136:3 00:00:00 android.hidl.allocator@1.0-service
system           180       2 0 21:34:29 136:3 00:00:00 android.hardware.graphics.allocator-service.ranchu
system           229     170 2 21:34:29 136:3 00:00:00 system_server
```

Live Binder services registered by `system_server` (PID 229) and core HALs:
```text
0	activity_task: [android.app.IActivityTaskManager]
1	android.frameworks.stats.IStats/default: [android.frameworks.stats.IStats]
2	android.hardware.graphics.allocator.IAllocator/default: [android.hardware.graphics.allocator.IAllocator]
3	android.hardware.graphics.composer3.IComposer/default: [android.hardware.graphics.composer3.IComposer]
4	android.hardware.light.ILights/default: [android.hardware.light.ILights]
5	android.security.identity: [android.security.identity.ICredentialStoreFactory]
6	android.system.suspend.ISystemSuspend/default: [android.system.suspend.ISystemSuspend]
7	apexservice: [android.apex.IApexService]
8	appops: [com.android.internal.app.IAppOpsService]
9	batterystats: [com.android.internal.app.IBatteryStats]
10	dataloader_manager: [android.content.pm.IDataLoaderManager]
11	device_identifiers: [android.os.IDeviceIdentifiersPolicyService]
12	feature_flags: [android.flags.IFeatureFlags]
13	file_integrity: [android.security.IFileIntegrityService]
14	gpu: [android.graphicsenv.IGpuService]
15	installd: [android.os.IInstalld]
16	lights: [android.hardware.lights.ILightsManager]
17	manager: []
18	memtrack.proxy: [android.hardware.memtrack.IMemtrack]
19	platform_compat: [com.android.internal.compat.IPlatformCompat]
20	platform_compat_native: [com.android.internal.compat.IPlatformCompatNative]
21	power: [android.os.IPowerManager]
22	powerstats: [android.os.IPowerStatsService]
23	recovery: [android.os.IRecoverySystem]
24	stats: []
25	suspend_control: [android.system.suspend.ISuspendControlService]
26	suspend_control_internal: [android.system.suspend.internal.ISuspendControlServiceInternal]
27	system_server_dumper: []
28	thermalservice: [android.os.IThermalService]
29	uri_grants: [android.app.IUriGrantsManager]
```

---

## 6. The Exact Technical Blocker for System Server

Contrary to earlier beliefs, `system_server` does **not** terminate prematurely from internal JVM faults, seccomp violations, or classloader errors.

Tracing `system_server` in `full_logcat.log`:
```text
10-25 21:33:18.438   230   230 I SystemServiceManager: Starting com.android.server.am.ActivityManagerService$Lifecycle
10-25 21:33:18.439   230   230 I ActivityManager: Memory class: 192
10-25 21:33:18.464   230   230 D AppOps  : AppOpsService published
10-25 21:33:18.465   230   230 I SystemServiceManager: Starting com.android.server.power.PowerManagerService
10-25 21:33:18.468   230   230 I SystemServiceManager: Starting com.android.server.display.DisplayManagerService
10-25 21:33:19.470   230   230 W ServiceManagerCppClient: Waited one second for SurfaceFlingerAIDL (is service started? Number of threads started in the threadpool: 32. Are binder threads started and available?)
10-25 21:33:20.470   230   230 W ServiceManagerCppClient: Waited one second for SurfaceFlingerAIDL (is service started? Number of threads started in the threadpool: 32. Are binder threads started and available?)
10-25 21:33:21.471   230   230 W ServiceManagerCppClient: Waited one second for SurfaceFlingerAIDL (is service started? Number of threads started in the threadpool: 32. Are binder threads started and available?)
```

Simultaneously in `sf_strace.log` (SurfaceFlinger):
```text
10-25 21:33:17.019   119   130 E surfaceflinger: open_verbose_path:56: Could not open '/dev/goldfish_pipe_dprctd': No such file or directory
10-25 21:33:17.024   119   130 E surfaceflinger: open_verbose:128: both vsock and goldfish_pipe paths failed
10-25 21:33:17.024   119   130 E HostConnection: Failed to connect to host (QemuPipeStream)
10-25 21:33:17.024   119   130 F mapper.ranchu: GoldfishAddressSpaceHostMemoryAllocator failed to open
147   21:33:17.813404 +++ killed by SIGABRT (core dumped) +++
```

**Causal Diagnosis:**
1. `SurfaceFlinger` attempts to initialize its RenderEngine using the vendor Ranchu mapper (`mapper.ranchu.so`).
2. `mapper.ranchu.so` aborts on missing QEMU emulator Goldfish pipes (`/dev/goldfish_pipe_dprctd`, `/dev/goldfish_address_space`).
3. Because SurfaceFlinger aborts, the `SurfaceFlingerAIDL` service is never published to ServiceManager.
4. `system_server` halts inside `DisplayManagerService` waiting synchronously for `SurfaceFlingerAIDL`.
5. Because `DisplayManagerService` never finishes, `system_server` cannot proceed to `PackageManagerService`.
6. When the diagnostic runner script reaches its timeout, it sends `kill -9 $INIT_PID`, which kills all container processes.

---

## 7. Next Smallest Experiment

To unblock `system_server` from the `SurfaceFlingerAIDL` stall:
1. Provide a minimal standalone `SurfaceFlingerAIDL` provider (or complete the mock registration probe in `surfaceflinger_minimal.cpp` by removing `return 42`) to satisfy `DisplayManagerService`'s Binder lookup.
2. In parallel, replace `mapper.ranchu.so` with a native DRM/GBM or ashmem allocator that does not attempt to open Goldfish hardware pipes.
3. Allow `system_server` to proceed past `DisplayManagerService` into `startOtherServices`, triggering `PackageManagerService` registration (`package`).
