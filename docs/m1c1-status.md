# M1C.1 — Binder-backed pointer and scroll input

Status: **PARTIAL — mouse and physical touchpad scrolling work; user-reported flicker remains unclassified**
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
| Physical mouse-wheel scrolling | PASS | User confirms mouse-wheel scrolling works; the live adapter records mouse-source events through Android's framework-built event path. |
| Horizontal UI movement | NOT VERIFIED | The Settings homepage has no horizontally scrollable content in the tested view. Horizontal axis transport is supported by the protocol, but a visible Android horizontal-scroll target was not exercised. |
| Physical touchpad scrolling | PASS | A live session delivered 312 Wayland `axis_source=finger` packets as 222 Android injections. Correlated Android client-target captures show the Settings list moving to lower rows. |
| Touchpad event backlog | IMPROVED | Matching adjacent touchpad deltas are coalesced. A 16-packet burst became two Android injections (1 + 15); both succeeded. The child wait polling interval is 1 ms instead of 5 ms. |
| Settings back-button mapping | PASS | A host click at surface `(84.91,143.24)` on `1280x720` mapped 1:1 to Android `(84,143)` and returned from Network & internet to the homepage. |
| Display flicker | NOT REPRODUCED AS CORRUPTION | Sampled Android frames are complete and show expected Settings content. One run reported 776 presented and 39 discarded feedback events from 815 submissions (4.8%). This can contribute to stutter but does not establish visible flicker; the captures showed no blank or torn frames. |
| Presenter/frame and cleanup | PASS | Presenter summary: 395 frames presented, 0 rejected, 18 input packets sent, 0 input drops. Adapter disconnected on presenter shutdown; delegated cgroup policy cleanup reported `removed=true` and no failures. |

The native Binder parcel reader was compared with Android 16 `MotionEvent` parcel
serialization and its field ordering is structurally valid. Nevertheless, the
live Binder scroll was accepted without changing the target view. Android's
`ScrollView` handles `ACTION_SCROLL` axes only for `SOURCE_CLASS_POINTER`; the
touchpad source is position-class and was ignored. The adapter now normalizes
touchpad deltas to Android mouse scroll, while recording their Wayland origin,
and coalesces adjacent touchpad packets before invoking `cmd input`. Android
screenshots and presenter frame captures verify actual Settings movement.

The reported flicker was not reproduced as blank, torn, or corrupted pixels.
The observed 4.8% discarded presentation feedback may explain occasional
stutter, but it is not evidence of visible flicker by itself. If flicker
continues, a short video or timestamped reproduction is needed to distinguish
frame pacing from a blanking or content fault.

See `results/m1c1/live/scroll-regression/scroll-fix.json` for the earlier
framework-builder result and `results/m1c1/live/touchpad-routing.json` for the
touchpad source routing, coalescing, frame, and screenshot evidence.

## Evidence files

- `acceptance-live.json` — summarized gates and counts.
- `click-probe.jsonl`, `scroll-probe.jsonl` — disposable host-side uinput actions.
- `presenter-input.jsonl`, `adapter-input.jsonl` — filtered live presenter and
  Android adapter event logs, including the final presenter summary.
- `touchpad-routing.json` — live Wayland finger-axis packet counts, Android
  injection results, frame identifiers, and screenshot hashes.

The host probes are test-only; production input remains surface-local Wayland
`wl_pointer` events. The implementation supports display 0 and left, right,
and middle mouse buttons; it does not implement touch or multi-touch.

## Verification

- `make -C experiments/m1a test` — PASS, including mapping, protocol,
  ordering/state and existing graphics/synchronization tests.
- `make -B -C experiments/m1c/input_adapter all` — PASS; rebuilt the Android
  adapter and Binder injector with `-Wall -Wextra -Werror`.
- `python3 -m unittest discover -s tests -v` — PASS, 115 tests.
- Live foreground session — PASS; Settings reached RUNNING, then Ctrl+C reached
  STOPPED and the presenter/input adapter exited.
- Touchpad protocol probe — PASS; 24 finger-axis deltas resulted in two Android
  `cmd input mouse scroll` events and 302,201 changed screen pixels.

Earlier runs of the suite had overlapped the live launcher; this verification
was run after both live sessions had shut down cleanly.
