# M1C.1 — Binder-backed pointer and scroll input

Status: **PARTIAL — pointer and Android scroll delivery work; physical scroll visibility not fully confirmed**
Date: 2026-10-29
Implementation commits: `556d3d0` (`feat(input): preserve pointer and scroll semantics on Android`), with the scroll correction described below
Live session: `/run/media/mrkus/Homework/aaas-workspace/tmp/m1b84_session_yert8z49`
Evidence: `results/m1c1/live/`

## Acceptance results

| Gate | Status | Evidence |
| --- | --- | --- |
| Private input adapter startup and HELLO | PASS | Presenter recorded adapter connected/ready; adapter validated HELLO and selected the Binder backend. |
| Host pointer click reaches Android | PASS | Disposable host uinput click generated Wayland button press/release; adapter recorded Binder DOWN and UP, each with `rc=0`. |
| Vertical scroll transport | PASS | Wayland presenter emits axis values in input protocol v1; Android adapter receives and validates the packet. |
| Android view scroll via hand-built Binder parcel | FAIL | Binder returned success, but Android Settings screencaps were pixel-identical before and after the event. This corrects the previous report, which treated Binder success as functional scrolling. |
| Android Settings scroll via framework event builder | PASS | Adapter now routes `ACTION_SCROLL` through `/system/bin/cmd input <mouse|touchpad> scroll ...`; an input-socket integration event moved the actual Settings homepage. `socket-before.png` and `socket-after.png` differ in 135,837 pixels (bbox `(42,315)-(1238,720)`). |
| Physical mouse-wheel visual movement after fix | NOT VERIFIED | Live host events reached the adapter and used the new `cmd` backend, but the captured samples were upward values while the page was already at its upper edge. They did not prove a visible movement for a downward physical wheel gesture. |
| Horizontal UI movement | NOT VERIFIED | The Settings homepage has no horizontally scrollable content in the tested view. Horizontal axis transport is supported by the protocol, but a visible Android horizontal-scroll target was not exercised. |
| Physical touchpad scrolling | NOT VERIFIED | The host reports an ITE5570 touchpad, but no physical finger gesture was available during the captured run. |
| Presenter/frame and cleanup | PASS | Presenter summary: 395 frames presented, 0 rejected, 18 input packets sent, 0 input drops. Adapter disconnected on presenter shutdown; delegated cgroup policy cleanup reported `removed=true` and no failures. |

The native Binder parcel reader was compared with Android 16 `MotionEvent` parcel
serialization and its field ordering is structurally valid. Nevertheless, the
live Binder scroll was accepted without changing the target view. The focused
correction uses Android's own `InputShellCommand` builder for scroll events,
while leaving the existing native Binder path in place for clicks, hover, and
drag. The Settings pixels changed through the Android adapter after the
framework-built scroll. A post-fix physical downward wheel movement and a
physical touchpad gesture still require separate verification before the full
M1C.1 scrolling requirement can be marked complete.

See `results/m1c1/live/scroll-regression/scroll-fix.json` for live evidence and
the before/after capture hashes.

## Evidence files

- `acceptance-live.json` — summarized gates and counts.
- `click-probe.jsonl`, `scroll-probe.jsonl` — disposable host-side uinput actions.
- `presenter-input.jsonl`, `adapter-input.jsonl` — filtered live presenter and
  Android adapter event logs, including the final presenter summary.

The host probes are test-only; production input remains surface-local Wayland
`wl_pointer` events. The implementation supports display 0 and left, right,
and middle mouse buttons; it does not implement touch or multi-touch.

## Verification

- `make -C experiments/m1a all test` — PASS, including mapping, protocol,
  ordering/state and existing graphics/synchronization tests.
- `make -B -C experiments/m1c/input_adapter all` — PASS; rebuilt the Android
  adapter and Binder injector with `-Wall -Wextra -Werror`.
- `python3 -m unittest discover -s tests -v` — PASS, 112 tests.

One initial full-suite run overlapped the live launcher, so the test that
acquires the launcher's single-instance lock failed as expected while the live
session held it. The suite was rerun after session cleanup and all 112 tests
passed.
