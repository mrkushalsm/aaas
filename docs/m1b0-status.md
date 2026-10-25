# M1B.0: Android 16 Build Feasibility, Source Reduction, and Workspace Setup

**Date:** 2026-10-25  
**Status:** Completed  
**Owner:** Lead Linux Systems Engineer (AaaS)

## Objective

Determine whether a reproducible Android 16 (API 36) image can be acquired within
the 80 GiB working budget on the external NTFS disk, and identify what subset of the
Android graphics and composition system stack is present for modern AIDL Composer3
HAL and Gralloc integration work.

---

## 1. External Workspace Setup & Budget

| Property | Value |
|---|---|
| Mount point | `/run/media/mrkus/Homework/` |
| Block device | `/dev/sda2` |
| Filesystem | `ntfs3` |
| UUID | `A2ACEDF2ACEDC0C1` |
| Available disk capacity | 466 GiB (346 GiB free at start) |
| Working ceiling | 80 GiB (strictly enforced by `scripts/android_workspace.py`) |
| Safety reserve | 20 GiB |
| Workspace root | `/run/media/mrkus/Homework/aaas-workspace/` |

### Filesystem Capabilities & Constraints (Probed)

| Capability | Result | Notes |
|---|---|---|
| POSIX permissions / chmod | Supported | Files can be made executable |
| Symlinks / Hard links | Supported | Hardlinks count once in usage accounting |
| Case sensitivity | Supported | NTFS case sensitivity active |
| Sparse files | ❌ NOT supported | Sparse holes are fully allocated on disk |
| Reflinks | ❌ NOT supported | Cannot copy-on-write duplicate images |
| Mount flags | `nosuid, nodev` | System build tools requiring SUID/mknod cannot run directly on NTFS |

**Conclusion:** Direct AOSP full builds cannot be hosted on the NTFS partition.
However, it is ideal for download storage, extracted images, caches, and inspection work.

---

## 2. Public Android SDK System Image Acquisition

Because Google Android Build CI API requires authentication and legacy endpoints return 403,
we probed and verified Google's publicly accessible SDK system images:

| Image Identifier | File | Size | SHA1 (Verified) | Status |
|---|---|---|---|---|
| `system-images;android-36;default;x86_64` | `x86_64-36_r02.zip` | 805.1 MiB (844,217,077 bytes) | `829c076e8ff448a336097ae25a355b495ba36e2c` | Downloaded & Verified |

Download receipt stored at `results/m1b0/fetch-receipt.json`.

---

## 3. Image Layout & Dynamic Partition Analysis

The downloaded archive unpacks to 1,954 MiB uncompressed, containing 20 members.
Inspection revealed a 2-tier disk structure:

### Disk Structure

1. **`system.img` (1,811 MiB):**
   - Disklabel: GPT (GUID Partition Table)
   - Partition 1: `vbmeta` (1.0 MiB, sectors 2048..4095)
   - Partition 2: `super` (1,808.0 MiB, sectors 4096..3706879)

2. **LP Dynamic Partitions inside `super`:**
   Parsed using pure-Python tool `scripts/read_lp_metadata.py`:
   - Logical block size: 4,096 bytes
   - Metadata slots: 2
   - Group: `emulator_dynamic_partitions` (1,800.0 MiB max)
   - Partition list:
     - `system`: 912.4 MiB (ext4, sector 2048)
     - `system_dlkm`: 7.0 MiB (raw/unknown, sector 1871872)
     - `system_ext`: 207.0 MiB (ext4, sector 1886208)
     - `product`: 367.9 MiB (ext4, sector 2312192)
     - `vendor`: 96.6 MiB (ext4, sector 3065856)

3. **`vendor.img` (99.0 MiB):**
   - Disklabel: GPT
   - Partition 1 (`/dev/sda1`): 97.0 MiB (ext4, sectors 2048..200703)
   - Mountable read-only via `guestfish` using `mount-ro /dev/sda1 /`

---

## 4. Discovered Graphics & HAL Architecture

Filesystem inspection of `/dev/sda1` on `vendor.img` confirmed the presence of modern
AIDL HAL services for both display composition and memory allocation:

### 4.1 Composer3 Virtual Hardware Composer

- **Binary:** `/vendor/bin/hw/android.hardware.graphics.composer3-service.ranchu`
- **AIDL Interface:** `android.hardware.graphics.composer3` Version 4 (`IComposer/default`)
- **VINTF Declaration:** `/vendor/etc/vintf/manifest/hwc3.xml`
  ```xml
  <manifest version="9.0" type="device">
      <hal format="aidl">
          <name>android.hardware.graphics.composer3</name>
          <version>4</version>
          <fqname>IComposer/default</fqname>
      </hal>
  </manifest>
  ```
- **AOSP Upstream Source Pointer:** `device/generic/goldfish-opengl/system/hwc3/hwc3.xml`
- **Init Configuration:** `/vendor/etc/init/hwc3.rc`
  ```rc
  service vendor.hwcomposer-3 /vendor/bin/hw/android.hardware.graphics.composer3-service.ranchu
      class hal animation
      user system
      group graphics drmrpc
      capabilities SYS_NICE
      onrestart restart surfaceflinger
      task_profiles ServiceCapacityLow
  ```
- **Dynamic Linkage (`readelf -d`):**
  - `android.hardware.graphics.composer3-V4-ndk.so` (AIDL NDK backend)
  - `libsync.so` (Linux explicit fence synchronization)
  - `libdrm.so` (Direct Rendering Manager / KMS integration)
  - `libgralloctypes.so` (Gralloc buffer metadata descriptors)
  - `libbinder_ndk.so` (NDK Binder IPC)
  - `libui.so` (Android graphic buffers and geometry)

### 4.2 Gralloc Allocator & Mapper

- **Binary:** `/vendor/bin/hw/android.hardware.graphics.allocator-service.ranchu`
- **AIDL Allocator:** `android.hardware.graphics.allocator` Version 2 (`IAllocator/default`)
- **Mapper:** `mapper@5.0/ranchu` (`/vendor/lib64/hw/mapper.ranchu.so`)
- **VINTF Declaration:** `/vendor/etc/vintf/manifest/android.hardware.graphics.gralloc.ranchu.xml`
- **Init Configuration:** `/vendor/etc/init/android.hardware.graphics.allocator-service.ranchu.rc`

---

## 5. Architectural Implications for AaaS

1. **Composer3 is AIDL Version 4:**
   The AaaS independent HAL implementation must target `android.hardware.graphics.composer3` v4.
   SurfaceFlinger connects via `IComposer/default` through Binder IPC.
2. **Explicit Fence Synchronization (`libsync.so`):**
   Acquire and release fences are passed as sync file descriptors (`/dev/sync` or DMA-BUF fences).
   This directly confirms the viability of the M1A.1 GPU fence synchronization architecture.
3. **Mapper 5.0:**
   The SDK image declares a Ranchu Gralloc Mapper 5.0. Its handle layout and
   successful DMA-BUF import into the host compositor have not been verified.
   The later diagnostic SurfaceFlinger run aborts while this mapper opens
   missing Goldfish devices; see `docs/m1b-graphics-blocker.md`.

---

## 6. Deliverables & Scripts

| Artifact | Path | Description |
|---|---|---|
| Workspace Guard | `scripts/android_workspace.py` | Storage guard with budget checks and runtime monitoring |
| Image Fetcher | `scripts/fetch_android_image.py` | Fetch & SHA1 verify Android SDK system images |
| Image Inspector | `scripts/inspect_android_image.py` | Inspect zip, extract images, parse LP metadata, scan vendor HALs |
| LP Metadata Parser | `scripts/read_lp_metadata.py` | Pure-Python parser for Android LP dynamic partitions & super images |
| Image Manifest | `manifests/android-images.json` | Pinned URLs, file sizes, and SHA1 hashes for SDK images |
| Fetch Receipt | `results/m1b0/fetch-receipt.json` | Cryptographic verification of downloaded image |
| Image Content Report | `results/m1b0/image-contents.json` | Machine-readable breakdown of partitions, HALs, and VINTF |
| LP Metadata Report | `results/m1b0/lp-metadata.json` | Detailed dynamic partition extents and filesystem report |
| Unit Test Suite | `tests/test_android_image.py`, `tests/test_lp_metadata.py` | Automated test suites (30 tests, all passing) |

---

## 7. Next Milestone: M1A.1 GPU Synchronization

With the Composer3 and Gralloc HAL contracts, binaries, and dependencies definitively established
from verified Android 16 artifacts, the next phase proceeds to:
- Establishing the DMA-BUF / DRM sync-file explicit synchronization primitives between host and runtime.
