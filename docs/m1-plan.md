# M1 experiments and stop gates

Order reflects dependencies; each result gets a dated directory with command transcript, exact source IDs, host capture, stdout/stderr, and a pass/fail/blocked decision.

| Experiment | Pass | Fail | Stop/block |
|---|---|---|---|
| E1 Lipstick simplecompositor | x86_64 nested compositor, two clients, focus/resize/close, no phone daemon | Requires permanent phone services or substantial compositor rewrite | Missing safe Qt5 private modules; do not alter system graphics stack |
| E2 Qt HWC compatibility | Plugin loads and virtual HWC exchange without reverse-direction adapter or extra full-frame pass | Inversion or duplicate composition required | Android header/libhybris ABI not pinned |
| E3 Composer3 client target | Settings in resizable xdg_toplevel, 10k correct fence frames, zero CPU copies | Broken lifetime/geometry/fence | No reproducible Android image/manifest or Binder permission model |
| E4 DMA-BUF sync | 300k three-buffer transitions, no premature reuse/wrong release/stale generation | Any invariant breach | Missing test GPU/protocol negotiated safely |
| E5 direct layer/fallback | Same producer/import buffer identity and zero blits; unsupported cases fall back cleanly | Copy on nominal path or corruption on fallback | Protected content cannot be exported; document unsupported |
| E6 Digitalis/Teto | ARM64-only JNI corpus works on proven x86_64 Android image | Translator crash or JNI/signal mismatch | AOSP 16 manifest and test APK/toolchain not frozen |
| E7 LXC vs namespaces | Same image/devices/readiness, 30 runs, security model reviewed | Non-comparable setup or unsafe privilege requirement | Would require disabling host controls |
| E8 lifecycle/baselines | Stopped/warm/frozen launch to first presentation; Waydroid/Droidloom on same hardware | Missing presentation evidence or apples-to-oranges configs | Build/image unavailable, record unavailability |

First M1 experiment: resolve Lipstick simplecompositor's Qt5 compositor/private module requirements in an isolated build environment and run two nested Wayland clients. If this requires host-wide Qt replacement or mobile daemons, stop and report the dependency boundary.

M0.1 preflight stopped at that boundary: the pinned Sailfish QtWayland fork declares 5.6.3 and its compositor target does not compile with the isolated Qt 5.15.8 toolchain; `mlite5` and other Sailfish packages are absent. The first M1 task must establish an x86_64 compatible Sailfish Qt toolchain and real package closure before attempting `nested_test.py`. The prepared harness is not runtime evidence.

## M1A path update (2026-10-25)

The Lipstick E1 dependency investigation remains preserved in `docs/lipstick-m01.md` and `results/m01/lipstick/`, but it is no longer on the critical path. The independent host transport experiment in `docs/m1a-transport.md` now precedes Composer3 work. It uses the desktop compositor as a client and has no Sailfish package dependency.

M1A has a live DMA-BUF producer/presenter trace and automated transport/release tests, but its full gate is incomplete. Next: exercise user-driven resize/close and compositor loss, capture visual evidence and FD/resource deltas, then test explicit GPU synchronization with an actual GPU writer. Composer3 remains deferred until those host-side guarantees are understood.
