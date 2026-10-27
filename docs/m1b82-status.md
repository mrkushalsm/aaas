# M1B.8.2 status — Settings first draw investigation

**Result: PARTIAL.** The framework launched the real Settings activity, but its pixels did not reach the Wayland window. No source correction has yet been justified or deployed for the native crash or BufferQueue stall.

## Preservation and baseline

- Branch `master`, initial HEAD `db43230`; no remote. Inherited changes in `experiments/m1b/shim_selinux.c` and `scripts/test_zygote_startup.py`, and inherited untracked M1B.8 files, were left intact. Their hashes and Git state are in `results/m1b82/preservation_manifest.json`. Copies and pre-edit diffs are under the external workspace `tmp/m1b82_preedit/`.
- External workspace was verified as mounted NTFS3 at `/run/media/mrkus/Homework/aaas-workspace` before the live runs. No original image or historical overlay was changed.
- The loaded SwiftShader overlay is `tmp/vulkan.pastel.so`, SHA-256 `4e9e89c1b534f05daf773516de599a6b525c875e49f3de1c5406ce1110e1a5a3`, ELF build ID `6954e2fbdddce3e33971d6c9e6bd70ad47b9ac4d`. The external SwiftShader source is at `cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5` with the retained Gemini/Codex working patches. The overlay retains local `__libc_single_threaded` storage set to zero.
- Before changes, 73 Python unit tests, `make -C experiments/m1a test`, and `android_workspace.py check` passed. This does not prove Settings rendering.

## Fresh live reproduction

The existing runtime runner was used with the M1B.8.1 diagnostic UWB, network statistics, Keystore SID, and meminfo overlays, `AAAS_BOOTANIM=0`, `AAAS_BOOT_WAIT=45`, and `AAAS_SETTINGS_SIGQUIT=1`. Logs have prefix `m1b82_baseline1_` in the external workspace `tmp/`. The existing Wayland presenter was run concurrently with frame dumps. Exact evidence and hashes are in `results/m1b82/baseline.json`.

- Framework reached boot completion and Settings launch returned `Status: ok`. ActivityManager resolved `com.android.settings/.homepage.SettingsHomepageActivity`; WindowManager focused `com.android.settings/com.android.settings.Settings` (PID 1093).
- The presenter imported/submitted 42 client targets, reported 36 presented, 6 discarded, and 41 releases. Composer3 logged frame IDs 1–42 with two client-target backings and one bounded 40 ms backpressure timeout. No client-target backing reuse violation was observed in this trace.
- Eight dumped host frames had five distinct SHA-256 hashes. Visual inspection of the last frame showed the **“Phone is starting…”** progress screen, not Settings.
- Settings' SIGQUIT trace shows its main thread waiting in `DrawFrameTask::drawFrame` and RenderThread inside `BufferQueueProducer::dequeueBuffer` through EGL beginFrame. This establishes the blocking location, but the queue slot counts and release history have not yet been captured, so the cause of the wait remains open.
- Logcat also shows a separate framework stability problem: `lmkd` repeatedly waits for `bpf.progs_loaded`, reports watchdog timeouts, and kills processes. This can terminate Settings while its draw is blocked.
- SurfaceFlinger diagnostic dumps timed out. A follow-up run with `AAAS_SF_SIGQUIT=1` terminated the native SurfaceFlinger process; that run is excluded from queue-state conclusions. The runner's SIGQUIT method is suitable for Java Settings but not for native SurfaceFlinger here.

## Retained SwiftShader crash analysis

The previous M1B.8.1 tombstone is `tmp/m1b81_dualstack1_tombstones/tombstone_04` in the external workspace. It records a Settings RenderThread SIGSEGV in `pthread_mutex_lock`, called by `std::unique_lock<std::mutex>::lock` from `sw::DrawCall::run` at relative PC `0x199350` of the matching SwiftShader build ID above.

Disassembly at `0x199328–0x199350` reads `draw->batchDataPool`, then its `marl::BoundedPool<BatchData>::storage` pointer, and adds `0x47cec10` to obtain `storage->mutex`. The recorded storage pointer is `0x7f04e8f7a310`; its calculated mutex is `0x7f04ed748f20`. The tombstone maps that final address to read-only libc string data containing `ppoll64`, and does not map the storage pointer itself. The expected mutex cannot be valid at that address. The immediate defect is therefore a stale or corrupted Marl pool storage pointer, **not evidence that Bionic's mutex implementation is wrong**.

The source assigns `draw->batchDataPool = &Renderer::batchDataPool` before `DrawCall::run`; `Renderer` owns both the draw and batch pools. `Renderer::~Renderer` waits on `drawTickets`, and `vk::Queue::~Queue` joins its queue thread before member destruction. These intended lifetime guards need runtime verification. Current evidence does not distinguish premature pool destruction, shared-pointer corruption, or an earlier overwrite. The crash and Settings dequeue stall have not been shown to share a cause.

## Targeted diagnostic runs

A temporary trace patch is retained at `experiments/m1b/swiftshader/renderer_lifetime_trace.patch`. It logs Renderer construction/destruction and the batch pool pointer used by the first 128 draws per process to Android logcat. The diagnostic overlay `tmp/m1b82_lifetime_logcat_vulkan.so` has SHA-256 `3ab49761ec2ca0dc2634d099e55c1d52e765e3a3baa7be6414b2e3edff2ffea2` and build ID `9027acad8ae8467a035e2b98cc096529675eb00d`. Raw logs use prefix `m1b82_lifetime2_`; counts are in `results/m1b82/lifetime_diagnostic.json`. This is a probe, not a corrective patch.

The diagnostic was built by applying the retained patch in `sources/swiftshader`, running `ninja -C sources/swiftshader/build src/Device/libvk_device.a`, and invoking `python3 scripts/build_android_swiftshader_overlay.py --workspace /run/media/mrkus/Homework/aaas-workspace --output /run/media/mrkus/Homework/aaas-workspace/tmp/m1b82_lifetime_logcat_vulkan.so`. The runner selected it with `AAAS_VULKAN_OVERLAY` and used the same M1B.8.1 diagnostic overlays as the baseline. The patch is validated with `git apply --check` against the restored external SwiftShader source.

In that run, Settings PID 651 constructed a Renderer and logged 128 draws using a consistent batch-pool storage pointer. It did not reproduce the invalid-mutex crash. At `12:37:15.112`, `lmkd`'s watchdog explicitly killed PID 651 with `oom_score_adj 0`; Android then launched PID 1172 for FallbackHome. This establishes a separate cause of Settings process loss and explains why a later host frame can show FallbackHome. It does not explain the earlier blocked dequeue.

A second, temporary diagnostic edit called `setprop ctl.stop lmkd` after framework boot; init reported `stopped`. This run (`m1b82_nolmkd_`) still produced `Status: timeout` for Settings launch, a blocked Settings RenderThread in `BufferQueueProducer::dequeueBuffer`, SurfaceFlinger dump timeouts, and only 7 host submissions. The stop happened after a five-second settle, during which earlier watchdog kills occurred. Therefore removing later watchdog kills did **not** restore first-draw progress in this run. The temporary runner edit and SwiftShader source edit were restored byte-for-byte from the pre-edit backups, and the original overlay was never replaced.

## Next smallest experiments

1. Extend the retained lifetime trace to cover batch pool storage destruction and draw ticket completion, and reproduce the invalid-mutex crash with the matching instrumented ELF. The trace should prove whether the pool storage was destroyed before the draw or overwritten while live.
2. Capture Settings' BufferQueue state at the blocked dequeue: slot states, queued/acquired/dequeued counts, buffer IDs, fences, and release callbacks. Use a native-safe SurfaceFlinger stack capture method; do not use SIGQUIT again. Distinguish app-layer BufferQueue state from Composer3 client-target releases.
3. Address `lmkd`'s missing-BPF watchdog behavior through its actual supported fallback or a narrow source fix. Do not present the temporary `ctl.stop` diagnostic as a production correction.
4. Patch only demonstrated ownership violations, add focused reproducers, and then repeat real Settings runs with presenter captures and BootAnimation regression.

## Gates

| Gate | Result | Evidence boundary |
| --- | --- | --- |
| G1 baseline preserved | Partial | Existing tests passed; fresh BootAnimation sustained run was not performed. |
| G2 native crash diagnosed | Partial | Exact fault path and invalid storage pointer symbolicated; allocation history unresolved. |
| G3 native crash fixed | Fail | No source fix or repeat stress run. |
| G4 BufferQueue stall diagnosed | Partial | Blocking call located; queue state and reason unknown. |
| G5 BufferQueue progress restored | Fail | Settings first draw remained blocked. |
| G6 Settings rendered | Fail | Captured screen is startup progress. |
| G7 Settings stable | Fail | No repeated successful first draws. |
| G8 buffer/fence safety | Partial | Client-target trace showed 41 releases for 42 submissions; app-buffer safety unverified. |
| G9 framework continuity | Fail | `lmkd` killed Settings in one run; another timed out even after diagnostic `lmkd` stop. |
| G10 resources/lifecycle | Partial | Processes exited after bounded runs; full lifecycle matrix not executed. |
| G11 regression verification | Partial | Repository tests pass; live Settings test fails its visual objective. |
| G12 reproducible evidence | Partial | Raw logs and structured baseline retained; no corrective patch yet. |

The diagnostic network-statistics and Keystore overlays remain development-only and must not be described as validated source-based or production-security fixes.
