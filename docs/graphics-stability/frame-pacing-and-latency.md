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

This single sample proves the method, not a latency distribution. No enhanced-mode sample has been obtained, and p95/p99 are therefore unreported. A separate Connected devices click crashed Settings and remains excluded. X11 injection is not suitable for targeting the native Wayland surface. A later focused diagnostic (`m1b84_session_1el0zr2e`) shows that native pointer delivery does work when the AaaS toplevel is active: KWin delivered pointer motion/button events to the presenter and the display-specific Android input adapter completed injection with `rc=0`. When the toplevel was inactive/obscured, clicks did not reach that surface. The targeted Contacts click still produced no changed ROI frame, so this is not a valid latency sample; Android application handling and event-to-frame causality remain unestablished. The exact trace and hashes are in `runs/input-response-native-focus-attempt.json`. No production input or graphics policy was changed. Overall input measurement remains **PARTIAL/OPEN** until a bounded default dataset and enhanced-mode samples are collected.

Presenter receive-to-commit and commit-to-presentation are available for profiled frames. Android application update, SurfaceFlinger composition, Composer output-ready, and Composer mixed-operation timestamps are not emitted on a compatible frame clock in this runtime, so full app-to-display latency is unavailable. No cross-process timestamps are subtracted unless the request timestamp is explicitly copied across the boundary.

## Excluded low-memory input attempt

Session `m1b84_session_swvikvp2` is recorded as **FAILED**, not accepted: Android did not bring Settings to the ready state, so the real-input measurement never began. Android userspace LMKD killed Settings PID 3132 (uid 1000, `oom_score_adj=102`) because the minimum watermark was breached and swap was 1,396 kB, below its 801,380 kB threshold. It also killed other Android processes. Host swap free fell from 480,220 kB at startup to 7,616 kB at shutdown-begin, with elevated memory PSI; the AaaS cgroup had no memory limit and no cgroup OOM events. This was a legitimate pressure response, not evidence of an LMKD policy defect. The failure record and raw log hashes are in the structured acceptance JSON. This attempt is excluded from latency distributions and does not explain the historical 326.704 ms event.

A later default-mode input probe (`m1b84_session_slrcq4l5`) sent real Wayland pointer/key input through the AaaS adapter. Android launched Settings SearchActivity, and the adapter acknowledged packets, but visible Settings pixels remained unchanged; no affected frame could be causally identified. The exploratory full-frame hash cost 3.43–7.49 ms per frame, so its traces are excluded from timing. Input-to-presentation remains **NOT MEASURED**. Raw log hashes and the exact limitation are in `acceptance.json`.

## Optimization decision and status

No production performance optimization was justified by the bounded measurements. The common path is not shown to violate the host frame budget, and the one large historical stall lacks stage evidence. The instrumentation and analyzer are reusable and opt-in; existing AaaS synchronization and release invariants remain unchanged.

The overall performance workstream remains **PARTIAL/OPEN** because the historical outlier is unlocalized, Composer-side timing is absent, input-to-causally-affected-presentation is unavailable, and continuous workload frame pacing was not measured. These limitations are explicit in the structured record. The separate exact-output zero-copy bridge remains OPEN/BLOCKED and is outside this workstream.
