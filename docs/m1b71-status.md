# M1B.7.1 status: baseline recovered, synchronization unresolved

**Result: PARTIAL.** The inherited first-frame result reproduced and advanced through six host submissions, but M1B.7.1 does not pass: buffer recycling and real completion fences have not been proved. No implementation source was changed during this read-only handoff/baseline stage.

## Baseline and source identity

- Branch `master`, commit `1f0f82bff948dbcc856a3581c79af3757b8dd280`; initial tree clean, no stash, no remote.
- Gemini transcript: 5,841 JSONL records inspected by schema and targeted chronological search. See `docs/m1b7-gemini-codex-handoff.md` for recovered decisions and preserved architecture.
- SwiftShader upstream base `cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5`, with nine modified tracked files in the external workspace. Source SHA256: `libVulkan.cpp` `abe35432a4a4ec003aee264f71d9e03ee7bdc9225b0bad55be7118357128ecaa`; `VkImage.cpp` `a849faed633b23d90c86a06b820ed0b30ddacbefe22b05ba353aa7ebabbc8d22`. Do not treat the base revision as including the working patch.
- Binary SHA256: Mapper `9471065827bd95a35e1da7a20fa93ecba179b414c7359e410651e44b747aadf2`; Allocator `7fbba21442c5688e0c45557f5fadf51d463b1722f25c1e3d0a67c838a67a9197`; Composer3 `55b96dead82d6c5fa20f2292bc2552d0d100e0380ae0dd9593b2b1c3e5ed5196`; Vulkan overlay `4e9e89c1b534f05daf773516de599a6b525c875e49f3de1c5406ce1110e1a5a3`; presenter `80ccdddb5a95622fde1f77f2febde9b1a060340129e43a14ef77ad7d77af4a61`.
- Workspace `/run/media/mrkus/Homework/aaas-workspace` was mounted as NTFS3 `/dev/sda2`; budget check reported 14,557,457,408 used bytes and 356,345,339,904 free bytes with 80 GiB ceiling and 20 GiB reserve. Render node `/dev/dri/renderD129`; Wayland session `wayland-0`, KWin capabilities logged `explicit_sync_capable=true`, 18 modifiers.

## Reproduction

Existing stale presenter owned an unlinked socket after a historical restart. An initial run (`m1b71_baseline_`) reached Android client-target pixels but failed transport connection with `ECONNREFUSED`; it is retained as a failed baseline attempt. After stopping that stale presenter and starting the same host binary, `AAAS_LOG_PREFIX=m1b71_baseline2_ AAAS_BOOT_WAIT=22 python3 scripts/test_zygote_startup.py` reproduced six Android client-target submissions in a 1280×720 Wayland window. Host summary: imports 6, submissions 6, releases 5, rejected 0, presented 6, discarded 0, protocol-explicit frames 6, peak RSS 501,040 KiB, user CPU 257,357 µs, system CPU 33,449 µs. The six submits happened in roughly 0.2 seconds; this is **not** a sustained duration test. Raw logs are in external `tmp/m1b71_baseline2_{runner,composer,allocator,full_logcat,kmsg_zygote_test}.log` and `tmp/m1b71_baseline_presenter.log`. Structured host events and content SHA256 values are in `results/m1b71/baseline.json`.

The host presenter dumped PPM pixels from the received buffer before Wayland import. The six originals are preserved in external `tmp/m1b71_baseline_frames/`. `artifacts/m1b71_android_animation.png` was converted from the first PPM with Pillow. Their hashes show five distinct byte sequences, but frame 6 repeats frame 4 and frame 5 has an unusually broad pixel range; changed pixels relative to frame 1 were 50,326, 37,265, 50,573, 888,711 and 50,573. These dumps originate from Android Composer3 submissions, not a host synthetic generator. They are evidence of changing pixels, not yet proof of correct animation or safe buffer reuse. The earlier `artifacts/m1b7_android_frame.png` remains the historical visual baseline.

The captured PNG visibly contains a horizontal tear. The baseline log shows multiple Scudo `invalid chunk state when deallocating` errors in SurfaceFlinger (PID 119), followed by a tombstone request at 18:11:23.064; this stopped the six-frame burst. A clean container repeat with `AAAS_LOG_PREFIX=m1b71_repeat_ AAAS_BOOT_WAIT=12` produced one submitted/presented frame and then the same Scudo error in BootAnimation (PID 160), tombstoned at 18:13:57.756. This cross-process failure is consistent with a shared graphics-library memory-management defect, but the exact freeing call is not established without a tombstone/backtrace. Repeat logs remain under the external workspace `tmp/m1b71_repeat_*`; its one PPM is retained as `tmp/m1b71_baseline_frames/repeat_frame_1.ppm`.

## Synchronization and ownership audit

SwiftShader `vkQueueSignalReleaseImageANDROID` calls `vkQueueWaitIdle`, sets native fence FD to `-1`, then calls `Image::prepareForExternalUseANDROID`. That method copies device memory to AHardwareBuffer memory under a CPU lock. Queue idle orders SwiftShader's queue work before this copy, but the return code of `vkQueueWaitIdle` is discarded and the subsequent SurfaceFlinger composition/acquire-fence path has not been validated. The copy uses device-memory offset and source row pitch; bounds, format and destination pitch checks are missing. Its `AHardwareBuffer_unlock` result is ignored.

Composer3 receives `ClientTarget.buffer.fence` (baseline `-1`), sends no acquire FD and returns a signaled `sync_file` from a signaled DRM syncobj. A DRM syncobj handle/FD and a Linux `sync_file` FD are distinct types; the `DRM_SYNCOBJ_HANDLE_TO_FD` call uses the export-sync-file flag. The signaled fence is currently fabricated relative to Wayland work. It must not be counted as completion. Composer3 similarly returns signaled layer release fences. The actual AIDL v4 nullability and SurfaceFlinger consumers still require a call-path audit; historical `UNEXPECTED_NULL` failures explain the workaround but do not establish its semantics.

Transport duplicates the DMA-BUF and optional acquire FD over SCM_RIGHTS. It maps frame ID to slot but has one release FD per slot. It does not wait for the Wayland release fence before reporting the next present. In this run ID 3 reused slot 1 and ID 4 reused slot 0 before host release messages for IDs 1 and 2. The host uses an acquire timeline, imports an incoming sync_file if present, or signals a point immediately if absent. It uses per-slot release timelines; on release it exports a sync_file. Presentation feedback is logged separately. The outstanding last frame was not released before process shutdown. This state machine is not yet safe enough to claim consumer synchronization.

Proposed required state transition: allocated → Android rendering → client-target ready → submitted with unique `(generation, frame ID, slot, buffer identity)` → host imported → committed → release timeline complete → release sync_file delivered/consumed → reusable. Connection loss or generation invalidation must retire in-flight IDs without reporting success. Current code does not enforce these transitions.

## Tests and gates

- `python3 -m unittest discover -s tests -v`: 72 passed.
- `make -C experiments/m1a test`: wire v1/v2, sync utility and stress tests passed.
- `python3 scripts/android_workspace.py --workspace /run/media/mrkus/Homework/aaas-workspace check`: passed.
- Live baseline2: six imports/submissions and six presentation feedback events, five release messages. No current 150-frame test, bounded long run, clean repeat, lifecycle suite, per-FD accounting, frame latency/copy timing, or new synchronization regression suite.

| Gate | Result | Evidence / boundary |
|---|---|---|
| G1 baseline | PASS | Live Android-to-Wayland six-frame reproduction |
| G2 continuous | PARTIAL | Five distinct captures in a short burst; no sustained run |
| G3 producer sync | UNPROVEN | Queue idle and CPU copy observed; client-target path unaudited |
| G4 consumer sync | FAIL | Slot reuse precedes release; signaled fence returned |
| G5 fence correctness | FAIL | Types partly verified; completion fabricated |
| G6 lifetime | FAIL | Single release FD per slot, overlapping IDs |
| G7 SwiftShader copy | PARTIAL | Visible pixels; bounds and error checks missing |
| G8 Wayland lifecycle | UNTESTED | Disconnect observed, lifecycle cases not run |
| G9 resource/performance | PARTIAL | Host CPU/RSS measured; no sustained accounting |
| G10 regression | PARTIAL | Existing tests pass; M1B.7.1 live tests absent |
| G11 visual | PARTIAL | Actual Android frames change; progression/correctness unproved |
| G12 reproducibility | PARTIAL | Baseline logs, hashes and handoff retained; reliability work pending |

The SELinux compatibility shim and staged APEX are experimental. They do not provide Android's production security model. Do not run untrusted APKs or expose container IPC to other users. The current rendering path uses SwiftShader software Vulkan and CPU copying, with possible additional host staging; it is not end-to-end zero-copy or hardware GPU rendering.

## Next engineering step

First, model each in-flight client-target buffer by identity and generation, propagate a real host-release completion fence to Android's reuse decision, and fail closed on disconnect. In parallel, inspect Android's Composer3 AIDL v4 fence unmarshalling and SurfaceFlinger consumer code to determine the valid absent-fence representation. Then add delayed/out-of-order release tests and repeat the live run before attempting 150 frames. Do not remove the SwiftShader copy or replace the graphics stack.
