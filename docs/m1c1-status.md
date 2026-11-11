# M1C.1 — Binder-backed pointer and scroll input

Status: **PASS / CLOSED**
Date: 2026-10-29
Implementation commits: `556d3d0`, `d25a142`, `e32185f`, `de4dc98`, `7c6e897`, `73e3f80`, and `6513f5e`.
Live session: `$AAAS_WORKSPACE/tmp/m1b84_session_yert8z49`
Evidence: `results/m1c1/live/`

## Acceptance results

| Gate | Status | Evidence |
| --- | --- | --- |
| Private input adapter startup and HELLO | PASS | Presenter recorded adapter connected/ready; adapter validated HELLO and selected the Binder backend. |
| Host pointer click reaches Android | PASS | Disposable host uinput click generated Wayland button press/release; adapter recorded Binder DOWN and UP, each with `rc=0`. |
| Vertical scroll transport | PASS | Wayland presenter emits axis values in input protocol v1; Android adapter receives and validates the packet. |
| Android view scroll via hand-built Binder parcel | Diagnostic path rejected | Binder returned success, but Android Settings screencaps were pixel-identical before and after the event. The implementation uses Android's framework-built event path instead, which moves the actual view. |
| Android Settings scroll via framework event builder | PASS | Adapter now routes `ACTION_SCROLL` through `/system/bin/cmd input <mouse|touchpad> scroll ...`; an input-socket integration event moved the actual Settings homepage. `socket-before.png` and `socket-after.png` differ in 135,837 pixels (bbox `(42,315)-(1238,720)`). |
| Physical mouse-wheel scrolling | PASS | User confirms mouse-wheel scrolling works; the live adapter records mouse-source events through Android's framework-built event path. |
| Horizontal UI movement | PASS — user confirmed | User confirmed horizontal scrolling in the final portrait session. Earlier automated Settings captures did not exercise a horizontal-scroll target. |
| Physical touchpad scrolling | PASS | A live session delivered 312 Wayland `axis_source=finger` packets as 222 Android injections. Correlated Android client-target captures show the Settings list moving to lower rows. |
| Touchpad event backlog | IMPROVED | Matching adjacent touchpad deltas are coalesced. A 16-packet burst became two Android injections (1 + 15); both succeeded. The child wait polling interval is 1 ms instead of 5 ms. |
| Settings back-button mapping | PASS | A host click at surface `(84.91,143.24)` on `1280x720` mapped 1:1 to Android `(84,143)` and returned from Network & internet to the homepage. |
| Display flicker and tearing | PASS — user confirmed | User confirmed the release-timeline fix in `6513f5e` removed the previously visible flicker and tearing during boot and Settings navigation. The fix holds each source buffer until its explicit Wayland release timeline point completes. |
| Portrait Android display | PASS — user confirmed and runtime recorded | Default session profile is 720×1280. The Composer reports the same dimensions and the Wayland presenter accepted portrait frames without format rejection. |
| Input readiness before Settings launch | PASS — user confirmed and runtime ordering tested | The adapter starts before the Settings activity command; the foreground launcher reports adapter HELLO readiness independently, so input is available before the later process-ready message. |
| Subpage scrolling and button responsiveness | PASS — user confirmed | User confirmed scrolling and button response across Settings navigation in portrait mode. The screencast evidence also shows movement on the Display page and main list; its Internet page had only one row and was not scrollable. |
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

## Hover/flicker follow-up (2026-10-29)

On the `e32185f` scroll baseline, rapid host pointer motion was still forwarded
as Android `HOVER_ENTER`, `HOVER_MOVE`, and `HOVER_EXIT` events using a synthetic
pointer with no stable Android device identity. Earlier logcat evidence showed
InputDispatcher rejecting repeated hover transitions for that pointer. The
input adapter now tracks focus locally and leaves unpressed pointer motion in
Wayland; Android still receives button events, drag `MOVE`, and scroll events.
This removes the invalid hover stream without changing scroll or frame-buffer
synchronization.

The rebuilt adapter was exercised in live Android session
`m1b84_session_rfdmpx_b`. It delivered 126 successful mouse scroll injections,
submitted 617 frames (589 presented, 28 discarded), and shut down cleanly.
That run's logcat contained no `HOVER_MOVE`, `HOVER_ENTER`, `HOVER_EXIT`,
`Invalid HOVER_ENTER`, Scudo error, or fatal-signal records. These results
validate the input-stream correction. They do **not** prove that all perceived
flicker is fixed: the capture was not a video of the AaaS window, and the boot
and activity-transition presentation path still needs direct visual
verification. The presenter already uses multiple in-flight buffers and
Wayland explicit-sync release points; adding another buffer layer without a
reproduced missing/partial frame would add latency without evidence it helps.

Structured run evidence: `results/m1c1/live/hover-flicker-rfdmpx_b.json`.

## Pointer-motion load follow-up (2026-10-29)

The presenter still sent every unpressed `wl_pointer.motion` sample over the
private Android input socket even though the Android adapter deliberately
ignored unpressed `AAAS_INPUT_MOTION`. The presenter now keeps those samples in
the Wayland cursor path and sends Android motion only during a held-button
drag. This removes unnecessary socket traffic and cannot reduce rendering
throughput; coordinates and focus tracking are still updated locally. A
regression test covers the forwarding guard.

In the live run `m1b84_session_ob22u_6u`, 1,200 unpressed pointer samples were
generated during five seconds; the session stayed RUNNING and shut down
cleanly. It submitted 891 frames, presented 867, released 890, discarded 24,
and rejected none. The adapter remained connected. This verifies runtime
survival and transport cleanup, but it does not prove that visible flicker is
gone. Android client-target samples remain complete; sampled changes during
Settings navigation correspond to the pressed ripple and page transition.
No direct recording of the Wayland window was obtained, so the flicker remains
unverified and this change is a targeted input-load reduction rather than a
claimed visual fix.

## Wayland release-timeline gating follow-up (2026-10-29)

The supplied screencast contains a diagonally split/corrupt presentation frame
during the Settings launch transition, with another brief corruption during a
subpage transition. The host presenter previously sent the transport release
as soon as it received `wl_buffer.release`, even when the explicit DRM
syncobj release point was still pending. AaaS treats that transport message as
slot availability, so this allowed the producer to recycle backing memory
before KWin's GPU read was complete. The presenter now defers transport
release until the per-buffer release timeline point signals, while retaining
the existing zero-copy DMA-BUF path and leaving frame submission frequency
unchanged. The full window is also declared opaque because each incoming
buffer is a complete Android display composition; this prevents transparent
startup pixels from revealing the desktop.

The rebuilt live run `m1b84_session_757yk26g` booted to the real Settings
homepage. During observation it recorded 265 commits, 263 presentation
feedback events, 264 transport releases, 2 discarded feedback events, and 0
rejected buffers. Ten early `wl_buffer.release` events were deferred pending
their explicit release timeline; all ten later received a transport release.
Every final release record asserts the release timeline was signaled. A fresh
active-window capture showed the Settings homepage. The run remained live for
manual interaction and had no presenter or Android runtime failure at capture.

This is a verified ownership/synchronization correction that directly matches
the tear mechanism visible in the supplied recording. Full visual flicker
elimination still requires observing subpage transitions and pointer movement
in the user's display; do not claim the flicker is fully resolved until that
review confirms it.

After rebuilding the final source state, a second clean Settings boot ran as
`m1b84_session_vnmdm9b8`. It recorded 269 commits, 268 presentation feedback
events, 268 transport releases, one discarded feedback event, and no rejected
buffers. Twenty-two `wl_buffer.release` notifications were held until their
explicit release points signaled, and all 22 subsequently released. The latest
Settings capture and machine-readable counts are retained under
`results/m1c1/live/release-timeline-gating-20261029.json`. It shut down cleanly.

The final rebuilt run `m1b84_session_n6j8anv8` was left open for review. It
recorded 269 commits, 269 presentation feedback events, 268 releases, no
discarded feedback events, no rejected frames, and six early release
notifications deferred until the explicit timeline completed (all six
resolved). Its binary hash/build ID and Settings screenshot are in the
structured result JSON.

## Final M1C.1 closure (2026-10-29)

The user has personally verified mouse clicks, dragging, mouse-wheel and
touchpad scrolling, horizontal scrolling, Settings subpage navigation and
button responsiveness, portrait rendering, input-bridge readiness, and stable
display without flicker or tearing. These are recorded as user-confirmed
acceptance, not as automated measurements. No new screenshot or event count is
claimed for those manual checks.

Portrait mode is the default for `python3 scripts/run_aaas.py` and uses a
720×1280 Composer configuration. `--orientation landscape` retains the
1280×720 profile. The launcher checks the portrait Composer binary checksum
before starting. The Android input adapter is started before the Settings
activity launch request; its HELLO is reported as “AaaS input bridge ready”
without waiting for the later process-ready message.

The final portrait smoke session was
`$AAAS_WORKSPACE/tmp/m1b84_session_hb9g11y9`. Its
presenter recorded 468 submissions, 451 presentation-feedback events, 467
transport releases, 17 discarded presentation-feedback events, zero rejected
buffers, and zero dropped input packets. The session entered RUNNING, then the
window close caused the launcher to stop Android and reach STOPPED. Its
structured summary is `results/m1c1/live/final-portrait-session-20261029.json`.
This smoke
run verifies portrait frame acceptance and window-close cleanup; its input
counter contains focus events and is not used as proof of the manual clicks or
scrolls.

Final checks:

- `python3 -m unittest discover -s tests -v` — PASS, 119 tests.
- `make -C experiments/m1a test` — PASS.
- `make -B -C experiments/m1c/input_adapter all` — PASS with `-Wall -Wextra -Werror`.
- Portrait Composer build (`AAAS_DISPLAY_WIDTH=720 AAAS_DISPLAY_HEIGHT=1280`) — PASS.
- `make -B -C experiments/m1a build/wayland-host-presenter` — PASS.
- Android workspace check — PASS; see `results/m1c1/workspace-check-final.json`.

Structured final acceptance is in `results/m1c1/acceptance.json`. Detailed
test output is retained in `results/m1c1/test-results-final.txt`. Earlier
diagnostic caveats above remain historical descriptions of what those runs
alone established; the final PASS incorporates the user's subsequent manual
visual and interaction verification.

Implementation closure commits:

- `de4dc98` — `feat(display): support portrait Android rendering`
- `7c6e897` — `fix(runtime): start portrait Settings sessions with input ready`
- `73e3f80` — `fix(input): coalesce adjacent scroll event bursts`
- `6513f5e` — `fix(graphics): acknowledge safe client target copies`
