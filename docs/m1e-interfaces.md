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

## App-mode primary presentation

For app-selected `--experimental-virtual-display` runs, `run_aaas.py` skips
starting the primary diagnostic presenter by default. `--show-primary-diagnostic`
requests the previous primary Wayland window for debugging. This does not
change Android display 0 or stop its framework/SystemUI services. Without
`--experimental-virtual-display`, the existing diagnostic primary presenter
behavior is retained.

## Resource diagnostic snapshots

`--resource-diagnostics` writes `resources-start.json`,
`resources-shutdown-begin.json`, and `resources-shutdown.json` in the private
session directory. `--resource-sample-interval N` additionally enables
periodic JSONL snapshots while RUNNING; interval must be 0–3600 seconds and at
most 3600 periodic records are emitted. Files are created with mode 0600.
Snapshots contain host `/proc/meminfo`, host PSI, cgroup v2 limits/events and
pressure for the launcher, AaaS parent, and optional delegated session group,
bounded matching process RSS/PSS and OOM score adjustments, and workspace
free space. Selected package names are used only to classify app processes;
command-line contents are not retained. Collection is read-only and does not
change memory policy.

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
titles and app IDs and were quick-tiled side by side in a later live run. Per-
window close was exercised. A later session verified concurrent Android-backed
resize on both outputs and an independent Settings resize while DeskClock stayed
unchanged. App reopen, per-output scroll, application-consumed keyboard input on
DeskClock, and post-resize input mapping remain unverified.

The presenter binds `xdg_wm_base` at protocol version 3 and its
`xdg_toplevel.configure` callback ignores the state array. It has no reliable
minimized/hidden signal or Android task visibility policy. The current behavior
therefore leaves visibility, minimization, and rendering decisions to KWin and
the Android runtime; no task pause or frame-throttling behavior is claimed.

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

Each app output owns its presenter, transport endpoint, input adapter, display
request/ack files, and frame generation. The Android process and broker are
shared. A per-output close causes the host to stop routing that output, asks
the broker to detach/release its VirtualDisplay and ImageReader, and waits for
an output-specific `released <displayId>` acknowledgement. A close of the last
app task transitions the shared runtime to STOPPING. Live KWin close testing
removed Settings task/display 8/2 while DeskClock task/display 9/3 stayed
RUNNING, then removed DeskClock and stopped the runtime. Both presenter logs
reported no outstanding or teardown-invalidated buffers. Reopen-after-close
and minimize/unmap behavior are not implemented or verified.

Each presenter receives the compositor's acknowledged `xdg_toplevel.configure`
dimensions, increments its local generation, sends the version-2 RESIZE
message, and publishes a private generation/width/height request for its
broker-owned display. `wp_viewporter` maintains the host toplevel geometry while
Android rebuilds its output. The broker replaces the per-display ImageReader
surface and invokes `VirtualDisplay.setSurface` and `VirtualDisplay.resize`;
the rollback restores the previous surface and dimensions if either call
fails. A delayed DisplayMetrics read confirms Android's new logical size.

The presenter previously rejected a stale-size transition buffer without
returning the existing protocol's RELEASE acknowledgement. Composer held that
slot, blocking replacement-size output. The presenter now releases valid
pre-import rejections, forwarding the original acquire fence as the release
dependency when it has not been consumed. This does not alter wire-v2 message
layout or accepted-buffer synchronization semantics.

A bounded live single-output resize verified 720×1280 → 960×1156 → 720×1280.
Android recreated its ImageReader-backed display output, Composer recreated
its virtual output, and presenter source buffers matched each configured size
(960×1156 stride 3840; 720×1280 stride 2944). The run ended with 176 imports,
176 submissions, 176 releases, and zero outstanding buffers. Evidence:
`results/m1e/live/native_resize_release_ack_20261030.json`.

A later two-output session resized Settings and DeskClock concurrently from
720×1280 to 960×1156. Broker acknowledgements, Android display metrics,
WindowManager task bounds, and both presenters' source-buffer dimensions
matched at 960×1156 (stride 3840). Settings was then resized independently to
960×578; its generation advanced and its source buffers matched, while
DeskClock remained at 960×1156 without a new configure. Both windows were
visible together in a genuine desktop capture. At shutdown the presenters
reported 215/215 and 197/197 imports/submissions/releases, with zero outstanding
buffers. Evidence:
`results/m1e/live/two_output_resize_keyboard_20261030.json` and
`results/m1e/live/two_output_native_resize_20261030.png`.

This establishes bounded concurrent resizing and resizing one output without
changing the other. Resize-back-to-original on both outputs, landscape, rapid
bursts, and pointer-coordinate correctness after resize remain untested.
`wp_viewporter` may cover transitions but is not counted as framebuffer
resizing. A new resize generation is validated only when a matching-size
Android source frame arrives; separate post-resize pointer remapping acceptance
is still required.

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
titles/app IDs were distinct. A later KWin quick-tile experiment arranged them
at `(0,0,960,1156)` and `(960,0,960,1156)`, captured together in
`results/m1e/live/two_app_side_by_side_resize_20261030.png`. Settings closed
independently while DeskClock remained live. In a separate session, synthetic
`/dev/uinput` h-i-i input visibly appeared in Settings Search on display 2.
After focus moved to DeskClock, its display-3 adapter received synthetic
Tab/Enter DOWN/UP events, while the Settings adapter had left keyboard focus and
logged no subsequent key injections. DeskClock had no text editor in the tested
Activity and no visible reaction to those keys was established. This confirms
limited focus/transport routing, not application-level keyboard consumption on
DeskClock. Per-output scrolling, post-resize input coordinates, and
physical-keyboard attribution remain open. Evidence:
`results/m1e/live/two_output_resize_keyboard_20261030.json` and
`results/m1e/live/two_app_keyboard_route_20261030.png`.

Resize and close evidence:
`results/m1e/live/two_app_window_resize_close_20261030.json`.


### Capacity-two Composer selection

When `--experimental-virtual-display` is combined with `--app2`, the launcher
builds/selects the Composer overlay with capacity two and two transport
endpoints. The `--app2` path starts the second Android activity before waiting
for the second input adapter HELLO, because that adapter connects only after its
virtual-display producer exists. An earlier capacity-two retry failed before
RUNNING during severe low-memory/swap pressure; subsequent bounded default and
source-LMKD/cgroup runs reached RUNNING and STOPPED. The lower-swap failure was
not reproduced in those follow-ups; see
[`two_output_capacity_memory_pressure_20261030.json`](../results/m1e/live/two_output_capacity_memory_pressure_20261030.json).
