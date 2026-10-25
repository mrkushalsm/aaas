# AaaS M1A.1: GPU Producer, Explicit Synchronization, and Transport Validation

**Date:** 2026-10-25  
**Status:** Completed (PASS)  
**Author:** Lead Linux Systems Engineer (AaaS)

---

## 1. Executive Summary

Milestone M1A.1 resolves the critical-path host-side GPU synchronization contract identified during the M1B preflight and graphics audit. We have implemented and validated a complete, genuine GPU rendering pipeline with explicit DRM synchronization between an offscreen GPU producer and an independent native Wayland presenter running under KWin Wayland.

### Key Milestones Achieved
1. **Real GPU Producer (no CPU writes, no `glFinish` serialization):**
   - Renders animated shader geometry on Intel Alder Lake-P GT1 (UHD Graphics) via Mesa Iris OpenGL ES 3.2.
   - Allocates tiled GPU-shareable DMA-BUFs (`DRM_FORMAT_XRGB8888`, modifier `0x100000000000002` / `INTEL_Y_TILED`).
   - Exports acquire fences as Linux `sync_file` descriptors via `EGL_ANDROID_native_fence_sync` (`eglDupNativeFenceFDANDROID`).
2. **Explicit Synchronization Interoperability (`sync_file` <-> `DRM syncobj`):**
   - Developed `sync_util.c` for kernel `sync_file` validation and DRM syncobj timeline import/export.
   - Uses `wp_linux_drm_syncobj_manager_v1` on KWin Wayland.
   - Employs dedicated per-slot release timelines to guarantee that out-of-order compositor releases can never prematurely signal prior buffers.
3. **Transport Wire Protocol v2:**
   - 96-byte versioned, bounded binary packet protocol with explicit message types, multiplane descriptor arrays, generation counters, stable buffer IDs, and SCM_RIGHTS FD ownership rules.
   - Preserves M1A v1 as an independently testable regression baseline.
4. **Live Validation & Visual Evidence:**
   - Executed live against KWin Wayland (150 sustained frames, 150 explicit-sync frames, 0 rejected).
   - Captured visual proof of rendered output: `results/m1a1/live-gpu-frame.png`.
   - Automated stress tests pass 100%, with zero file descriptor leaks across 100 rapid cycles.

---

## 2. Hardware, Kernel, and Driver Environment

| Component | Identifier | Version / Properties |
|---|---|---|
| Host GPU | Intel Alder Lake-P GT1 [UHD Graphics] `[8086:46a3]` | Mesa Intel Graphics (ADL GT2) |
| Kernel Driver | `i915` | DRM capabilities: `DRM_CAP_SYNCOBJ = 1`, `DRM_CAP_SYNCOBJ_TIMELINE = 1` |
| Primary Render Node | `/dev/dri/renderD129` | Permissions: `0666` (world read/write) |
| OpenGL ES | Mesa 26.2.4-arch1.1 | OpenGL ES 3.2, EGL 1.5 |
| Wayland Compositor | KWin Wayland 6.7.5 | `WAYLAND_DISPLAY=wayland-0` |
| Advertised Protocols | `wp_linux_drm_syncobj_manager_v1` (v1), `zwp_linux_dmabuf_v1` (v5) | Modifier tranches for `XR24`, `AR24`, `AB24`, `XB24` |

---

## 3. Explicit Synchronization Architecture

```
+-----------------------------------------------------------------------------------------+
|                                    GPU PRODUCER                                         |
|                                                                                         |
|  1. Await Slot Release Fence: sync_file_wait(slot.release_fence_fd, 1000ms)             |
|  2. GLES Draw Calls: Animated rotating fragment shader into FBO (EGLImage -> gbm_bo)    |
|  3. eglCreateSyncKHR(EGL_SYNC_NATIVE_FENCE_ANDROID) + glFlush()                         |
|  4. eglDupNativeFenceFDANDROID() -> acquire_sync_file_fd                                |
|  5. Send AAAS_V2_BUFFER with [dma_buf_fd, acquire_sync_file_fd]                         |
+--------------------------------------------+--------------------------------------------+
                                             | UNIX SEQPACKET Socket (Wire Protocol v2)
                                             v
+-----------------------------------------------------------------------------------------+
|                                  WAYLAND PRESENTER                                      |
|                                                                                         |
|  6. Import DMA-BUF -> zwp_linux_buffer_params_v1_create_immed() -> wl_buffer            |
|  7. Advance Acquire Point: acquire_point++                                              |
|     syncobj_timeline_import_sync_file(drm_fd, acquire_timeline, acquire_point, acq_fd)   |
|     wp_linux_drm_syncobj_surface_v1_set_acquire_point(acquire_timeline, acquire_point)  |
|  8. Advance Slot Release Point: slot[i].release_point++                                 |
|     wp_linux_drm_syncobj_surface_v1_set_release_point(slot[i].release_tl, rel_point)    |
|  9. wl_surface_commit(surface)                                                          |
+--------------------------------------------+--------------------------------------------+
                                             | Wayland Protocol Commit
                                             v
+-----------------------------------------------------------------------------------------+
|                                    KWIN COMPOSITOR                                      |
|                                                                                         |
| 10. Compositor GPU waits on acquire_timeline at acquire_point before texture sampling    |
| 11. Compositor completes frame presentation / display scanout                           |
| 12. Compositor signals slot[i].release_tl at release_point                               |
+--------------------------------------------+--------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                               PRESENTER COMPLETION                                      |
|                                                                                         |
| 13. Compositor fires buffer release                                                     |
| 14. syncobj_timeline_export_sync_file(drm_fd, slot[i].release_tl, point, &release_fd)     |
| 15. Send AAAS_V2_RELEASE with [release_sync_file_fd] back to Producer                   |
+-----------------------------------------------------------------------------------------+
```

### Immunity to Out-of-Order Release Hazards
Monotonic DRM syncobj timelines implicitly mark all points `< P` as signaled once point `P` is reached. If a single release timeline were shared across all rotating buffers, a quick release of buffer 3 would prematurely unblock buffer 1.  
**Solution Implemented:** Each buffer slot maintains its own independent DRM syncobj timeline (`slot[i].release_timeline_handle`). Buffer 3 advancing point `N` has no interaction with Buffer 1 or 2, guaranteeing mathematical safety under out-of-order compositor release sequences.

---

## 4. Transport Wire Protocol v2 Specification

Defined in `experiments/m1a/src/wire_v2.h` (96 bytes packed):

| Field | Type | Description |
|---|---|---|
| `magic` | `uint32_t` | Constant `0x53414141` (`'AAAS'`) |
| `version` | `uint32_t` | Constant `2` |
| `type` | `uint32_t` | `HELLO (1)`, `RESIZE (2)`, `BUFFER (3)`, `RELEASE (4)`, `CLOSE (5)` |
| `flags` | `uint32_t` | `EXPLICIT_SYNC (1<<0)`, `RELEASE_FENCE (1<<1)`, `LINEAR (1<<2)` |
| `generation` | `uint32_t` | Window configuration epoch |
| `id` | `uint32_t` | Stable buffer slot identifier (`1..N`) |
| `width`, `height` | `uint32_t` | Buffer dimensions in pixels (max 8192) |
| `format` | `uint32_t` | DRM fourcc format code (`DRM_FORMAT_XRGB8888`) |
| `num_planes` | `uint32_t` | Plane count (`1..4`) |
| `modifier` | `uint64_t` | DRM format modifier (e.g. `I915_FORMAT_MOD_Y_TILED`) |
| `offset[4]` | `uint32_t[4]` | Byte offsets per plane |
| `stride[4]` | `uint32_t[4]` | Byte pitch per plane |
| `timestamp_ns` | `uint64_t` | Monotonic timestamp |
| `reserved[2]` | `uint32_t[2]` | Explicit zero padding |

### SCM_RIGHTS FD Ownership
- For `AAAS_V2_BUFFER` with `EXPLICIT_SYNC`: FDs `0..num_planes-1` are DMA-BUFs; FD `num_planes` is the acquire `sync_file`.
- For `AAAS_V2_RELEASE` with `RELEASE_FENCE`: FD `0` is the release `sync_file`.
- The receiver enforces strict deep validation: if a received FD is not a valid DMA-BUF or not a valid `sync_file`, all descriptors are closed immediately and the message is rejected with `EBADFD`.

---

## 5. Live Execution Trace & Evidence

A sustained live run of 150 frames was recorded against KWin Wayland:
- **Trace file:** `results/m1a1/live-gpu-trace.jsonl`
- **Verification script:** `experiments/m1a/tests/check_trace_v2.py`
- **Result:**
  ```text
  Trace verified successfully: 150 GPU submissions, 150 explicit-sync frames, 147 releases, 147 presented.
  ```

### Trace Excerpt
```json
{"t_ns":5507940170361,"role":"producer","event":"release_fence_waited","generation":2,"id":3,"release_wait_result":1}
{"t_ns":5507940267602,"role":"producer","event":"frame_sent_gpu","generation":2,"id":3,"frame":119,"modifier":72057594037927938,"explicit_sync":true}
{"t_ns":5507940436071,"role":"presenter","event":"frame_committed","generation":2,"id":3,"explicit_sync":true,"acquire_point":119,"release_point":60}
{"t_ns":5507940975026,"role":"presenter","event":"buffer_release","generation":2,"id":2,"fence":"exported","point":59}
{"t_ns":5507942268041,"role":"presenter","event":"frame_presented","generation":2,"id":0,"flags":7}
{"t_ns":5507957110861,"role":"producer","event":"release_with_fence","generation":2,"id":2,"fence":"received"}
```

### Visual Verification
Visual proof captured via Spectacle background capture:
- **Image:** `results/m1a1/live-gpu-frame.png` (1920x1200 RGBA, 791 KiB).

---

## 6. Automated Test Matrix

All tests run via `make -C experiments/m1a test` and `python3 -m unittest discover -s tests`:

| Test Suite | Target | Cases Verified | Result |
|---|---|---|---|
| `test-wire` | M1A v1 Baseline | Original 48-byte wire roundtrip, bad FD reject | PASS |
| `test-wire-v2` | Transport Protocol v2 | Hello, resize, bad version, buffer with sync, release with fence, bad FD cleanup | PASS |
| `test-sync-util` | DRM Syncobj & Fences | `sync_file_is_valid`, timeline signal/wait, sync_file timeline import/export, FD transfer | PASS |
| `test-stress` | Concurrency & Faults | Malformed packets, delayed acquire fence, out-of-order release, 100 roundtrip FD leak stress, invalid syncobj errors, 50 rapid resizes, inflight disconnect | PASS |
| `check_trace_v2.py` | Live Trace Assertion | Monotonic acquire points, zero unreleased reuse, summary matching | PASS |
| `python3 -m unittest` | Python Test Suite | 30 unit tests (M1B.0 workspace guard, LP metadata parser, image fetch/inspect, repo lock) | PASS |

---

## 7. Deliverables Summary

| Component | Path | Description |
|---|---|---|
| Protocol XML | `experiments/m1a/protocols/linux-drm-syncobj-v1.xml` | Upstream Wayland DRM syncobj protocol definition |
| Sync Utilities | `experiments/m1a/src/sync_util.h`, `sync_util.c` | Linux `sync_file` and DRM syncobj timeline import/export |
| Wire Protocol v2 | `experiments/m1a/src/wire_v2.h`, `wire_v2.c` | Version 2 transport protocol with explicit synchronization |
| GPU Producer | `experiments/m1a/src/gpu_producer.h`, `gpu_producer.c` | Asynchronous GLES rendering, fence export, release wait |
| GPU Presenter | `experiments/m1a/src/gpu_presenter.h`, `gpu_presenter.c` | Wayland presenter with `linux-drm-syncobj-v1` integration |
| Unified Executable | `experiments/m1a/src/main_v2.c` -> `build/aaas-m1a1` | CLI entry supporting `--gpu`, `--cpu`, `--implicit-sync`, `--frames` |
| Stress Tests | `experiments/m1a/tests/test_stress.c` | Automated stress testing suite |
| Trace Checker | `experiments/m1a/tests/check_trace_v2.py` | Automated log validator |
| Makefile | `experiments/m1a/Makefile` | Modular build system building v1, v2, and all tests |

---

## 8. Next Step: Android 16 Composer3 v4 Integration

With the host-side explicit synchronization contract proven, tested, and operating live under KWin Wayland, the next narrowly scoped milestone is:
- **M1A.2 / M1B.1 AIDL Composer3 Virtual Display Bridge**: Connect the verified Android 16 `android.hardware.graphics.composer3` v4 service (`/vendor/bin/hw/android.hardware.graphics.composer3-service.ranchu` / AIDL `IComposer`) with the `wire_v2` transport protocol, translating Android Binder composition layers and acquire/release fences into `AAAS_V2_BUFFER` submissions.
