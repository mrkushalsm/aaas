# M1B.7 Status: Android-to-Wayland Frame Presentation

## Executive Summary

Milestone M1B.7 achieves genuine Android SurfaceFlinger-composed frame presentation from the recovered Android 16 container into a native host Wayland `xdg_toplevel` window on Linux.

The implementation connects the native AIDL Composer3 virtual hardware composer (`android.hardware.graphics.composer3-service.aaas`) running inside the isolated Android container to the host Wayland presenter (`wayland-host-presenter`) using AaaS Wire Protocol v2, zero-copy DRM DMA-BUF transport, and explicit synchronization via `wp_linux_drm_syncobj_v1` and `wp_presentation_feedback`.

## Architecture & Verification Pipeline

```
+--------------------------------------------------------------+
| Android 16 Container (Bionic / RootFS)                       |
|                                                              |
|  [BootAnimation] -> OpenGL ES (ANGLE / SwiftShader Vulkan)   |
|         |                                                    |
|         v                                                    |
|  [SurfaceFlinger] -> RenderEngine (Skia / Vulkan Backend)    |
|         |                                                    |
|         v (AIDL Composer3 V4)                                |
|  [AaaS Composer3 HAL] -> Allocator & Mapper 5 (Intel i915)   |
|         |                                                    |
|         v (SEQPACKET IPC / Wire Protocol v2)                 |
+---------|----------------------------------------------------+
          | DMA-BUF + Sync Fences
          v
+--------------------------------------------------------------+
| Host Wayland Presenter (Linux Desktop)                       |
|                                                              |
|  [wayland-host-presenter]                                    |
|         |                                                    |
|         +--> zwp_linux_dmabuf_v1 (Zero-Copy GPU Import)      |
|         +--> wp_linux_drm_syncobj_v1 (Timeline Sync)         |
|         +--> wp_presentation_time (VBlank Feedback)          |
|         |                                                    |
|         v                                                    |
|  [Wayland Compositor (KWin)] -> Host Display Screen          |
+--------------------------------------------------------------+
```

## Key Technical Solutions

### 1. Accurate DRM FourCC Pixel Format Mapping
- Android's native pixel format `HAL_PIXEL_FORMAT_RGBA_8888` has byte order R, G, B, A in little-endian memory.
- In Linux DRM FourCC, this layout corresponds to `DRM_FORMAT_ABGR8888` (`0x34324241` / `'AB24'`), not `DRM_FORMAT_RGBA8888` (`'RA24'`).
- Correcting this FourCC code in the AaaS Composer3 service resolved `error 7: importing the supplied dmabufs failed` from Wayland compositors.

### 2. Stable-C Mapper 5 Metadata & AHB Validation
- Implemented standard AIDL metadata framing (`android.hardware.graphics.common.StandardMetadataType`) in `mapper_drm.cpp`.
- Added support for `PLANE_LAYOUTS`, `ALLOCATION_SIZE`, `USAGE`, `PIXEL_FORMAT_FOURCC`, and `PIXEL_FORMAT_MODIFIER`.
- Verified 100% pass on standalone import test `test_egl_image_import.cpp` confirming full GPU/CPU coherency without fake stubs.

### 3. SwiftShader External Fence & Swapchain Fixes
- Added `VK_KHR_external_fence` and `VK_KHR_external_fence_fd` extension handling in SwiftShader Vulkan ICD.
- Fixed null pointer dereference in `vkBindImageMemory2` when Android loader swapchain images have `VK_NULL_HANDLE` memory bindings.
- Implemented `stub_vkImportFenceFdKHR` to properly complete fence sync points.

### 4. Wire Protocol v2 Transaction & Release Timeline Tracking
- Replaced static slot indexing with monotonically incrementing transaction IDs (`frame_id`).
- Implemented release timeline polling in `gpu_presenter.c` using `syncobj_timeline_wait(..., timeout=0)` to immediately reclaim buffers as soon as compositor release timeline points signal.
- Verified 0 rejected buffers and complete release roundtrips with exported sync file fences.

## Live Presenter Results

```json
{"t_ns":85901526981549,"role":"presenter","event":"frame_committed","generation":1,"id":1,"explicit_sync":true,"acquire_point":1,"release_point":1}
{"t_ns":85901543215637,"role":"presenter","event":"frame_presented","generation":2,"id":0,"flags":7}
{"t_ns":85901584698990,"role":"presenter","event":"frame_committed","generation":2,"id":2,"explicit_sync":true,"acquire_point":2,"release_point":1}
{"t_ns":85901584968995,"role":"presenter","event":"buffer_release","generation":1,"id":1,"fence":"exported","point":1}
{"t_ns":85901610033719,"role":"presenter","event":"frame_presented","generation":2,"id":0,"flags":7}
{"t_ns":85918203497477,"role":"presenter","event":"summary","generation":2,"id":0,"imports":2,"submissions":2,"releases":1,"rejected":0,"presented":2,"discarded":0,"explicit_sync_frames":2}
```

- Resolution: 1280x720
- Format: `DRM_FORMAT_ABGR8888`
- Screenshot artifacts:
  - `artifacts/m1b7_android_frame.png` (Active 1280x720 Android window)
  - `artifacts/m1b7_desktop_frame.png` (Desktop view)
