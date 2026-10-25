# AaaS M1B.5 Status: Native DRM Mapper 5 Bringup & SurfaceFlinger RenderEngine Breakthrough

## 1. Executive Summary

Milestone M1B.5 targeted the earliest graphics blocker identified in the recovered Android 16 container runtime: `mapper.ranchu.so` aborting due to missing Goldfish emulator pipe and address space devices (`/dev/goldfish_pipe_dprctd` and `/dev/goldfish_address_space`), which previously crashed `surfaceflinger` and blocked `SurfaceFlingerAIDL` publication.

By engineering a freestanding, Bionic-compatible native DRM/DMA-BUF Mapper 5 (Stable-C) implementation ([experiments/m1b/mapper_drm/mapper_drm.cpp](file:///home/mrkus/Work/personal/projects/aaas/experiments/m1b/mapper_drm/mapper_drm.cpp)), validating it with a standalone compatibility harness ([experiments/m1b/mapper_drm/test_mapper_compat.cpp](file:///home/mrkus/Work/personal/projects/aaas/experiments/m1b/mapper_drm/test_mapper_compat.cpp)), and mounting it via isolated overlay in [scripts/test_zygote_startup.py](file:///home/mrkus/Work/personal/projects/aaas/scripts/test_zygote_startup.py), **SurfaceFlinger successfully advanced past graphics allocation and completed full RenderEngine initialization** using ANGLE OpenGL ES 3.1 on SwiftShader Vulkan.

As explicitly anticipated in Section 12 of the milestone specification, advancing past graphics allocation revealed the exact next integration boundary: `android.hardware.graphics.composer3-service.ranchu` rejects non-QEMU hosts because it hardcodes a requirement for `virtio_gpu` DRM nodes. This document details the causal chain, the native Mapper 5 implementation, live container verification, and the technical specification for the upcoming independent AaaS Composer3 implementation.

---

## 2. Baseline Reproduction & Preservation

Before introducing any modifications, the historical baseline logs were preserved and isolated:
- Historical logs preserved in:
  - [full_logcat.log](file:///run/media/mrkus/Homework/aaas-workspace/tmp/historical_baseline/full_logcat.log)
  - [sf_strace.log](file:///run/media/mrkus/Homework/aaas-workspace/tmp/historical_baseline/sf_strace.log)
  - [zygote_recovery_run.log](file:///run/media/mrkus/Homework/aaas-workspace/tmp/historical_baseline/zygote_recovery_run.log)

To guarantee that subsequent test runs would not overwrite historical records, [scripts/test_zygote_startup.py](file:///home/mrkus/Work/personal/projects/aaas/scripts/test_zygote_startup.py) was enhanced to support `AAAS_LOG_PREFIX`. A fresh baseline run (`AAAS_LOG_PREFIX="m1b5_baseline_"`) was executed and reconfirmed:
1. Zygote forked `system_server` (PID 230), publishing 30 core Binder services.
2. `DisplayManagerService` blocked indefinitely waiting for `SurfaceFlingerAIDL`.
3. `surfaceflinger` (PID 83) loaded `/vendor/lib64/hw/mapper.ranchu.so`, logged `GoldfishAddressSpaceHostMemoryAllocator failed to open`, and terminated with `SIGABRT`.

---

## 3. Root Cause Analysis: The Graphics Allocation Barrier

### 3.1 Dynamic Library Resolution Call Chain
In Android 16 (`libui.so`), graphics buffer management follows the Mapper 5 architecture:
1. `GraphicBufferMapper::getInstance()` initializes `Gralloc5Mapper`.
2. `Gralloc5Mapper` queries the default AIDL Allocator service `android.hardware.graphics.allocator.IAllocator/default` via `AServiceManager_waitForService()`.
3. It calls `IAllocator::getIMapperLibrarySuffix(&suffix)`. In the emulator rootfs, the allocator returns `"ranchu"`.
4. It calls `AServiceManager_openDeclaredPassthroughHal("mapper", "ranchu", 2)`.
5. The Android dynamic linker searches `/vendor/lib64/hw/mapper.ranchu.so`, maps it into `surfaceflinger`, and invokes `AIMapper_loadIMapper(&outImplementation)`.

### 3.2 VINTF Manifest Declarations
The vendor VINTF manifest fragment at `/vendor/etc/vintf/manifest/android.hardware.graphics.gralloc.ranchu.xml` declares:
```xml
<manifest version="9.0" type="device">
    <hal format="aidl">
        <name>android.hardware.graphics.allocator</name>
        <version>2</version>
        <fqname>IAllocator/default</fqname>
    </hal>
    <hal format="native">
        <name>mapper</name>
        <fqname>@5.0/ranchu</fqname>
    </hal>
</manifest>
```

### 3.3 Goldfish Hardware Dependency Failure
In stock `mapper.ranchu.so`, `AIMapper_loadIMapper` constructs a `GoldfishMapper` singleton, which initializes `GoldfishAddressSpaceHostMemoryAllocator`. This allocator immediately executes:
```c
open("/dev/goldfish_pipe_dprctd", O_RDWR | O_CLOEXEC);
open("/dev/goldfish_address_space", O_RDWR | O_CLOEXEC);
```
On native Linux hardware (Intel/NVIDIA), these nodes return `ENOENT`. The library asserts and aborts:
```
F libc    : Fatal signal 6 (SIGABRT), code -1 (SI_QUEUE) in tid 83 (surfaceflinger)
E mapper.ranchu: GoldfishAddressSpaceHostMemoryAllocator failed to open: No such file or directory
```

---

## 4. Native DRM/DMA-BUF Mapper 5 Implementation

Rather than emulating goldfish pipe protocols or attempting a multi-gigabyte AOSP rebuild, we implemented a freestanding, native Linux DRM/DMA-BUF Mapper 5 shared library conforming to the Android Stable-C Mapper 5 ABI.

### 4.1 Freestanding Architecture
- **Stable-C Interface**: Mapper 5 does not use HIDL or AIDL Binder IPC; it operates as an in-process C function table (`AIMapper`) containing `uint32_t version` and 15 C function pointers.
- **Freestanding Bionic Linkage**: To avoid ABI mismatches between host GCC/Clang `libc++` and Android Bionic `libc++.so`, the implementation in [experiments/m1b/mapper_drm/mapper_drm.cpp](file:///home/mrkus/Work/personal/projects/aaas/experiments/m1b/mapper_drm/mapper_drm.cpp) uses freestanding C/C++ primitives without STL dependencies (`std::mutex`, `std::unordered_map`). Thread safety is implemented using standard `pthread_mutex_t`, and handle tracking uses fixed-capacity memory slots.
- **Native Handle Layout**: Defined in [experiments/m1b/mapper_drm/include/cutils/native_handle.h](file:///home/mrkus/Work/personal/projects/aaas/experiments/m1b/mapper_drm/include/cutils/native_handle.h), tracking DMA-BUF file descriptors, pixel dimensions, strides, pixel formats, usage flags, and allocation sizes.

### 4.2 Stable-C Function Table Coverage
The implementation exports:
- `ANDROID_HAL_MAPPER_VERSION = 5`
- `AIMapper_loadIMapper(AIMapper** outImplementation)`

And populates all 15 required function pointers:
1. `importBuffer(const native_handle_t* handle, buffer_handle_t* outBufferHandle)`: Clones DMA-BUF file descriptors using `dup()` and registers the imported handle in the active handle table.
2. `freeBuffer(buffer_handle_t bufferHandle)`: Closes cloned file descriptors and unmaps any active memory regions.
3. `getTransportSize(buffer_handle_t bufferHandle, uint32_t* outNumFds, uint32_t* outNumInts)`: Computes serialization size for Binder IPC.
4. `lock(buffer_handle_t bufferHandle, uint64_t cpuUsage, ARect accessRegion, int acquireFence, void** outData)`: Maps the underlying DMA-BUF using `mmap(MAP_SHARED)` with appropriate `PROT_READ | PROT_WRITE` protections and waits on optional acquire fences.
5. `unlock(buffer_handle_t bufferHandle, int* outReleaseFence)`: Flushes mapped buffers and emits an optional release sync fence.
6. `flushLockedBuffer`: Memory synchronization hook for coherent DMA-BUF access.
7. `rereadLockedBuffer`: Invalidation hook for CPU cache coherency.
8. `getMetadata` & `getStandardMetadata`: Returns standard Gralloc 5 metadata (Width, Height, Stride, Allocation Size, Buffer ID, Pixel Format, Usage).
9. `setMetadata` & `setStandardMetadata`: Updates mutable metadata attributes.
10. `listSupportedMetadataTypes`: Enumerates supported metadata queries.
11. `dumpBuffer` & `dumpAllBuffers`: Emits diagnostic logging for `dumpsys SurfaceFlinger`.
12. `getReservedRegion`: Returns reserved gralloc shared memory regions.

### 4.3 Compilation
The library is compiled with host `clang++` targeting `x86_64-linux-android` against Bionic SDK libraries:
```bash
clang++ -target x86_64-linux-android \
  -shared -fPIC -O2 -nostdlib \
  -I experiments/m1b/mapper_drm/include \
  -I /run/media/mrkus/Homework/aaas-workspace/rootfs_m1b1/system/include \
  experiments/m1b/mapper_drm/mapper_drm.cpp \
  /run/media/mrkus/Homework/aaas-workspace/rootfs_m1b1/system/lib64/libc.so \
  /run/media/mrkus/Homework/aaas-workspace/rootfs_m1b1/system/lib64/libcutils.so \
  -o /run/media/mrkus/Homework/aaas-workspace/tmp/mapper.drm.so
```

---

## 5. Standalone Compatibility Verification

A comprehensive standalone test harness was built in [experiments/m1b/mapper_drm/test_mapper_compat.cpp](file:///home/mrkus/Work/personal/projects/aaas/experiments/m1b/mapper_drm/test_mapper_compat.cpp) and executed inside an unprivileged Bubblewrap container simulating Android Bionic userspace:

```bash
bwrap --ro-bind "$ROOTFS" / \
  --bind "$ROOTFS/dev" /dev \
  --dev-bind /dev/dri /dev/dri \
  --bind "$TMP_DIR/mapper.drm.so" /data/mapper.drm.so \
  --bind "$TMP_DIR/test_mapper_compat" /data/test_mapper_compat \
  /system/bin/sh -c "cd /data && /data/test_mapper_compat /data/mapper.drm.so"
```

### Verification Output:
```
=== AaaS M1B.5 Mapper 5 Compatibility Probe ===
[TEST] Loading mapper shared library: /data/mapper.drm.so
[TEST] ANDROID_HAL_MAPPER_VERSION = 5
[MAPPER.DRM] AIMapper_loadIMapper called! Native DRM Mapper 5 loaded.
[TEST] AIMapper loaded successfully: mapper=0x7e88764b8100 version=5
[TEST] Using Linux memfd DMA-BUF backing
[MAPPER.DRM] importBuffer: handle=0x7e88764c2020 numFds=1 numInts=10 -> cloned_fd=4
[TEST] importBuffer succeeded: imported=0x7e88764c20a0 (cloned fd=4)
[TEST] Metadata validation:
       WIDTH: 1920 (expected 1920)
       HEIGHT: 1080 (expected 1080)
       STRIDE: 1920 (expected 1920)
       SIZE: 8294400 (expected 8294400)
       FORMAT: 1 (expected 1)
[MAPPER.DRM] lock: handle=0x7e88764c20a0 (fd=4 size=8294400) -> mapped_ptr=0x7e8875adb000
[TEST] lock succeeded: mapped_ptr=0x7e8875adb000
[MAPPER.DRM] unlock: handle=0x7e88764c20a0
[TEST] unlock succeeded: releaseFence=-1
[TEST] Real backing memory data coherency VERIFIED across independent DMA-BUF mappings!
[MAPPER.DRM] freeBuffer: handle=0x7e88764c20a0 (fd=4 mapped=0x7e8875adb000 size=8294400)
[TEST] freeBuffer succeeded
=== ALL MAPPER 5 & DMA-BUF COMPATIBILITY TESTS PASSED ===
```

---

## 6. Live Container SurfaceFlinger Bringup & RenderEngine Breakthrough

### 6.1 Isolated Overlay Execution
Using [scripts/test_zygote_startup.py](file:///home/mrkus/Work/personal/projects/aaas/scripts/test_zygote_startup.py) with `mapper.drm.so` mounted over `/vendor/lib64/hw/mapper.ranchu.so`, the container booted under full Zygote, `system_server`, and SurfaceFlinger supervision.

### 6.2 Breakthrough in RenderEngine Initialization
The live logcat in `/run/media/mrkus/Homework/aaas-workspace/tmp/m1b5_primary_full_logcat.log` confirmed that SurfaceFlinger loaded the native DRM mapper:
```
I mapper.drm: [MAPPER.DRM] AIMapper_loadIMapper called! Native DRM Mapper 5 loaded.
```

With graphics allocation unblocked, ANGLE EGL display initialization on SwiftShader Vulkan proceeded immediately. **SurfaceFlinger initialized and completed its RenderEngine backend without crashing:**
```
I RenderEngine: Threaded RenderEngine with SkiaGL Backend (Ganesh)
I RenderEngine: Background Blurs Enabled (Kawase algorithm)
I RenderEngine: OpenGL ES informations:
I RenderEngine: vendor    : Google Inc. (Google)
I RenderEngine: renderer  : ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver-5.0.0)
I RenderEngine: version   : OpenGL ES 3.1.0 (ANGLE 2.1 git hash: 1166eec4c0b125e9e945196acfc549983ef72b18)
I RenderEngine: GL_MAX_TEXTURE_SIZE = 8192
I RenderEngine: GL_MAX_VIEWPORT_DIMS = 8192
```

---

## 7. The Subsequent Integration Boundary: Ranchu HWComposer 3

### 7.1 Causal Sequence in SurfaceFlinger `init()`
SurfaceFlinger's `init()` sequence executes in a strict order:
1. `RenderEngine::create()` (**PASSED** with native DRM Mapper 5 + ANGLE).
2. `createHWComposer()`:
   - Connects to AIDL service `android.hardware.graphics.composer3.IComposer/default`.
   - Calls `IComposer::createClient(&mClient)`.
3. `sm->addService("SurfaceFlingerAIDL", mClient)`.
4. `flinger->run()`.

### 7.2 The Ranchu HWComposer virtio_gpu Hardcode
In the live test, immediately following RenderEngine initialization, `surfaceflinger` called `createClient()`. The vendor service `android.hardware.graphics.composer3-service.ranchu` (PID 68) logged:
```
E RanchuHwc: Failed to find virtio-gpu DRM node. Ranchu HWComposer is only expected to be used with "virtio_gpu"
```
Because the host environment provides native Linux DRM nodes (`/dev/dri/card0` / `renderD128` corresponding to Intel/NVIDIA), `RanchuHwc` rejected client creation. As a result, `mAidlComposer->createClient()` failed, aborting SurfaceFlinger prior to registering `SurfaceFlingerAIDL`.

### 7.3 Milestone Boundary Adherence
As required by Section 12 of the M1B.5 specification:
> *"If graphics allocation succeeds but Composer3 remains blocked by Goldfish hardware, record that as a distinct next integration boundary. Do not bypass the second failure by fabricating success."*

This result precisely establishes that:
1. Graphics buffer mapping is solved for native Linux via Stable-C Mapper 5.
2. RenderEngine is completely functional on software Vulkan (SwiftShader).
3. The remaining blocker to `SurfaceFlingerAIDL` publication is the emulator-specific `composer3.ranchu` service, which must be replaced by the dedicated AaaS Composer3 implementation.

---

## 8. Automated Verification Suite

Unit tests validating Milestone M1B.5 are implemented in [tests/test_m1b5_graphics.py](file:///home/mrkus/Work/personal/projects/aaas/tests/test_m1b5_graphics.py):
- `test_vintf_graphics_declarations`: Validates VINTF manifests for Gralloc 5 (`IAllocator/default`, `mapper@5.0/ranchu`) and HWC3 (`IComposer/default`).
- `test_mapper_drm_source_structure`: Enforces presence and structure of all 15 Stable-C function pointers in `mapper_drm.cpp` and `native_handle.h`.
- `test_mapper_drm_binary_symbols`: Verifies `AIMapper_loadIMapper` and `ANDROID_HAL_MAPPER_VERSION` dynamic symbol visibility.
- `test_mapper_compat_source`: Verifies `test_mapper_compat.cpp` exercises DMA-BUF import, locking, and cross-mapping coherency.
- `test_zygote_startup_overlay_flags`: Verifies overlay and logging isolation in `test_zygote_startup.py`.
- `test_historical_baseline_preserved`: Confirms historical baseline logs remain intact and untouched in `historical_baseline/`.

Full project test suite passes:
```
Ran 65 tests in 0.111s
OK
```

---

## 9. Next Milestone Roadmap: AaaS Composer3 Bringup

To achieve `SurfaceFlingerAIDL` registration and complete framework boot:
1. **Independent Composer3 Service**:
   Implement a minimal `android.hardware.graphics.composer3.IComposer` AIDL service that accepts client connections without QEMU `virtio_gpu` hardcodes.
2. **Display Configuration & VSync**:
   Provide a virtual display (e.g. 1920x1080@60Hz) and a software VSync timer to drive SurfaceFlinger composition loops.
3. **Host Presentation**:
   Connect output framebuffers directly to Wayland surfaces via host `wl_drm` / `linux-dmabuf` protocol extension, fulfilling the unified AaaS desktop integration vision.
