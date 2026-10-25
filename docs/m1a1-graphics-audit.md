# AaaS M1A.1: Host Graphics & Explicit Synchronization Audit

**Date:** 2026-10-25  
**Author:** Lead Linux Systems Engineer (AaaS)  
**Scope:** `experiments/m1a/` producer, presenter, wire protocol, buffer registry, and Wayland synchronization.

---

## 1. Executive Summary

Milestone M1A established a functional CPU-written DMA-BUF transport between a producer and a native Wayland presenter using `zwp_linux_dmabuf_v1` and `xdg-shell`. However, M1A relies entirely on synchronous CPU memory mapping (`gbm_bo_map`) and the compositor's `wl_buffer.release` event.

When transitioning to an independent split-engine Android compatibility runtime with real GPU workloads (Android GLES apps, SurfaceFlinger, and AIDL Composer3), rendering and composition become asynchronous GPU pipelines. Under asynchronous GPU execution, the assumptions in M1A v1 break down.

This document details the audit findings and defines the requirements for M1A.1:
1. Real GPU rendering via EGL/GLES on Mesa/GBM.
2. Kernel explicit synchronization via Linux `sync_file` (dma-buf fence) and DRM syncobj timelines.
3. Wayland compositor explicit synchronization via `wp_linux_drm_syncobj_manager_v1`.
4. Extended Wire Protocol v2 with acquire/release fence passing, multiplane support, and robust lifetime tracking.
5. Preservation of M1A CPU-written path as a regression baseline.

---

## 2. Detailed Audit of Existing M1A Components

### 2.1 Producer (`experiments/m1a/src/main.c`)
- **Current Behavior:**
  - Creates a GBM device from DRM render node `/dev/dri/renderD129`.
  - Allocates buffers with `gbm_bo_create(dev, w, h, GBM_FORMAT_XRGB8888, GBM_BO_USE_LINEAR | GBM_BO_USE_RENDERING)`.
  - CPU maps the buffer with `gbm_bo_map(..., GBM_BO_TRANSFER_WRITE, ...)` and fills pixels with nested CPU loops.
  - Sends DMA-BUF FD without any synchronization fence.
- **Failures under Asynchronous GPU Execution:**
  - **No Acquire Fence:** If a GPU submits draw calls to command rings, execution is asynchronous. Without exporting an acquire fence (`sync_file`), the DMA-BUF is submitted to Wayland while GPU vertex/fragment shaders may still be actively writing memory. The compositor reads incomplete or torn frames.
  - **Misleading Synchrony:** Calling `glFinish()` after every frame would serialize execution on the CPU thread, defeating pipelined rendering and creating severe throughput degradation.
  - **Modifier Restrictions:** Linear allocation (`GBM_BO_USE_LINEAR`) disables hardware tiling (such as Intel `INTEL_Y_TILED` or `INTEL_Y_TILED_GEN12_RC_CCS`), reducing GPU memory bandwidth efficiency.

### 2.2 Wayland Presenter (`experiments/m1a/src/main.c`)
- **Current Behavior:**
  - Binds `zwp_linux_dmabuf_v1` (version 3), `wl_compositor`, `xdg_wm_base`, and `wp_presentation`.
  - Hardcodes `explicit_sync: false`.
  - Imports DMA-BUF via `zwp_linux_buffer_params_v1_create_immed()`.
  - Listens only for `wl_buffer.release`.
- **Fallacies Regarding `wl_buffer.release` & `wp_presentation`:**
  - `wl_buffer.release` is an asynchronous IPC event from the Wayland compositor informing the client that it has unlatched the buffer from its current display state.
  - **`wl_buffer.release` is NOT a GPU completion fence:** It carries no synchronization file descriptor. The compositor's GPU may still be executing texture sampling or composition passes when the event is sent.
  - `wp_presentation_feedback` (`presented` / `discarded`) reports display refresh timing and hardware scanout timestamping. It is an informational callback, not an execution fence that can be inserted into a GPU command queue or imported into a DRM syncobj.

### 2.3 Wire Protocol v1 (`experiments/m1a/src/wire.h`, `wire.c`)
- **Structure:** Rigid 48-byte struct `aaas_msg`.
- **Limitations:**
  - `AAAS_BUFFER` strictly enforces `nfds == 1` (the DMA-BUF FD). It has no capacity to transmit an acquire fence FD.
  - `AAAS_RELEASE` enforces `nfds == 0`. It cannot transmit a release fence FD back to the producer.
  - Single-plane assumption: Only single `offset` and `stride` fields. No support for multiplanar formats (e.g. YUV420, NV12).
  - No handshake or capability negotiation: Features (such as explicit sync vs implicit sync) cannot be queried or agreed upon.
  - No defined byte-order conversion or schema versioning.

### 2.4 Synchronization & Concurrency Hazards
1. **Acquire Hazard:** Producer GPU rendering overlaps with Compositor sampling -> visual tearing, corruption.
2. **Release Hazard:** Compositor GPU reading overlaps with Producer next-frame GPU writing -> write-after-read hazards, corrupted frame history.
3. **Out-of-Order Release Hazard:** If the presenter uses a single monotonic DRM syncobj timeline for all releases, releasing buffer 2 implicitly signals buffer 1. If buffer 1 was held by the compositor for scanout, buffer 1 would be falsely marked reusable, causing memory corruption.

---

## 3. Host Capabilities & Architecture Plan for M1A.1

### 3.1 Verified Host Primitives
1. **DRM / Kernel:**
   - Node: `/dev/dri/renderD129` (Intel Alder Lake-P GT1 / UHD Graphics, Mesa Iris driver).
   - `DRM_CAP_SYNCOBJ = 1`
   - `DRM_CAP_SYNCOBJ_TIMELINE = 1`
   - `drmSyncobjHandleToFD`, `drmSyncobjFDToHandle`, `drmSyncobjImportSyncFile`, `drmSyncobjExportSyncFile`, `drmSyncobjTransfer` all verified functional.
2. **EGL & OpenGL ES:**
   - EGL 1.5, OpenGL ES 3.2 Mesa 26.2.4.
   - `EGL_ANDROID_native_fence_sync` confirmed available.
   - `eglCreateSyncKHR(dpy, EGL_SYNC_NATIVE_FENCE_ANDROID, NULL)` + `eglDupNativeFenceFDANDROID(dpy, sync)` verified to produce valid `sync_file` FDs.
3. **KWin Wayland Compositor:**
   - Advertises `wp_linux_drm_syncobj_manager_v1` version 1 (global name 61).
   - Advertises `zwp_linux_dmabuf_v1` version 5 with DRM modifier tranches (`INTEL_Y_TILED`, `LINEAR`, etc.).

### 3.2 Key Architectural Requirements
1. **GPU Producer:**
   - Use GBM + EGL + GLES2/3 offscreen rendering (FBO attached to EGLImage backed by `gbm_bo`).
   - Draw actual dynamic GPU geometry / shaders.
   - Flush GPU pipeline (`glFlush()`) and export acquire fence via `eglDupNativeFenceFDANDROID()`.
   - Never call `glFinish()` in the frame loop.
   - Wait on release fence before recycling buffer.
2. **DRM Syncobj Interoperability:**
   - Presenter imports acquire `sync_file` FD into acquire timeline point via `drmSyncobjImportSyncFile` + `drmSyncobjTransfer`.
   - Presenter provides dedicated per-slot release timeline or independent release points so out-of-order completion is mathematically immune to monotonic timeline premature signaling.
   - Presenter exports compositor release point to `sync_file` via `drmSyncobjTransfer` + `drmSyncobjExportSyncFile` and sends it to producer.
3. **Wire Protocol v2:**
   - Version 2 wire protocol supporting:
     - `AAAS_V2_HELLO`: capability & version negotiation.
     - `AAAS_V2_RESIZE`: generation & window dimensions.
     - `AAAS_V2_BUFFER`: buffer metadata + DMA-BUF FD + acquire fence FD.
     - `AAAS_V2_RELEASE`: buffer ID + generation + release fence FD.
     - `AAAS_V2_CLOSE`: clean shutdown notification.
4. **Regression Baseline:**
   - Preserve M1A v1 CPU-written path and v1 wire protocol as a separate compilation target and regression test.
