# M1C.1 — Binder-backed pointer and scroll input

Status: **PASS for input transport and Android injection**
Date: 2026-10-29
Implementation commit: `556d3d0` (`feat(input): preserve pointer and scroll semantics on Android`)
Live session: `/run/media/mrkus/Homework/aaas-workspace/tmp/m1b84_session_yert8z49`
Evidence: `results/m1c1/live/`

## Acceptance results

| Gate | Status | Evidence |
| --- | --- | --- |
| Private input adapter startup and HELLO | PASS | Presenter recorded adapter connected/ready; adapter validated HELLO and selected the Binder backend. |
| Host pointer click reaches Android | PASS | Disposable host uinput click generated Wayland button press/release; adapter recorded Binder DOWN and UP, each with `rc=0`. |
| Vertical wheel reaches Android | PASS | Host `REL_WHEEL` probe; adapter recorded Binder SCROLL with `vscroll=1.0`, `hscroll=0.0`, `rc=0`. |
| Horizontal wheel reaches Android | PASS | Host `REL_HWHEEL` probe; adapter recorded Binder SCROLL with `vscroll=0.0`, `hscroll=1.0`, `rc=0`. |
| Presenter/frame and cleanup | PASS | Presenter summary: 395 frames presented, 0 rejected, 18 input packets sent, 0 input drops. Adapter disconnected on presenter shutdown; delegated cgroup policy cleanup reported `removed=true` and no failures. |

The click and both wheel directions were exercised twice during the same live
Android session. The scroll claims are limited to successful Android Binder
`IInputManager` injection (transaction returned success); a visible change in a
scrollable Settings view was not separately asserted.

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
