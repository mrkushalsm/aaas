# M1B.8.3 status — LMKD and Settings first draw

**Result: PARTIAL.** A source patch for a SwiftShader sampling-cache data race was built and loaded. Three independent isolated runs with that build launched the real Settings homepage and captured its Android-generated pixels in the Wayland presenter. The LMKD repair was validated with a checksum-guarded **binary diagnostic overlay**, while its source patch has not yet been built. The original SwiftShader build still stalled, and the older DrawCall mutex failure has not been traced to its allocation origin.

## Preservation and provenance

- Initial branch `master`, HEAD `4a0d285`, no remote. `results/m1b83/preservation_manifest.json` records the inherited worktree files and SHA-256 hashes. Those files were not edited or staged. The external workspace was verified as `$AAAS_WORKSPACE_DEVICE` (`ntfs3`), with 17,509,197,824 bytes used at the final workspace check, below the 80 GiB ceiling and with the 20 GiB reserve intact.
- The Android image and prior overlays were not replaced. The original SwiftShader overlay remains `tmp/vulkan.pastel.so` (SHA-256 `4e9e89c1b534f05daf773516de599a6b525c875e49f3de1c5406ce1110e1a5a3`, build ID `6954e2fbdddce3e33971d6c9e6bd70ad47b9ac4d`). The SwiftShader source base is `cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5`, with the earlier Gemini/Codex Vulkan and Bionic changes retained.
- Large logs and exact diagnostic binaries are under external `tmp/m1b83_*`. `results/m1b83/live_runs.json` records the per-run commands' prefixes, launch results, compositor counts, binary hashes, and exclusions. The intentionally misconfigured `m1b83_samplinglock3_` run is excluded: its services-JAR overlay accidentally named a `.so`, so it did not reach a comparable framework boot. Shared-socket runs are supporting evidence only; the controlled comparison used `m1b83_isolated_ipc/wayland.sock`.

## Failure timeline and LMKD diagnosis

The prior M1B.8.2 logs show the original LMKD main thread waiting for `bpf.progs_loaded` after `sys.boot_completed=1`. Its independent watchdog then killed processes every two seconds, eventually selecting foreground Settings at `oom_score_adj=0`. The running `/system/bin/lmkd` has build ID `0820006cb7c64cb792202a9058eb08e8`, SHA-256 `46af90db625b96ecd71c70d2d7f2712887f618e32ed56d80e9719902450851c0`. Its disassembly at `0xdc60–0xdd17` calls `android::base::WaitForProperty` before constructing `MemEventListener`, matching the [Android 16 LMKD source](https://android.googlesource.com/platform/system/memory/lmkd/+/291e98ff95c3ce2647e44a29628dfae51c5d2634/lmkd.cpp) at `init_memevent_listener_monitoring()`. The caller already logs and uses a vmstats fallback when this function returns false. The container has no pinned LMKD memevents ring buffer at `/sys/fs/bpf/memevents/map_bpfMemEvents_lmkd_rb`.

`scripts/patch_lmkd_memevents_diagnostic.py` guards the exact original checksum and three prologue bytes, then makes **only that listener-initialization function** return false in a separate overlay (`tmp/m1b83_lmkd_vmstats_diagnostic`, SHA-256 `9780759ba36e50d061064f05c77520809f3291edad6a43a1495e9d91f21d54bd`). The original image was not modified. The generated runner copy in external `tmp/m1b83_runner_isolated.py` bind-mounted this overlay and used a private transport socket; the inherited repository runner's hash remained unchanged.

The exact temporary-runner difference is retained as `patches/m1b83/runner-lmkd-isolated-diagnostic.patch`. Apply it to a **copy** of the current `scripts/test_zygote_startup.py` from the repository root with `patch -p1`; the resulting file must have SHA-256 `74829b88022a000237cc0d8baac7bb9a78112a587156732af11cfe53834eb2de`. The patch changes only the IPC directory and adds a read-only bind of the diagnostic LMKD binary when it exists. A dry-run and application to a fresh temporary copy matched the retained external runner byte for byte. This patch depends on the inherited runner revision recorded in the preservation manifest and is a diagnostic recipe, not a proposed production runner change.

Live logcat then showed ActivityManager connecting to LMKD and LMKD reporting **“Using vmstats for direct reclaim and kswapd detection”**. None of the valid M1B.8.3 overlay runs recorded an LMKD watchdog timeout or watchdog kill. An original-SwiftShader run with this same LMKD overlay still timed out on Settings after eight host submissions. This separates the watchdog fault from the graphics stall. LMKD also logged `EACCES` when writing some `/proc/<pid>/oom_score_adj` files; actual low-memory victim selection under pressure was **not** tested.

`patches/m1b83/lmkd-absent-memevents-fallback.patch` is a source-level candidate against Android 16 LMKD revision `291e98ff95c3ce2647e44a29628dfae51c5d2634`. Under an explicit `AAAS_CONTAINER_RUNTIME` build flag it checks whether the pinned ring buffer is unavailable and returns false to the existing vmstats path. It has passed reverse-apply and whitespace checks, but has **not** been compiled, loaded, or validated under genuine memory pressure. The diagnostic binary retains the original ELF build-ID note despite changed bytes, so its SHA-256 and observed vmstats log distinguish it from the image binary. This is not a production LMKD repair.

## SwiftShader race and native crashes

The retained SystemUI tombstone `tmp/m1b82_hold_tombstones/tombstone_02` faults at `SpirvEmitter::getImageSampler+930` (`0x162232`) in the original SwiftShader build. The instruction calls a virtual method through `rr::Routine`, but the loaded first word at that object address is `0x000001fe0000000d`, not a plausible vtable pointer. The source obtains this routine through `Device::SamplingRoutineCache::getOrCreate()`.

That method read its `std::unordered_map` snapshot without holding `mutex`, while `updateSnapshot()` cleared and repopulated the same map under `mutex`. Concurrent lookup and mutation of the map is undefined behavior. `experiments/m1b/swiftshader/m1b83_sampling_cache_lock.patch` moves the existing lock above the snapshot lookup, covering both the lookup and routine copy. No renderer, allocator, compositor, or transport component was replaced. The patch was built with the existing `ninja` and `scripts/build_android_swiftshader_overlay.py` procedure. The loaded diagnostic overlay is `tmp/m1b83_sampling_lock_vulkan.so`, SHA-256 `1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`, build ID `48176d3bf7c52ad4a2e1c8445fac8d52b83864ba`.

The earlier Settings DrawCall tombstone still establishes an invalid `BoundedPool` storage pointer in `DrawCall::run`; its allocation and overwrite history remain unknown. No DrawCall source correction was made. A probe with the retained Renderer lifetime logging alone produced 264 frames and Settings pixels, while an isolated run with the original unlogged overlay timed out after 8 host submissions (a separate shared-socket run timed out after 11). Logging materially changes timing and is **not** a fix. The cache-lock build produced Settings without lifetime logging in repeat runs, which supports the race correction, but does not prove that the old DrawCall fault and the SPIR-V fault share one cause. Neither fault recurred in the three successful cache-lock runs; this bounded observation is not a memory-safety proof.

## Settings and buffer progression

The controlled runs used the existing Android 16 framework overlays, actual `com.android.settings/.Settings` launch (resolved to `.homepage.SettingsHomepageActivity`), the existing Composer3, and the host presenter on a private socket. The unpatched, unlogged control run reached `sys.boot_completed=1`, but Settings returned `Status: timeout`; its RenderThread waited in `BufferQueueProducer::dequeueBuffer+4515`, while the SurfaceFlinger dump timed out and its main and RenderEngine threads were sampled in futex waits. The exact BufferQueue slot state and the upstream completion dependency remain unmeasured. This is a **partial wait-for graph**, not proof that the app BufferQueue itself is defective.

With the cache-lock overlay, independent isolated runs reported:

| Run | Settings launch | Host submissions | Presented | Releases | Visual result |
| --- | --- | ---: | ---: | ---: | --- |
| `m1b83_samplinglock1_` | ok | 287 | 281 | 286 | Settings homepage captured at frame 280 |
| `m1b83_samplinglock2_` | ok | 337 | 334 | 336 | Settings homepage captured at frame 320 |
| `m1b83_samplinglock4_` | ok | 436 | 432 | 435 | Settings homepage visible at frame 400 |

In the first successful run, ActivityTaskManager resumed Settings, WindowManager focused its window, SurfaceFlinger listed the Settings layer, and Settings RenderThread was idle in its sampled Java/native trace after drawing. The host's PPM client-target dumps show “Phone is starting…” in earlier frames, the Settings splash image during transition, and the actual Settings homepage later. **The 1280×720 capture** (maintainer archive only) comes from host `gpu_presenter` dumping Android Composer3 client targets, with no host-generated UI. `results/m1b83/frame_content.json` records 14 sampled RGB hashes and changed-pixel counts; frame 240 changed 831,808 pixels relative to frame 220. The exact first Settings frame lies between the sampled frames, so frame 280 is the first **retained confirmed homepage** frame, not necessarily the first one drawn.

The `m1b83_samplinglock3b_` run reached a 400-frame presenter cap before its sampled UI transition, so it is excluded from the three confirmed visual runs despite `Status: ok`. No run showed a Composer3 backing-reuse violation in its log. The maximum in-flight count and all FD counts were not independently sampled; live absence of leaks cannot be claimed. The presenter reported one outstanding release at normal disconnect in the three uncapped successful runs; the 150-frame and 400-frame capped runs stopped with additional in-flight buffers by design. The existing release-fence mechanism was not changed.

## BootAnimation, resources, and lifecycle

With the cache-lock overlay and `AAAS_BOOTANIM=1`, the existing presenter accepted 150 Android submissions, reported 149 presented, 148 releases, zero discarded/rejected, and 150 explicit-sync submissions before its 150-frame cap. This is a fresh graphics regression result, not a zero-copy claim. The SwiftShader CPU-copy stage remains. The running Android framework and normal presenter disconnect completed in the bounded runs; comprehensive window-close/restart and pressure tests remain open. Repeated unrelated Ranchu radio-service SIGABRT tombstones occurred in all runs and were not modified by this milestone.

The presenter reported maximum RSS of approximately 507 MiB in the isolated runs. The external workspace check reported 17,509,197,824 used bytes. Per-process FD counts, SwiftShader copy durations, real LMKD pressure response, and app BufferQueue slot counts were not measured. The current SELinux and Keystore SID probes remain development-only; no arbitrary APK was run and no host-wide security configuration was changed.

## Verification and commits

- `python3 -m unittest discover -s tests -v`: 73 passed.
- `make -C experiments/m1a test`: wire v1/v2, sync utility, and GPU sync stress tests passed.
- `python3 scripts/android_workspace.py --workspace $AAAS_WORKSPACE check`: passed with the required reserve.
- SwiftShader and LMKD source patch whitespace/reverse-apply checks passed. The SwiftShader patch was built and loaded; the LMKD source patch was not built.
- Live first-draw evidence is in the raw external logs and the structured result files under `results/m1b83/`. Commits: `e649c07` (SwiftShader cache lock), `e3bf422` (LMKD fallback diagnostic and source candidate), `13b5c29` (queue trace). This report and structured evidence are committed separately.

## Acceptance gates

| Gate | Result | Boundary |
| --- | --- | --- |
| G1 preserved work | PASS | Manifest, original binaries, logs, and inherited files retained. |
| G2 LMKD diagnosis | PASS | Exact `waitForProgsLoaded` path and watchdog sequence identified. |
| G3 LMKD correction | PARTIAL | Diagnostic vmstats fallback validated; source build and pressure behavior outstanding. |
| G4 queue wait diagnosis | PARTIAL | Successful run completes queue waits; original stall's outstanding task remains unidentified. |
| G5 native faults diagnosed | PARTIAL | Sampling-cache race established; DrawCall storage origin unknown. |
| G6 native faults corrected | PARTIAL | Cache race corrected and no recurrence in bounded runs; DrawCall fault unproven. |
| G7 BufferQueue progress | PASS | Real Settings first draw, layer, composition, and presenter pixels observed. |
| G8 Settings visible | PASS | Actual homepage captured from Android client target. |
| G9 stable rendering | PARTIAL | Three independent visible launches; longer stress and DrawCall lifetime proof remain. |
| G10 graphics baseline | PASS | 150-frame BootAnimation regression with release accounting. |
| G11 lifecycle | PARTIAL | Bounded normal exit verified; close/restart and FD-leak matrix incomplete. |
| G12 reproducibility | PARTIAL | Source and binary hashes, trace, screenshot, tests retained; LMKD source build outstanding. |

**Overall M1B.8.3: PARTIAL.** The Settings first-frame target is achieved through the existing architecture with the SwiftShader cache-lock patch and LMKD diagnostic fallback. The next smallest work is to build the source-based LMKD fallback, verify genuine pressure handling and `oom_score_adj` permissions, then instrument the original DrawCall pool lifetime and blocked SurfaceFlinger queue task without relying on logging-induced timing changes.
