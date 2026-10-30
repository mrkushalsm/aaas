# M1E interfaces and identity model

Status: **two concurrent virtual-display output streams implemented; per-window
input and lifecycle protocol remain incomplete**

## Current bounded two-output prototype

The default path is still the established primary display. The opt-in
`--experimental-virtual-display` path adds one output per selected app without
changing primary wire protocol v2:

1. A session-local init service runs the AaaS display broker as Android system
   UID. It creates one or two trusted, private, own-content Android
   `VirtualDisplay` instances with separate broker-owned `ImageReader` surfaces.
2. Android assigns the display ID; the broker publishes it only to the private
   session files. The launcher starts the selected resolved Activity on that
   display. The input adapter for the experimental endpoint is configured
   with that display ID.
3. SurfaceFlinger creates one Composer virtual display per sink. Composer has
   one `VirtualDisplayState` and `AaasTransport` per endpoint, with independent
   output slots, client-target slots, locks, and generations.
4. Each output has an instance of the existing Wayland presenter and an input
   adapter connected to its private endpoint. The Android display ID is never used as a host-window ID.
5. On shutdown, the host asks the broker to release its `VirtualDisplay` and
   `ImageReader`, waits for removal and acknowledgement, and then stops the
   one-shot init service and the output pipeline.

The broker is not a host-callable Binder proxy. It has fixed bounded display
dimensions/density and creates at most two trusted displays per experimental
session. The two-app mode is currently a bounded prototype, not arbitrary
dynamic display management.
The feature is opt-in; default sessions do not set its display-content-mode
property or start this service.

## Identity mapping

These identifiers have distinct owners and lifetimes:

| Identifier | Owner | Current prototype use |
|---|---|---|
| AaaS session ID | host launcher | private runtime-session identity |
| Android display ID | DisplayManager | runtime assigned; displays 2 and 3 observed, scoped to session |
| Composer display ID | Composer HAL | runtime assigned; IDs 100 and 101 observed |
| Android task ID | ActivityTaskManager | Settings task 8 / display 2; DeskClock task 9 / display 3 |
| Activity token/component | ActivityTaskManager/PackageManager | Settings and SubSettings instances |
| transport socket | session launcher | separate socket and transport instance for each output |
| buffer slot/generation | Composer transport | output and client-target records are separate per display |
| Wayland toplevel | host presenter/KWin | separate virtual-output window; no stable host-window ID yet |
| input focus generation | presenter/input adapter | existing stale-event rejection; separate adapters target displays 2 and 3 |

The intended later relationship is
`host_window_id -> (android_display_id, display_generation) -> task_id`.
Current live evidence proves Settings task 8/display 2 and DeskClock task
9/display 3 concurrently, with Composer IDs 100/101. The toplevels had distinct
titles and app IDs but identical KWin geometry; independent focus, placement,
resize, and teardown are not yet verified.

## Trusted display broker boundary

The system-owned broker uses Android 16 `DisplayManager` and
`VirtualDisplayConfig`; Android assigns the ID and reports the unique ID,
flags, and `canHostTasks`. It creates a `PRIVATE | TRUSTED |
OWN_CONTENT_ONLY` display, disables Home support for that display, and owns the
surface and release lifecycle. Inputs are local session files and bounded
constants, not arbitrary Binder transactions. The host cannot request general
privileged display operations.

This is a development prototype using the existing diagnostic SELinux
compatibility environment. It is not a production security boundary.

## Composer and transport

Composer virtual-display creation is enabled only in the separately built
experimental Composer and only if its dedicated endpoints are connected. The
cap-two build advertised two outputs when both presenters were listening. Its slots distinguish the
`virtualDisplayOutputBuffer` from `clientTarget`; each keeps its own duplicated
DMA-BUF and acquire fence, dimensions, format, and generation. Buffers are
validated before use, acquire fences are waited, and host release fences are
returned as the present fence. The virtual stream uses a separate instance of
the existing frame protocol, leaving primary wire protocol v2 unchanged.

In the verified run, SurfaceFlinger supplied matching DMA-BUF inodes for the
output and client target. The code detected this and avoided a self-copy. A
copy is performed only for distinct backing. The copy path was not proven by
the Settings GPU-only run. Two Composer states and transports were exercised
concurrently; the distinct-backing branch remains component-tested only.

Future multi-window work must explicitly negotiate a session-authenticated
stream/window ID and display generation, or retain one authenticated socket
per output under a session manager. It must reject stale generations and
cross-output buffer reuse, preserve acquire/release fences, bound buffering,
and acknowledge teardown. Do not reinterpret v2 fields.

## Input routing

The primary presenter and input adapter continue to target Android display 0.
Each virtual presenter reads its Android-assigned display ID from its own
session-private file and places it in pointer and keyboard packets. Its
dedicated adapter validates the configured ID. Both adapters completed HELLO for their own display. Controlled pointer clicks
visibly changed the Settings view on display 2 and the DeskClock Alarm tab on
display 3. A synthetic `hii` fixture appeared in Settings Search on display 2
after Android Binder KeyEvent injection. Selecting the two KWin toplevels caused
the matching focus leave/enter messages; the Settings key packets were absent
from the DeskClock adapter. This is partial focus-isolation evidence. DeskClock
text editing, per-output scrolling, and full application-level two-way keyboard
isolation remain unverified.

Multi-window input will bind session, host-window ID, Android display ID and
generation, focus generation, and sequence. Focus loss must release held
buttons/keys before target changes. Existing M1C/M1D packets and semantics
remain unchanged.

## Lifecycle and resize boundary

The broker creates and releases up to two displays and surfaces. The launcher
starts and stops both presenters and adapters with the Android session. Full
session shutdown removed displays 3 and 2 and destroyed tasks 9 and 8. It does
not yet support task-specific close, minimize/unmap, or preserving another task
while one output is removed. The launcher currently stops the whole session if
either task or presenter exits.

Wayland configure sizes are not yet applied to Android display configuration.
Scaling an old frame is not accepted as resize support. A future resize must
choose content dimensions and density, update the Android virtual display,
wait for the configuration generation, then update pointer mapping and
buffers atomically.

## Two-output run state (2026-10-30)

The live two-app invocation was:

```sh
python3 scripts/run_aaas.py --experimental-virtual-display \
  --app com.android.settings --app2 com.android.deskclock --startup-timeout 180
```

The Android identity pairs were `(task 8, display 2, Composer 100)` for Settings
and `(task 9, display 3, Composer 101)` for DeskClock. Their distinct transport
sockets were `/dev/aaas/wayland-vdisplay.sock` and
`/dev/aaas/wayland-vdisplay.sock-2`; their input sockets were
`/dev/aaas/input-vdisplay.sock` and `/dev/aaas/input-vdisplay-2.sock`. The host
titles/app IDs were distinct. KWin geometry for both was `(600,0,720,1280)`, so
the actual window presentation still needs independent arrangement; pointer
and Settings keyboard interaction are now evidenced, while lifecycle/resize and
full per-window input acceptance remain incomplete. Full run details and screenshot hashes: `results/m1e/live/two_app_outputs.json`.
