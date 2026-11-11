# AaaS M1B.1 Status: Android 16 Runtime Boot and Composer3 Integration Boundary

## 1. Executive Summary

Milestone **M1B.1** investigated whether the verified Android 16 (API 36, userdebug) x86_64 SDK image can serve as the foundation for a shared-kernel Android-as-a-Service (AaaS) container runtime, and audited the AIDL Composer3 v4 integration boundary.

All investigations were conducted strictly without building full AOSP, without virtual machines (direct namespaces/containers), without destructive host modifications, and respecting the external workspace budget at `$AAAS_WORKSPACE`.

### Key Outcomes
1. **Dynamic Partition Extraction**: Developed `scripts/extract_super_partitions.py` to carve out raw ext4 partitions (`system`, `vendor`, `product`, `system_ext`) and erofs (`system_dlkm`) from the LP super image without native Android tools or root privileges.
2. **APEX Architecture Discovery**: Identified that Android 16 moves all core Bionic libraries (`libc.so`, `libm.so`, `libdl.so`) and the ELF dynamic interpreter (`/system/bin/linker64`) into `/apex/com.android.runtime/`. Developed `scripts/extract_all_apexes.py` to unpack all 35 APEX/CAPEX packages, enabling standard Android binaries to execute directly on the Linux host kernel.
3. **Host Kernel Binder Verification**: Audited host Linux kernel 7.2.9: discovered `CONFIG_ANDROID_BINDER_IPC_RUST=y`, `CONFIG_ANDROID_BINDER_DEVICES=""`, and `binderfs` registered as `nodev binder`. Verified that unprivileged user namespaces can mount `binderfs` and dynamically instantiate `/dev/binder`, `/dev/hwbinder`, and `/dev/vndbinder` via `BINDER_CTL_ADD` (`0xc1086201`).
4. **Android Bionic & Shell Execution**: Successfully ran Android 16 `/system/bin/sh` and `toybox` (`Linux KushalSM-Laptop 7.2.9-arch1-1 x86_64 Toybox`) inside an unprivileged Bubblewrap (`bwrap`) container.
5. **ServiceManager & SELinux Assertion**: Identified that `servicemanager` crashes on host kernels lacking SELinux due to unconditional assertions in `android::Access::Access()` (`selinux_status_open()` and `getcon()`). Developed a freestanding `libselinux_shim.so` (zero dependencies) allowing Android 16 `servicemanager` to initialize and run continuously on the host kernel via binderfs.
6. **Init Second-Stage Parsing**: Tested Android 16 `/system/bin/init second_stage` with full subuid mapping (`mrkus:100000:65536`). Init parsed `/init.environ.rc`, `/system/etc/init/hw/init.zygote64.rc`, and all service definitions (`hwc3.rc`, `surfaceflinger.rc`, `servicemanager.rc`), revealing three concrete container blockers:
   - Cgroup setup (`SetupCgroups` requires container write access to cgroups v2).
   - SELinux domain transitions (`setexeccon` fails when SELinux is disabled).
   - Host sysctl restrictions (`/proc/sys/kernel/kptr_restrict` and `sysrq` are read-only in user namespaces).
7. **Composer3 Ranchu HAL Analysis**: Ran `/vendor/bin/hw/android.hardware.graphics.composer3-service.ranchu`. Verified AIDL v4 interface (`android.hardware.graphics.composer3-V4-ndk.so`). Binary successfully started and logged `RanchuHwc RanchuHWC (HWComposer3/HWC3) starting up...`. Confirmed that Ranchu HWC relies on QEMU/Goldfish emulator devices (`/dev/goldfish_sync`, `/dev/goldfish_pipe`).
8. **AaaS Composer3 Adaptation Architecture**: Formulated the architectural specification for a native, lightweight `aaas-composer3` HAL that replaces emulator pipes with AaaS `wire_v2` UNIX domain socket transport and DRM syncobj timeline explicit synchronization.

---

## 2. Image Provenance & Partition Structure

### 2.1 Artifact Provenance
- Source: Android 16 Developer Preview 2 SDK system image (`x86_64-36_r02.zip`).
- SHA1: `829c076e8ff448a336097ae25a355b495ba36e2c`.
- Build fingerprint: `Android/sdk_phone64_x86_64/emu64x:16/BE2A.250530.026.D1/13818094:userdebug/test-keys`.

### 2.2 LP Partition Layout (`super.img`)
Extracted using `scripts/extract_super_partitions.py` from LP metadata:
| Partition | Filesystem | Size (MiB) | Sector Offset | Target Type |
|---|---|---|---|---|
| `system` | ext4 | 912.4 | 2,048 | Linear (0) |
| `system_ext` | ext4 | 207.0 | 1,886,208 | Linear (0) |
| `product` | ext4 | 367.9 | 2,312,192 | Linear (0) |
| `vendor` | ext4 | 96.6 | 3,065,856 | Linear (0) |
| `system_dlkm` | erofs | 7.0 | 1,871,872 | Linear (0) |

### 2.3 The APEX Runtime Decoupling
In Android 16, system root symlinks:
```
/system/bin/linker64 -> /apex/com.android.runtime/bin/linker64
/system/lib64/libc.so -> /apex/com.android.runtime/lib64/bionic/libc.so
/system/lib64/libdl.so -> /apex/com.android.runtime/lib64/bionic/libdl.so
/system/lib64/libm.so  -> /apex/com.android.runtime/lib64/bionic/libm.so
```
Standard `apexd` activates packages by loopback mounting `apex_payload.img`. To operate cleanly in an unprivileged container without loop devices or root privileges, `scripts/extract_all_apexes.py` unpacks `apex_payload.img` directly into `/apex/<package_name>/`.

---

## 3. Host Kernel & IPC Audit

### 3.1 Kernel Binder Inspection
Host kernel config (`/proc/config.gz`):
```ini
# CONFIG_ANDROID_BINDER_IPC is not set
CONFIG_ANDROID_BINDER_IPC_RUST=y
CONFIG_ANDROID_BINDER_DEVICES=""
```
Filesystem support (`/proc/filesystems`):
```
nodev	binder
```
Because `CONFIG_ANDROID_BINDER_DEVICES` is empty, no static `/dev/binder` nodes exist at host boot. However, `binderfs` is active and can be mounted unprivileged in a user namespace:
```bash
mount -t binder binder /dev/binderfs
```
Dynamic device allocation is performed via `ioctl(fd, BINDER_CTL_ADD, &req)` with `_IOWR('b', 1, struct binderctl_num)` = `0xc1086201`:
- `/dev/binderfs/binder` (major 242, minor 1) -> `/dev/binder`
- `/dev/binderfs/hwbinder` (major 242, minor 2) -> `/dev/hwbinder`
- `/dev/binderfs/vndbinder` (major 242, minor 3) -> `/dev/vndbinder`

### 3.2 User Namespace UID Mapping
Host system `/etc/subuid` and `/etc/subgid` allocate `mrkus:100000:65536`.
Using `newuidmap` and `newgidmap`:
- Container UID 0 (root) -> Host UID 1000
- Container UIDs 1..65535 -> Host UIDs 100001..165535
This satisfies Android permission checks for `AID_SYSTEM` (1000), `AID_GRAPHICS` (1003), and `AID_SHELL` (2000), eliminating `fchown` `EINVAL` errors during early init.

---

## 4. Boot Milestone Progression & Findings

| Milestone | Target Component | Status | Findings / Blockers |
|---|---|---|---|
| M1 | Android Shell / Tooling | **VERIFIED** | `/system/bin/sh` and `toybox` execute directly on host kernel. |
| M2 | Binderfs IPC Infrastructure | **VERIFIED** | `binderfs` mounts in user namespace; `binder`, `hwbinder`, `vndbinder` allocated. |
| M3 | Property Service / Trie | **BLOCKED (Init)** | Init requires `/proc/sys/kernel/kptr_restrict` and Cgroup v2 access. |
| M4 | ServiceManager | **VERIFIED (with Shim)** | Runs continuously via `libselinux_shim.so` bypassing SELinux abort. |
| M5 | APEX Activation | **VERIFIED (Staged)** | Unpacked 35 APEX packages into `/apex/`, resolving `linker64` and Bionic. |
| M6 | Composer3 HAL (Ranchu) | **VERIFIED (Startup)** | Starts up, logs `RanchuHWC starting up...`; blocked on Ranchu QEMU pipe. |
| M7 | SurfaceFlinger | **BLOCKED** | Blocked on Property Service and native Composer3 / Gralloc HAL. |

### 4.1 ServiceManager SELinux Assertion
Disassembly of `android::Access::Access()` in `servicemanager`:
```asm
8545:  call 15600 <selinux_status_open@plt>
854a:  test %eax, %eax
854c:  js   8576 <__libc_init@plt-0xd04a>  ; Jumps to LOG(FATAL) if < 0
8551:  call 15640 <getcon@plt>
8556:  test %eax, %eax
8558:  jne  85d9 <__libc_init@plt-0xcfe7>  ; Jumps to LOG(FATAL) if != 0
```
On non-SELinux host kernels, `selinux_status_open(true)` fails, triggering `SIGABRT`. The freestanding `libselinux_shim.so` satisfies these symbols:
```c
int selinux_status_open(int fallback) { return 0; }
int getcon(char **con) { *con = "u:r:servicemanager:s0"; return 0; }
int selinux_check_access(...) { return 0; }
int selinux_status_updated(void) { return 0; }
```

---

## 5. Composer3 AIDL v4 Boundary & Adaptation Architecture

### 5.1 Ranchu HWC Analysis
The binary `/vendor/bin/hw/android.hardware.graphics.composer3-service.ranchu`:
- Implements `aidl::android::hardware::graphics::composer3::BnComposer` and `BnComposerClient`.
- Links to `android.hardware.graphics.composer3-V4-ndk.so` and `libOpenglSystemCommon.so`.
- Internally opens `/dev/goldfish_sync`, `/dev/goldfish_pipe_dprctd`, and `/dev/dri/card`.

### 5.2 AaaS Composer3 (`aaas-composer3`) Specification
Rather than running the Ranchu emulator HAL, AaaS requires a clean, lightweight Composer3 HAL daemon:

```
+-------------------------------------------------------------+
| Android Container User Space                                |
|                                                             |
|  [SurfaceFlinger]                                           |
|         | Binder IPC (android.hardware.graphics.composer3)  |
|         v                                                   |
|  [aaas-composer3 HAL]                                       |
|     - Implements BnComposer & BnComposerClient              |
|     - Imports DMA-BUF from Gralloc (native_handle_t)        |
|     - Connects to host via UNIX socket (/run/aaas/wire.sock)|
+---------|---------------------------------------------------+
          |
          | Wire Protocol v2 (MSG_SUBMIT_BUFFER_V2)
          | FDs: DMA-BUF FD, Acquire Syncobj FD
          v
+-------------------------------------------------------------+
| Host Environment (Wayland / KWin Session)                   |
|                                                             |
|  [AaaS Host Presenter (aaas-m1a1)]                          |
|     - Imports DMA-BUF -> wl_buffer (zwp_linux_dmabuf_v1)    |
|     - Attaches acquire point (wp_linux_drm_syncobj_v1)      |
|     - Submits frame to Wayland surface                      |
|     - Exports release syncobj timeline point back to client |
+-------------------------------------------------------------+
```

### 5.3 Implementation Steps for `aaas-composer3`
1. **AIDL Interface Implementation**:
   Implement `BnComposer::createClient()` returning a `BnComposerClient` instance.
2. **Buffer Registration**:
   `registerDisplay()` / `setClientTarget()`: extract DMA-BUF file descriptors from Gralloc `native_handle_t`.
3. **Frame Submission via Wire v2**:
   In `executeCommands()` (validate/present display):
   - Package layer composition or client target buffer.
   - Attach present/acquire fence FD from SurfaceFlinger.
   - Send `MSG_SUBMIT_BUFFER_V2` across the UNIX domain socket to `aaas-m1a1`.
   - Receive `MSG_RELEASE_BUFFER_V2` with release fence FD and feed back to SurfaceFlinger.
4. **VSync Generation**:
   Implement `IComposerCallback::onVsync()` synchronized either to Wayland presentation feedback timing or `CLOCK_MONOTONIC` timerfd.

### 5.4 Build Strategy
The custom `aaas-composer3` will be compiled as a standalone C++ binary using Android NDK (or host clang targeting Android x86_64 sysroot) linking against:
- `libbinder_ndk.so`
- `libcutils.so`
- `liblog.so`
- `libutils.so`
- `android.hardware.graphics.composer3-V4-ndk.so`

This isolates the graphics transport from the rest of AOSP, allowing the container graphics to talk directly to our verified M1A.1 Host Presenter.

---

## 6. Verification and Test Results

- All unit and stress tests pass:
  - `python3 -m unittest discover -s tests -v`: **34/34 passing**.
  - `make -C experiments/m1a test`: **100% passing** (`test-wire`, `test-wire-v2`, `test-sync-util`, `test-stress`).
- Zero tracking of generated results or benchmark traces in git.
- Full workspace isolation on `$AAAS_WORKSPACE`.
