# Graphics performance, frame pacing, and latency

Status: **PARTIAL — presenter instrumentation and bounded staging baseline verified; historical outlier and causal input latency remain open.**

Evidence date: 2026-11-03. Structured results are in [acceptance.json](../../results/post-m1e/graphics-performance/acceptance.json); raw presenter logs remain in the external AaaS workspace and are addressed by session ID and SHA-256 there.

## Scope and interpretation

This workstream adds opt-in measurements to the native presenter. It does not change rendering, synchronization, buffer ownership, or default runtime behavior. `--trace-staging-stages` is available only with `--experimental-virtual-display` and is disabled unless requested. A post-change untraced two-app session confirmed 119 accepted frames emitted no `staging_profile` records and no presentation timestamp fields. The production SwiftShader binaries, Android base image, Composer, and staging policy were not changed.

The legacy `staging_copy.overhead_us` starts after acquire-fence wait and ends after staging allocation, source sync/mapping, visible-row copy, unmapping, sync completion, and export. It is a complete presenter staging interval, not a memcpy timer. Detailed records additionally collect per-operation durations, presenter-thread CPU time, thread context-switch/fault deltas, errno/results, dimensions, format, and strides. Durations use `CLOCK_MONOTONIC`; CPU time uses `CLOCK_THREAD_CPUTIME_ID`; counters use `getrusage(RUSAGE_THREAD)`. Events carry presenter frame ID and display generation. Profile output is one JSON line per staged frame and uses the existing bounded session logs; it is diagnostic and can perturb tails.

`wp_presentation` is advertised by the tested KWin 6.7.5 session. Its clock ID was 1 (`CLOCK_MONOTONIC` on this host); refresh intervals were approximately 16.666 ms. Presentation feedback timestamps and commit-to-presentation intervals are reported as compositor presentation feedback. They are not physical scanout or photon timestamps. `wl_buffer.release` remains a separate buffer-reuse event. Frame callbacks, presentation feedback, and release are not conflated.

## Historical 326.704 ms event

The preserved frame 1687 in session `m1b84_session_nrgvcf_2` is still **OPEN/UNRESOLVED**. The immutable log hash is `1e57b4cf9e3087aab1e5241a0cd1c09c33ac086440fef075c8813bdd5bfaf4e9`.

At generation 6, the presenter received a 424×742 RGBA frame with 1792-byte source stride and DMA-BUF identity `(st_dev=12, st_ino=165571)` at monotonic time `138153517005560 ns`. The staging-complete event occurred at `138153843719109 ns`, reporting `326704 µs`. Receive-to-staging-event was `326713549 ns`; the old log has no substage timestamps, CPU time, syscall timing, or scheduler trace. The acquire-fence wait was excluded by the timer. The destination staging allocation had distinct identity `(12,166302)`, was imported and committed at `138153843801093 ns` and `138153843814906 ns`, then released later through the explicit-sync timeline.

This establishes that the long interval was inside the old measured presenter staging interval (within timestamp/event overhead), and rules out acquire-fence waiting as the reported 326.704 ms. It does **not** identify GBM allocation, DMA-BUF sync, mapping, row copy, unmapping, export, or descheduling as the cause. The frame was classified as alias composition. Current short samples do not reproduce the outlier; non-reproduction is not a fix. No production optimization is attributed to it.

## Current measurements

Four fresh two-app default-mode sessions used the same diagnostic Composer overlay and actual Settings/Contacts rendering. Two ran with detailed staging tracing (`m1b84_session_80s1na12`, `m1b84_session_u79tnnbp`); two ran without it (`m1b84_session_usc7dkdc`, `m1b84_session_gbmuetb5`). A further enhanced source-LMKD/cgroup session (`m1b84_session_xy76k5mt`) produced 121 detailed staging samples. All five ended `STOPPED`, with per-presenter imports/submissions/releases balanced and zero outstanding buffers. The runs were short event-driven/static UI samples, not a continuous animation benchmark.

Across the 234 detailed staging samples (none carried an acquire fence to wait on, so that stage has zero timing samples):

| Metric | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|
| Whole staging pipeline | 1.383 ms | 2.199 ms | 3.363 ms | 4.038 ms |
| GBM allocation | 0.514 ms | 0.873 ms | 1.142 ms | 1.753 ms |
| Visible-row copy | 0.727 ms | 1.078 ms | 1.352 ms | 2.628 ms |
| Destination map | 0.022 ms | 0.043 ms | 1.244 ms | 1.732 ms |
| Presenter thread CPU | 1.372 ms | 2.069 ms | 3.091 ms | 3.961 ms |

The stage distributions overlap and are not additive at their respective percentiles. Thread CPU time tracks whole-pipeline wall time closely in these samples, with zero median involuntary context switches and no major faults. This does not explain the historical 326 ms event, but does not indicate a recurring long wait or descheduling issue in the measured common path. GBM allocation and visible copy are the largest usual sub-stages; their observed absolute times remain below one 60 Hz interval. No buffer pool or copy-loop optimization was introduced because a material user-visible bottleneck or repeatable regression was not established, and changing lifetime behavior would add risk without an evidenced requirement.

The untraced legacy staging timer had 231 samples: p50 1.393 ms, p95 2.285 ms, p99 3.027 ms, max 3.717 ms. The traced legacy timer had p50 1.382 ms, p95 2.199 ms, p99 3.362 ms, max 4.038 ms. Separate short sessions show no median/p95 increase attributable to tracing, but are not a randomized paired overhead study; tail perturbation remains possible.

In the enhanced traced run, the two presenters' whole-pipeline p50 values were 1.473 ms and 1.270 ms; p95 values were 2.038 ms and 1.846 ms. Their GBM allocation p50 values were 0.571 ms and 0.458 ms; visible-copy p50 values were 0.740 ms and 0.679 ms. The enhanced session's presentation-feedback interval maximum included a long static/idle gap and is not classified as a missed frame.

The traced default runs received 114 and 112 compositor presentation-feedback events. KWin reported about 28 ms median and 38–43 ms p95 commit-to-presentation feedback. A separate controlled two-cycle Settings close/reopen workload received 92 and 117 presentation events on the two slots. Some adjacent presentation intervals were 16.659 ms (one observed refresh) and 33.3 ms, but the overall median was 83.3 ms and idle gaps reached 15.2 s because the UI is event-driven. Those gaps cannot be interpreted as missed refresh opportunities or frame drops. Feedback included presented/discarded classifications; counts are in the raw JSON. This validates burst event delivery and transitions, but a continuously animating workload and missed-refresh analysis remain unverified.

The previous staged mixed-composition acceptance contains matched alias/mixed staging p95 values around 1.6–2.0 ms, but its metric excludes Composer-side work. The new detailed sessions exercised the alias Composer path; they do not provide a matched detailed-stage trace of mixed composition or Composer operation duration. No comparison is made that mixed composition is faster based on lower presenter-only p95.

## Input latency and end-to-end boundaries

An opt-in `--trace-input-response-roi x,y,w,h` probe hashes only a bounded source-buffer ROI after a pointer-down input. It records the input sequence and baseline hash, source frame ID/generation and hash, then attaches that exact changed frame to its `wp_presentation` feedback. The analyzer requires matching adapter injection completion, host timestamp, changed ROI, committed frame, exact presented frame, and compatible clock ID. `input_probe_frame` is emitted while handling the received source transport frame; the Composer transport frame ID remains the frame ID used by the presenter. KWin 6.7.5 reports presentation feedback on clock ID 1 (`CLOCK_MONOTONIC`), with an observed refresh interval of 16.666 ms. This is compositor-reported presentation, not physical photon timing.

One default-mode sample now passes that causal chain: pointer sequence 6 on display 2 changed ROI hash `e81038c92f1dac2b` to `53467f0c4bd5df05` in generation 1, frame 170. The frame was committed and received presented feedback at `147856827696000 ns`, yielding **457.251 ms** from host input `147856370445404 ns`. The Android adapter reported successful injection (`rc=0`). The ROI hash for that frame took `344890 ns`. Raw presenter, adapter and logcat paths/hashes plus the analyzer result are in `acceptance.json` and `runs/input-response-default-single.json`. The app navigation was a real Settings Display-page transition; it did not crash.

That initial sample validated the method for a heavier Settings navigation, but it did not represent ordinary tap response or a distribution. It is retained separately and is not pooled with the minimal visual-response probe results below. Earlier excluded attempts include a Settings crash and a Contacts permission prompt; X11 injection also cannot target the native Wayland surface. The focused native-input attempt (`m1b84_session_1el0zr2e`) established that KWin delivers input when the AaaS toplevel is active, while an inactive or obscured toplevel does not receive it. Contacts was behind `GrantPermissionsActivity`, so that attempt had no expected target response. This was a readiness/focus issue, not a rendering measurement. No production input or graphics policy was changed.

Presenter receive-to-commit and commit-to-presentation are available for profiled frames. Android application update, SurfaceFlinger composition, Composer output-ready, and Composer mixed-operation timestamps are not emitted on a compatible frame clock in this runtime, so full app-to-display latency is unavailable. No cross-process timestamps are subtracted unless the request timestamp is explicitly copied across the boundary.

## Excluded low-memory input attempt

Session `m1b84_session_swvikvp2` is recorded as **FAILED**, not accepted: Android did not bring Settings to the ready state, so the real-input measurement never began. Android userspace LMKD killed Settings PID 3132 (uid 1000, `oom_score_adj=102`) because the minimum watermark was breached and swap was 1,396 kB, below its 801,380 kB threshold. It also killed other Android processes. Host swap free fell from 480,220 kB at startup to 7,616 kB at shutdown-begin, with elevated memory PSI; the AaaS cgroup had no memory limit and no cgroup OOM events. This was a legitimate pressure response, not evidence of an LMKD policy defect. The failure record and raw log hashes are in the structured acceptance JSON. This attempt is excluded from latency distributions and does not explain the historical 326.704 ms event.

A later default-mode input probe (`m1b84_session_slrcq4l5`) sent real Wayland pointer/key input through the AaaS adapter. Android launched Settings SearchActivity, and the adapter acknowledged packets, but visible Settings pixels remained unchanged; no affected frame could be causally identified. The exploratory full-frame hash cost 3.43–7.49 ms per frame, so its traces are excluded from timing. That attempt contributes no sample; the later single valid ROI-correlated Settings sample is recorded above. Raw log hashes and the limitation are in `acceptance.json`.

Session `m1b84_session_4a888xyr` is separately excluded before measurement. Contacts was still behind its runtime permission prompt, then Android LMKD killed Contacts and PermissionController during genuine host memory/swap pressure: host `SwapFree` fell from 673,608 kB at session start to 212 kB at shutdown-begin, and Android reported 228 kB/164 kB against an 801,380 kB low-swap threshold. The AaaS cgroup had no memory limit. No policy was changed; this run is not a latency sample. Raw hashes and lifecycle evidence are in `runs/input-response-lmkd-readiness-failure.json`.

## Optimization decision and status

No production performance optimization was justified by the bounded measurements. The common path is not shown to violate the host frame budget, and the one large historical stall lacks stage evidence. The instrumentation and analyzer are reusable and opt-in; existing AaaS synchronization and release invariants remain unchanged.

The input-to-compositor-reported-presentation measurement task is **PASS/CLOSED** for the deterministic probe workload in default and enhanced modes. At that point, the broader performance workstream was **PARTIAL/OPEN** because the historical outlier was unlocalized, Composer-side timing was absent, and continuous workload frame pacing had not yet been measured. The 2026-11-03 continuous-rendering update below adds that workload and its observed frame pacing; the remaining performance gaps still prevent closure. The separate exact-output zero-copy bridge remains deferred.

## Continuous rendering and compositor comparison (2026-11-03)

The same diagnostic Android marker View accepts `--animation-hz 30` or `60`; the default remains static/input-driven (`0`). The original driver used `postInvalidateDelayed`; later measurements changed it to frame-aligned `postInvalidateOnAnimation` with a monotonic target-period gate and an opt-in, low-rate draw checkpoint. APKs were built locally and installed through the existing diagnostic overlay. This remains test-only; no base-image or rendering-pipeline code changed. Frame statistics and raw-log hashes are in [the performance acceptance record](../../results/post-m1e/graphics-performance/acceptance.json) and [the compositor record](../../results/post-m1e/compositor-portability/acceptance.json).

These are short diagnostic runs. Presented FPS is computed from compositor presentation timestamps, and interval percentiles are within that compositor's feedback clock. They are not directly comparable where backends differ.

| Compositor/backend | Requested | Presented FPS | Presented interval p50 / p95 / p99 / max | Committed / presented / discarded | Staging p50 / p95 / max |
|---|---:|---:|---:|---:|---:|
| KWin 6.7.5, host session | 30 Hz | 25.08 | 33.340 / 66.663 / 66.672 / 66.678 ms | 647 / 644 / 3 | 1.422 / 2.137 / 4.134 ms |
| KWin 6.7.5, host session | 60 Hz | 45.03 | 16.668 / 33.343 / 50.005 / 50.009 ms | 1498 / 1430 / 68 | 1.384 / 1.955 / 3.819 ms |
| KWin 6.7.5, enhanced dual-display session | 30 Hz probe | 31.21 | 33.331 / 50.003 / 66.669 / 133.336 ms | 1108 / 1107 / 1 | 2.810 / 4.670 / 7.430 ms |
| KWin 6.7.5, enhanced dual-display session | 60 Hz probe | 31.40 | 33.331 / 50.002 / 66.663 / 83.329 ms | 1103 / 1103 / 0 | 3.010 / 4.948 / 7.372 ms |
| Weston 15.0.1, nested Wayland + llvmpipe | 30 Hz | 24.69 | 42.334 / 61.414 / 66.692 / 79.330 ms | 583 / 582 / 1 | 1.487 / 2.075 / 3.695 ms |
| Sway 1.12, nested Wayland + GLES/llvmpipe | 30 Hz | 24.27 | 42.452 / 57.073 / 61.135 / 86.696 ms | 1218 / 1217 / 1 | 1.258 / 1.735 / 5.324 ms |
| Sway 1.12, nested Wayland + GLES, two windows | 30 Hz | 31.64 / 30.58 | 33.330 / 50.004 / 66.663 / 66.673 ms (unresized window) | 2795 / 2755 / 40 (unresized); resized window stopped after stale-size rejection | 1.307 / 1.852 / 4.342 ms (unresized) |

KWin and Sway use presentation clock ID 1 (`CLOCK_MONOTONIC`). Nested Weston uses ID 4 (`CLOCK_MONOTONIC_RAW`); its within-run interval distribution is valid, but commit-to-feedback subtraction against presenter `CLOCK_MONOTONIC` is unavailable. Sway reported no refresh interval for its nested output. Weston reported 16.667 ms. No missed-refresh count is inferred from intervals alone. Presenter process peak RSS was about 287 MiB; its user+system CPU time ranged from 1.23 to 4.75 seconds for these runs. Android-wide CPU/PSS and host-compositor CPU attribution were not captured, so these are not whole-runtime efficiency measurements.

The enhanced-mode KWin session ran the 30 Hz and 60 Hz probes simultaneously on two Android displays for 31.6 seconds. It presented at 31.21 and 31.40 FPS respectively; the concurrent 30/60 workload is not directly comparable to the single-display default sessions. Start/end memory availability stayed around 9.4/9.3 GiB, the observed cgroup OOM-kill count was zero, both presenters had zero outstanding buffers, and the per-session enhanced cgroup was removed at shutdown. Per-presenter staging p95 was 4.670/4.948 ms under this concurrent load.

The KWin 60 Hz target presented 45.03 FPS and discarded 68 of 1498 submitted frames. This is a measured cadence shortfall, not a pass against a 60 FPS target. The staging path remained low-millisecond; Android/Composer scheduling and compositor work are not instrumented on a correlated frame clock, so no production bottleneck or safe optimization is established. No production optimization was made.

### Frame-aligned probe follow-up (2026-11-03)

Two additional default KWin sessions used the frame-aligned driver and low-rate `onDraw` checkpoints (one checkpoint per 60 View draws). The 60 Hz session (`m1b84_session_7xwxyd3w`, APK SHA-256 `f82ade2ec6f61a2c138d1db699f5659864c0fc2efd0622343589167dd151e633`) logged 27 checkpoints; their median spacing was 1.830 s, corresponding to an estimated 32.79 `onDraw` callbacks/s. The presenter reported 1,659 presented frames over 45.15 s (31.58 FPS), with 1 discarded frame and staging p50/p95/max of 2.624/4.181/6.576 ms. The 30 Hz session (`m1b84_session_2rh09tre`, APK SHA-256 `d637df8aa9abc971aabe32ae2dde3d091f6fc74e6cf88582cc142af5f0c4deb2`) logged 25 checkpoints; median spacing was 1.807 s (estimated 33.21 `onDraw` callbacks/s). The presenter reported 1,524 presented frames (32.22 FPS), with 1 discarded frame and staging p50/p95/max of 2.621/4.253/7.130 ms. Checkpoints are a sampled View-draw rate, not exact frame identities; they establish that the app draw cadence itself was about 33/s in these runs.

The corrected driver did not recover the requested 60 Hz rate. The close agreement between sampled `onDraw` cadence and presenter presentation rate, with only one discarded frame and low-millisecond staging, places the observed shortfall at or before the Android View draw boundary for these runs. It does not identify whether Choreographer, app scheduling, SurfaceFlinger, or another upstream component limited draws; no Composer-correlated timing was captured. No production graphics bottleneck or safe optimization is established. The 60 Hz acceptance gate remains failed, and the 30 Hz result is measured rather than accepted against an explicit cadence tolerance.

### Compositor outcome

- **KWin:** the established baseline rendered 30 and 60 Hz animation, returned presentation feedback, and shut down with balanced imports/submissions/releases and zero outstanding buffers.
- **Weston:** the nested Wayland backend imported real Android DMA-BUF frames, presented continuous probe frames, and separately displayed two Android windows. Its 30 Hz run ended with one final buffer invalidated at client teardown (`teardown_invalidated=1`, outstanding=0). Full resize/input/lifecycle acceptance was not completed; this is nested llvmpipe coverage, not native-output performance evidence.
- **Sway:** two real Android windows mapped under the direct nested Sway compositor and both presented the continuous probe. A deliberate resize of one window from 420×740 to 500×740 caused the broker and Android display metrics to move to 500×740 while Composer frames remained 720×1280. The presenter rejected the stale-generation buffers; that window then stopped producing accepted frames. The other window continued presenting. This is a reproduced resize/convergence failure, not a reason to weaken stale-buffer checks. Sway therefore remains unaccepted for full portability.
- **Hyprland and Mutter:** binaries are absent from the host; no live runtime validation was performed. They are unverified.

Weston and Sway were extracted into the external workspace and run nested over the existing KWin session; no host compositor or system packages were replaced. The Sway/Weston measurements are not a matched native-compositor comparison. The external workspace guard passed at 56,056,196,096 bytes used with 314,844,061,696 bytes free.

The broader performance workstream remains **PARTIAL/OPEN**: the continuous workload is measured, but the 60 Hz target did not meet cadence, Composer/Android timing and whole-runtime resource attribution are missing, and the historical 326.704 ms stall remains OPEN/UNRESOLVED. Cross-compositor portability remains **PARTIAL/OPEN** because Sway resize convergence failed and Weston has incomplete behavior coverage. The integrated milestone is not closed. Exact-output zero-copy remains deferred.

## Repeatable input-to-presentation measurement (2026-11-03)

A minimal permission-free Android View probe replaces app-navigation timing for the causal measurement. A rootless `/dev/uinput` pointer-down enters the active native KWin surface, reaches the existing presenter listener and Android input adapter, and increments an eight-bit marker rendered by Android. The bounded ROI `(0,40,512,160)` changes on each event. Acceptance joins the same input sequence to a successful adapter DOWN injection, changed source-frame ROI, frame generation/ID, Wayland commit, and KWin `wp_presentation` feedback. Host, presenter, and feedback timestamps use `CLOCK_MONOTONIC` (feedback clock ID 1); reported presentation is compositor feedback, not photon timing. The probe APK is injected only as an explicit read-only diagnostic overlay; the base image and normal runtime are unchanged.

| Mode | Valid / attempted | Input→commit p50 / p95 / max | Input→presentation p50 / p95 / max | ROI cost p50 / max |
|---|---:|---:|---:|---:|
| Default, session `m1b84_session_hpavk5em` | 31 / 31 | 49.40 / 59.67 / 62.99 ms | 75.78 / 98.47 / 100.46 ms | 0.384 / 0.691 ms |
| Enhanced, session `m1b84_session_xt7cizwp` | 31 / 31 | 47.25 / 69.96 / 74.86 ms | 79.05 / 94.26 / 105.95 ms | 0.399 / 1.161 ms |

These are 31 serial pointer responses per mode on Android display 2, not a broad application responsiveness guarantee. Each run had 31/31 successful DOWN injections, changed ROI states, and matching presented feedback; no samples were rejected. The previous 457.251 ms Settings navigation sample remains separate and is not pooled with this lightweight workload. Enhanced cgroup OOM counters were zero and the session cgroup was removed. Both sessions stopped cleanly with balanced presenter imports/submissions/releases and zero outstanding buffers or pending presentation feedback.

A separate two-window input probe confirmed clicks reached both display-specific adapters, but neither marker changed, so it remains excluded and does not establish dual-display visual correlation. No production graphics optimization was justified. Per-event records and raw-log SHA-256 references are in `results/post-m1e/graphics-performance/runs/input-response-probe-{default,enhanced}.json`; the excluded dual-display attempt is separately recorded. The input-latency measurement task is **PASS/CLOSED**. Continuous frame pacing was subsequently measured in the 2026-11-03 update below. The broader graphics-performance workstream remains **PARTIAL/OPEN** because the historical 326.704 ms staging event is unresolved, the 60 Hz target fell short, and Composer-side/whole-runtime attribution remains incomplete. The historical staging incident remains **OPEN/UNRESOLVED**.
