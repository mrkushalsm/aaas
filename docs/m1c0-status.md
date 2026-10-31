# M1C.0 — Wayland pointer input into Android InputManager

Status: **PASS**  
Date: 2026-10-28  
Baseline: `39c6f1040cfb972adedd79c59c281948187c2164` (M1B.8.6)  
Final run: `/run/media/mrkus/Homework/aaas-workspace/tmp/m1b84_session_5lvw_x0t`  
Evidence: `results/m1c0/`

## 1. Result

A real Wayland pointer click on the AaaS window now reaches Android's real
input path and changes Android UI:

1. KWin delivers ordinary `wl_pointer` enter, motion, button, leave events to
   the AaaS surface.
2. The host presenter maps surface-local coordinates to Android display pixels.
3. It sends a fixed-size, versioned packet over a private `SOCK_SEQPACKET`
   socket to the Android container.
4. The Android adapter validates the packet and injects
   `MOVE`, `DOWN`, and `UP` through
   `/system/bin/cmd input -d 0 motionevent ...`.
5. Android's InputManager/InputDispatcher dispatches the click to Settings.
6. The resulting `Network & internet` page is rendered through the existing
   Composer3/DMA-BUF/SwiftShader/Wayland path.

In the final run, a click at Android display `(310,393)` changed
`topResumedActivity` from the Settings home activity to
`com.android.settings/.SubSettings` and rendered:

```text
Network & internet
Internet
Networks available
```

The presenter presented 313 frames with 0 rejects after the click. No host
global input capture, `sudo`, privileged helper, or direct activity launch was
used.

## 2. Why this is a real input path

The adapter does not call a Settings activity, does not use a host-side UI fake,
and does not write to a test-only Android view. It executes Android's public
command surface with a fixed argv:

```text
/system/bin/cmd input -d 0 motionevent MOVE|DOWN|UP <x> <y>
```

`cmd input` is an Android platform command that goes through `IInputManager`
and the normal InputDispatcher path. The adapter uses `execv` directly, not a
shell, and accepts no package names, activity names, or arbitrary commands.
The only variable arguments are the validated motion type and bounded display
coordinates.

## 3. Architecture

```text
KWin compositor
    │  wl_pointer enter/motion/button/leave
    ▼
wayland-host-presenter (host, user)
    │  wl_seat + wl_pointer
    │  surface -> display mapping
    │  68-byte input_v1 packets
    ▼
ipc/input.sock  ==bind mount==>  /dev/aaas/input.sock
    │  private AF_UNIX SOCK_SEQPACKET
    ▼
aaas-input-adapter (Android container)
    │  validate session/display/focus/sequence
    │  fixed execv argv
    ▼
/system/bin/cmd input -d 0 motionevent ...
    │
    ▼
Android InputManager -> InputDispatcher -> Settings
```

The input socket is deliberately separate from the wire protocol v2
frame/release socket. Pointer traffic cannot consume a frame-release packet.

### Host-side files

- `experiments/m1a/src/input_v1.h`, `input_v1.c` — wire format and validation.
- `experiments/m1a/src/input_map.h`, `input_map.c` — viewport-aligned mapping.
- `experiments/m1a/src/input_state.h`, `input_state.c` — receiver ordering.
- `experiments/m1a/src/gpu_presenter.c` — `wl_seat`/`wl_pointer`, mapping,
  input socket accept/read, lifecycle handling.
- `experiments/m1a/src/wayland_host_presenter.c` — `--input-socket` and
  `--input-session` options, socket creation.
- `experiments/m1a/src/gpu_presenter.h` — optional input configuration.

### Android-side files

- `experiments/m1c/input_adapter/aaas_input_adapter.c` — persistent adapter.
- `experiments/m1c/input_adapter/Makefile` — Bionic PIE build.

### Session orchestration

- `scripts/run_aaas.py` — generates a random 64-bit session token, creates the
  adapter log, passes the input socket/session to the presenter, binds the
  adapter and log into the generated runner, and starts the adapter after
  Settings launches.
- `scripts/test_zygote_startup.py` is not edited. `run_aaas.py` still transforms
  a hash-checked copy.

## 4. Protocol

All fields are little-endian on the wire. The packet is exactly 68 bytes.

| Field | Size | Meaning |
|---|---:|---|
| `magic` | 4 | `0x49414141` |
| `version` | 2 | `1` |
| `type` | 2 | HELLO=1, FOCUS=2, MOTION=3, BUTTON=4, SHUTDOWN=5 |
| `length` | 4 | 68 |
| `sequence` | 4 | strictly increasing per connection |
| `display_id` | 4 | 0 for the AaaS display |
| `display_generation` | 4 | presenter configure generation |
| `timestamp_ns` | 8 | `CLOCK_MONOTONIC` |
| `session_id` | 8 | random per-session token |
| `x`, `y` | 4+4 | Android display pixels |
| `button` | 4 | `BTN_LEFT`=0x110, `BTN_RIGHT`=0x111, `BTN_MIDDLE`=0x112 |
| `state` | 4 | focus or button state |
| `focus_generation` | 4 | increments on focus enter/leave |
| `flags` | 4 | ACK only |
| `reserved` | 4 | must be zero |

Validation rejects:

- wrong magic, version, or length;
- unknown message type;
- stale/wrong session token;
- wrong or out-of-range display id;
- missing display generation;
- negative or oversize coordinates;
- unsupported button or state;
- ACK on a non-HELLO message;
- unknown flags or nonzero reserved.

The receiver state additionally rejects:

- any non-HELLO message before HELLO;
- sequence zero, replay, or regression;
- stale display generation;
- stale focus generation;
- unexpected HELLO ACK.

Sequence and generation state reset when a new adapter connects.

## 5. Coordinate mapping

The presenter sets the Wayland viewport destination to the configured surface
size, stretching the complete source rectangle on each axis. Input coordinates
therefore use the same independent x/y scale. During a resize, pointer mapping
is rejected until an Android source frame matching the configured surface is
active; an older frame remains visible through the viewport but its coordinates
do not correspond to the newly resized Android display. Points are floored and
clamped to display bounds; exact right and bottom edges are outside.

Tested cases include identity, half size, double size, nonuniform viewport
stretch, odd heights, exact edges, negative points, zero dimensions, and the
matching-frame readiness gate.

## 6. Lifecycle behavior

- **Pointer enter**: send FOCUS ENTER and begin forwarding.
- **Pointer motion**: send MOTION; while a button is held, the adapter injects
  Android `MOVE`.
- **Pointer button**: send BUTTON press/release; release without a matching
  press is ignored.
- **Pointer leave**: release any pressed buttons first, then send FOCUS LEAVE.
- **Move outside surface**: same release-then-leave behavior. During a resize,
  pointer events are withheld until a matching Android source frame is active.
- **Seat removal / pointer capability loss**: release buttons, leave focus,
  unbind pointer.
- **Adapter connect**: send HELLO (display dimensions and generation), then
  re-send FOCUS ENTER if the pointer is already inside. This closes the
  adapter-startup race observed during bring-up.
- **Adapter disconnect/EOF**: presenter closes the channel and tears down.
- **Presenter shutdown**: send SHUTDOWN before closing; adapter releases
  pressed buttons and exits.
- **SIGTERM/SIGINT**: adapter sets a stop flag, releases pressed buttons, and
  exits.
- **Malformed traffic**: adapter logs and counts invalid messages; after eight
  invalid messages it exits.

A bring-up test found that the adapter checked focus before handling
`SHUTDOWN`, so an unfocused adapter ignored the shutdown packet and only exited
on EOF. The check was moved ahead of the focus gate; the final run logs
`shutdown_received` and then `stop`.

## 7. Live acceptance evidence

### Final run

Command:

```bash
python3 scripts/run_aaas.py --use-source-lmkd --memory-policy=cgroup
```

Test input was generated by a disposable host `uinput` pointer. This harness is
not part of production input collection; it only moves the host cursor over the
real AaaS window and clicks. The presenter still receives normal KWin
`wl_pointer` events.

Host target:

```text
window origin (320,218), size 1280x720
Android target (310,393)
host target (630,611)
```

Presenter evidence:

```text
input_pointer_enter surface=(310.000,393.000) mapped display=(310,393)
input_sent type=BUTTON state=PRESSED  x=310 y=393
input_sent type=BUTTON state=RELEASED x=310 y=393
input_pointer_leave
input_sent type=SHUTDOWN
summary: presented=313 rejected=0 input_sent=6 input_dropped=0
```

Adapter evidence:

```text
hello display_generation=1 width=1280 height=720
focus_enter
inject MOVE x=310 y=393 rc=0
inject DOWN x=310 y=393 rc=0
inject UP   x=310 y=393 rc=0
focus_leave
shutdown_received
stop
```

Android evidence:

```text
topResumedActivity=com.android.settings/.SubSettings
START u0 { ... cmp=com.android.settings/.SubSettings ... } from uid 1000
```

OCR of the rendered window after the click:

```text
Network & internet
Internet
Networks available
```

Before/after screenshots are in `results/m1c0/screens/`.

### Held-button/focus-loss test

The pointer was pressed on a blank area, then moved outside the AaaS window
while still held. The presenter synthesized the button release before leaving:

```text
input_sent BUTTON PRESSED  sequence=8
input_sent BUTTON RELEASED sequence=9
input_buttons_released reason="content_leave" buttons=1
input_sent FOCUS LEAVE sequence=10
adapter: inject MOVE/DOWN rc=0, inject UP rc=0, focus_leave
```

The host button-release event after leaving was ignored by the presenter because
the pointer focus was already gone. Android still received the synthesized
release, so no stuck button remained.

### Default launcher regression

`python3 scripts/run_aaas.py` (no memory-policy options) started the adapter,
completed HELLO/ACK, presented 245 frames with 0 rejects, and shut down cleanly:

```text
input_adapter_connected
input_adapter_ready
summary: presented=245 rejected=0 input_sent=2 input_dropped=0
adapter: shutdown_received, stop
```

## 8. Tests

### C tests

```text
make -C experiments/m1a test
```

All inherited tests plus:

- `test-input-map`: 19 mapping cases.
- `test-input-v1`: magic/version/length/type/session/display/coordinate/button/
  state/flags/reserved/ACK validation.
- `test-input-state`: sequence zero/replay/regression, stale display generation,
  stale focus generation, uninitialized receiver, unexpected HELLO ACK, and
  reconnect reset.

Result: **PASS**.

### Python tests

```text
python3 -m unittest discover -s tests -v
```

Result: **112 tests OK**. This includes the new
`test_runner_binds_adapter_and_starts_private_input_channel` test, which checks
the generated runner's adapter bind, log bind, socket, session file, and start
command.

### Workspace check

```text
AAAS_WORKSPACE=/run/media/mrkus/Homework/aaas-workspace \
  python3 scripts/android_workspace.py check
```

```text
used_bytes      18,739,453,440
free_bytes     352,160,677,888
ceiling_bytes   85,899,345,920
reserve_bytes   21,474,836,480
```

Result: **PASS**.

## 9. Preservation

The five inherited M1B.8 files were not modified:

```text
experiments/m1b/shim_selinux.c
scripts/test_zygote_startup.py
docs/m1b8-status.md
experiments/m1b/shim_dns_helper.c
experiments/m1b/shim_netd_updatable.c
```

Their SHA-256 values match `results/m1c0/preservation_manifest.json` exactly.
The source-built LMKD and delegated cgroup v2 policy remain in place; the final
run used `--use-source-lmkd --memory-policy=cgroup`, created the session
hierarchy, and removed it during shutdown.

## 10. Limitations

- `cmd input` spawns one child process per injected Android event. This is
  simple, uses the real input path, and is adequate for M1C.0, but it is not a
  high-rate input implementation.
- Only Android display 0 is supported.
- Only left, right, and middle buttons are forwarded. Wheel/scroll and
  multi-touch are not part of M1C.0.
- Hover-only motion is logged but not injected; motion is injected as Android
  `MOVE` only while a button is held.
- The test-only `uinput` harness moves the host cursor. The production input
  source is still surface-local `wl_pointer` events from KWin.
- The inherited M1B.8.6 watchdog/storage and rootless memory-policy limitations
  are unchanged.

## 11. Evidence index

```text
results/m1c0/
├── acceptance.json
├── hashes.txt
├── preservation_manifest.json
├── workspace-check-final.json
├── screens/
│   ├── 01-settings-before.png
│   ├── 01-settings-before-window.png
│   ├── 02-network-internet-after.png
│   └── 02-network-internet-after-window.png
├── final-run/
│   ├── presenter.log
│   ├── presenter-input-events.jsonl
│   ├── input-adapter.log
│   ├── adapter-events.jsonl
│   ├── top-activity-after.txt
│   ├── activity-log.txt
│   ├── before-ocr.txt
│   ├── after-ocr.txt
│   ├── state.jsonl
│   ├── status.txt
│   └── launcher.log
├── lifecycle/
│   ├── held-button-presenter.jsonl
│   ├── held-button-adapter.jsonl
│   ├── final-shutdown-presenter.jsonl
│   └── final-shutdown-adapter.jsonl
├── default-regression/
│   ├── presenter.log
│   ├── input-adapter.log
│   └── launcher.log
└── test-output/
    ├── python-unittest.log
    └── m1a-make-test.log
```
