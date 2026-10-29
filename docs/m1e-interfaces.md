# M1E interfaces and identity model

Status: **single virtual-display output prototype implemented; multi-window
session protocol remains future work**

## Current single-output prototype

The default path is still the established primary display. The opt-in
`--experimental-virtual-display` path adds one output without changing primary
wire protocol v2:

1. A session-local init service runs the AaaS display broker as Android system
   UID. It creates one trusted, private, own-content Android `VirtualDisplay`
   with a broker-owned `ImageReader` surface.
2. Android assigns the display ID; the broker publishes it only to the private
   session files. The launcher starts the selected resolved Activity on that
   display. The input adapter for the experimental endpoint is configured
   with that display ID.
3. SurfaceFlinger creates one Composer virtual display. Composer records its
   output-buffer slots separately from per-display client-target slots and
   submits output on a separate local transport socket.
4. A second instance of the existing Wayland presenter owns the secondary
   toplevel and its private input endpoint. The Android display ID is never
   used as a host-window ID.
5. On shutdown, the host asks the broker to release its `VirtualDisplay` and
   `ImageReader`, waits for removal and acknowledgement, and then stops the
   one-shot init service and the output pipeline.

The broker is not a host-callable Binder proxy. It has fixed bounded display
dimensions/density and a single trusted display per experimental session.
The feature is opt-in; default sessions do not set its display-content-mode
property or start this service.

## Identity mapping

These identifiers have distinct owners and lifetimes:

| Identifier | Owner | Current prototype use |
|---|---|---|
| AaaS session ID | host launcher | private runtime-session identity |
| Android display ID | DisplayManager | runtime assigned; prototype display 2, scoped to session |
| Composer display ID | Composer HAL | runtime assigned; prototype HAL display 100 |
| Android task ID | ActivityTaskManager | task 8 was observed on display 2 |
| Activity token/component | ActivityTaskManager/PackageManager | Settings and SubSettings instances |
| transport socket | session launcher | dedicated virtual-output stream, distinct from primary socket |
| buffer slot/generation | Composer transport | output and client-target records are separate per display |
| Wayland toplevel | host presenter/KWin | separate virtual-output window; no stable host-window ID yet |
| input focus generation | presenter/input adapter | existing stale-event rejection; secondary adapter targets display 2 |

The intended later relationship is
`host_window_id -> (android_display_id, display_generation) -> task_id`.
Current evidence proves one task on one secondary display, not a general
session-manager mapping or multiple simultaneous secondary displays.

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
experimental Composer and only if its dedicated endpoint is connected. It
advertises a maximum of one virtual display. Its slots distinguish the
`virtualDisplayOutputBuffer` from `clientTarget`; each keeps its own duplicated
DMA-BUF and acquire fence, dimensions, format, and generation. Buffers are
validated before use, acquire fences are waited, and host release fences are
returned as the present fence. The virtual stream uses a separate instance of
the existing frame protocol, leaving primary wire protocol v2 unchanged.

In the verified run, SurfaceFlinger supplied matching DMA-BUF inodes for the
output and client target. The code detected this and avoided a self-copy. A
copy is performed only for distinct backing. The copy path was not proven by
the live Settings run, and two-display concurrency is not yet supported.

Future multi-window work must explicitly negotiate a session-authenticated
stream/window ID and display generation, or retain one authenticated socket
per output under a session manager. It must reject stale generations and
cross-output buffer reuse, preserve acquire/release fences, bound buffering,
and acknowledge teardown. Do not reinterpret v2 fields.

## Input routing

The primary presenter and input adapter continue to target Android display 0.
The virtual presenter reads the Android-assigned display ID from a
session-private file and places it in pointer and keyboard packets. Its
dedicated adapter validates the configured ID and injects events to that
display through the existing Binder input manager path. A controlled pointer
click was observed opening a Settings subpage on display 2. Keyboard
interaction on display 2 and cross-window focus routing remain unverified.

Multi-window input will bind session, host-window ID, Android display ID and
generation, focus generation, and sequence. Focus loss must release held
buttons/keys before target changes. Existing M1C/M1D packets and semantics
remain unchanged.

## Lifecycle and resize boundary

The broker creates and releases one display and its surface. The experimental
launcher starts and stops the output presenter and adapter with the Android
session. This proves display cleanup on session shutdown, but not
task-specific close, app-finish behavior, minimize/unmap, or preserving another
task while one output is removed.

Wayland configure sizes are not yet applied to Android display configuration.
Scaling an old frame is not accepted as resize support. A future resize must
choose content dimensions and density, update the Android virtual display,
wait for the configuration generation, then update pointer mapping and
buffers atomically.
