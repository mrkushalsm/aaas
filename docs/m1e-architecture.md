# M1E architecture evaluation

Status: **two app windows can be arranged, resized, focused, and closed independently; visible text entry and vertical scrolling are bounded live passes; broader focus/lifecycle and graphics stability remain partial**
Android framework reference: pinned AOSP `frameworks/base` commit
`99b01a65cc4c104933788b3143285ab6bae65827` from
`manifests/android16-r1-subset.json`.
Android graphics interface reference: pinned `hardware/interfaces` commit
`5688f7eb1e117ed26e642a695de300b7683acb87`.

## Observed AaaS runtime boundary

The launcher now accepts `--app <package>` (defaulting to
`com.android.settings`), resolves that package's `MAIN`/`LAUNCHER` component
through Android PackageManager, and starts the resolved component. The normal
path keeps the diagnostic primary display. The experimental
`--experimental-virtual-display` path creates a system-owned trusted Android
virtual display for each requested app (`--app` and optional `--app2`), routes
each task to its Android display ID, and uses one Composer transport socket
and Wayland toplevel per output. The primary display, wire protocol v2, and
primary input route remain unchanged. Two tasks, Android displays, Composer
outputs, and Wayland toplevels have been verified in one runtime. Window
creation, configure, input, and presentation use Wayland protocols; AaaS has
no KDE/KWin API or patch dependency. KWin was the available test compositor
for recorded quick-tile placement and configure-event experiments. Per-window
close, native resize, and an independently resized second output have since
been verified. Bounded app-consumed keyboard input and create-after-destroy app
reopen have since been demonstrated. Per-output vertical scroll consumption
is live-verified in both runtime modes. Horizontal/touchpad-specific scroll
and Android lifecycle synchronization with host minimize remain unverified.

The live Android probe reported one logical display: ID 0, 720×1280, trusted,
and able to host tasks. Settings was task 8 and top-resumed. A Launcher HOME
task existed but was invisible. WindowManager's `DisplayPolicy` had a StatusBar
window and a Taskbar navigation window; the Taskbar contributed bottom Insets
of 126 pixels. The Android app window reported full display bounds in that
probe, but the system navigation window and touch ownership still exist on
that diagnostic display. The experimental secondary display has a separately
verified WMS/InputDispatcher state recorded below.

In selected-app virtual-display mode, the launcher omits the primary
diagnostic Wayland presenter unless `--show-primary-diagnostic` is specified.
Android's primary display and its framework/SystemUI services remain active;
only its host presentation is omitted. The ordinary non-virtual-display
diagnostic command still presents the primary output.

## Candidate comparison

| Candidate | Reuse and rendering | Android policy and security | Cost / principal risk | Assessment |
|---|---|---|---|---|
| **A. One virtual display per app task** | Android models display policy/output separately. Composer3 creates one output transport and presenter per available endpoint. Two outputs have been resized concurrently and then one independently. | The scoped system-UID broker creates trusted, private, own-content displays. Settings and DeskClock launched on separate displays. No general host Binder access is exposed. | Keyboard/focus edge coverage, resize-back/burst/landscape cycles, and Android minimize lifecycle synchronization remain incomplete; visible vertical scroll is verified. | **Side-by-side placement, per-window close, concurrent/independent resize are bounded live passes; overall M1E remains partial.** |
| **B. Task-level SurfaceControl output** | Android tasks already group an application's Activity stack, which is the right lifecycle unit. But the AaaS host currently receives only the whole-display Composer client target. It cannot obtain a task's independent surface from the current transport. | A task organizer/SurfaceControl bridge would require privileged framework ownership and strict surface/input authorization. Activities, dialogs, transitions, and child windows must remain composed consistently. | Requires task organizer/transaction infrastructure, SurfaceControl capture or reparenting, independent buffer export/release fences, z-order/animation handling, and input routing. Not a direct DMA-BUF stream merely because the Task has a SurfaceControl. | Better long-term if proven capture/export is available, but substantially more invasive and no reuse proof exists. Do not start here. |
| **C. Hybrid: task identity on per-task virtual displays** | One Android task is launched onto one virtual display and mapped to a dedicated presenter/toplevel. The primary diagnostic output remains independent. | The display broker is system-owned and creates the display locally. Two distinct tasks and displays were observed concurrently. Both outputs were resized together to 960×1156, then Settings alone to 960×578 with matching source buffers. | Resize-back/burst/landscape and full input-coordinate coverage, Android lifecycle synchronization with minimize, and the historical crash-free stability question remain. Bounded app text entry, vertical scroll isolation, create-after-destroy, and host-visible minimize/restore have live evidence. | **Validated as the current M1E prototype direction**, not yet a finished multi-window design. |

## Android 16 source contracts

Pinned source files (URLs point at the immutable commit used by the project):

- [`DisplayManagerService`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/services/core/java/com/android/server/display/DisplayManagerService.java): virtual-display creation, flags, display device/logical display registration, and display ownership.
- [`VirtualDisplayConfig`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/core/java/android/hardware/display/VirtualDisplayConfig.java): display dimensions, flags, output `Surface`, trusted/home support and related config contract.
- [`ActivityTaskSupervisor`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/services/core/java/com/android/server/wm/ActivityTaskSupervisor.java): launch-on-display authorization; private/untrusted display launch is not just an ActivityOptions routing decision.
- [`PackageManagerShellCommand`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/services/core/java/com/android/server/pm/PackageManagerShellCommand.java): `resolve-activity --brief` resolves an Activity component and prints the flattened component. M1E's package option uses this existing Android resolver and validates package syntax before constructing its runner command.
- [`VirtualDisplaySurface`](https://android.googlesource.com/platform/frameworks/native/+/2827a4a16b0340ecd07c2d5a6c89991799b362bb/services/surfaceflinger/DisplayHardware/VirtualDisplay/VirtualDisplaySurface.cpp): output-surface buffers are passed through `setOutputBuffer`; optional GPU/client composition is a distinct `setClientTarget` operation.
- [`DisplayContent`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/services/core/java/com/android/server/wm/DisplayContent.java): per-display system-decoration and Home-support decisions. Default display policy differs from secondary-display policy; decoration changes need to happen before surfaces are exposed and must be verified against WMS/Insets/input state.
- [`DisplayWindowSettings`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/services/core/java/com/android/server/wm/DisplayWindowSettings.java): display-specific settings and default-display behavior.
- [`WindowOrganizerController`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/services/core/java/com/android/server/wm/WindowOrganizerController.java): privileged task/window organization boundary for the task-level alternative.
- Composer3 interface source at pinned [`IComposerClient.aidl`](https://android.googlesource.com/platform/hardware/interfaces/+/5688f7eb1e117ed26e642a695de300b7683acb87/graphics/composer/aidl/android/hardware/graphics/composer3/IComposerClient.aidl) and [`DisplayCommand.aidl`](https://android.googlesource.com/platform/hardware/interfaces/+/5688f7eb1e117ed26e642a695de300b7683acb87/graphics/composer/aidl/android/hardware/graphics/composer3/DisplayCommand.aidl): the actual virtual-display/output-buffer API contract to use when implementing the prototype.

The checkout contains no local `frameworks/base` source tree; its pinned r1
revision is recorded in the manifest. Exact pinned source files were fetched
individually for this audit and their SHA-256 hashes are recorded in
`results/m1e/source_refs_manifest.json`. The existing `frameworks-native-qpr2`
checkout is exploratory only and is not treated as exact source for this SDK
image. No full AOSP checkout was started.

### Virtual-display frame contract

The pinned `frameworks/native` `VirtualDisplaySurface.cpp` distinguishes the
virtual display's **output buffer** from its optional client-composition
buffer. `advanceFrame()` supplies the output-surface buffer through
`HWComposer::setOutputBuffer`; the client-composition buffer, when present,
is separately supplied through `setClientTarget`. The pinned Composer3
`DisplayCommand.aidl` likewise defines `virtualDisplayOutputBuffer` as a
buffer written by the composer and requires it to be set before presentation.
This means the existing primary-display client-target exporter cannot simply
be reused by treating the two buffers as interchangeable. A virtual-display
prototype now registers a Composer virtual display, retains per-display output
buffer slots separately from client-target slots, and submits output through a
dedicated transport instance/socket. The observed Settings frames referenced
the same DMA-BUF inode for output and client target (`alias=1`); Composer waited
both acquire fences and forwarded that allocation without a self-copy. When
backing differs, the implementation copies client composition into the output
buffer. This validates separate API roles and routing, but does not claim
physically distinct backing allocations for every observed frame.

The 2026-10-30 continuation tested whether retaining one prior `ImageReader`
image would force a distinct output allocation. It did not: four live
output/client-target identity samples still had matching DMA-BUF device/inode,
and 65 frames were presented with zero presenter rejects. The temporary
retention experiment was reverted. The pinned source explains this GPU-only
case: `fbSourceForCompositionType(CompositionType::Gpu)` returns
`SOURCE_SINK`, and the GPU producer dequeues the sink/output buffer itself
(`VirtualDisplaySurface.cpp`, lines 670-671 and 388-435). `SOURCE_SCRATCH` is
selected for `CompositionType::Mixed`. Thus the observed alias is consistent
with the framework contract; it is not evidence that the separate-backing
copy path works. The Composer copy now rejects non-RGBA/BGRA formats, brackets
the CPU mapping with DMA-BUF read/write START/END synchronization, and uses a
stride-aware row-copy helper. A host component test confirms distinct backing,
pixel bytes, stride handling, and padding preservation. It uses memfd rather
than DMA-BUF, so cache-coherency and real Mixed-composition behavior remain
unverified. The cap-two build now validates concurrent per-display ownership
for the observed GPU-alias path; the real distinct DMA-BUF copy path remains
unverified and is not forced in GPU-only operation. See
`results/m1e/live/distinct_backing_probe.json` and
`results/m1e/live/distinct_copy_component.json`.

The framework `VirtualDisplayConfig` surface is the output sink supplied at
display creation. The system-owned broker must own that sink's BufferQueue
lifetime and ensure that buffer identities, generations, and fences cross the
Composer/host boundary without aliasing the primary client-target slots. A
Wayland window is not itself an Android `Surface`, so the host presenter alone
cannot create this Android output endpoint.

## Recommendation and prototype exit criteria

Continue with **Candidate C as the staged architecture**, using one Android
virtual display per app task and a dedicated presenter socket/toplevel. Two
Android tasks, displays, Composer transports, and Wayland toplevels have now
been exercised concurrently. Do not create a parallel Android container per
app. A later KWin quick-tile run established simultaneous side-by-side access;
Android output-buffer resize and full independent input/lifecycle acceptance
remain incomplete. Before claiming full M1E, the remaining work must prove:

1. Validate additional installed apps and launch failures.
2. Complete task-specific close/reopen and define minimize behavior.
3. Preserve the GPU-only aliased output path and validate the synchronized
   distinct-backing copy branch when real mixed composition supplies it.
4. Implement resize as an Android display/configuration update, not host-only
   scaling.
5. Verify independent keyboard/pointer/scroll focus and task-specific teardown,
   including destroying one output while the other continues.

The initial trusted-display path passed for Settings, and two-output ownership
was exercised in a bounded simultaneous run. Keep the primary display as a
diagnostic baseline until per-window teardown is independently proven. Do not
fall back to pretending virtual outputs are physical displays. The Android shell exposes no trusted-display creation
command; the system-owned local broker is required for this prototype.

The launcher now checks ActivityManager's activity/task snapshot for the
validated package instead of assuming the process name equals the package ID.
This covers apps declaring a custom `android:process`; exact task-ID tracking
in a host session manager remains future work.

## Trusted virtual-display prototype result (2026-10-30)

`python3 scripts/run_aaas.py --experimental-virtual-display --startup-timeout 180`
created Android display ID 2 with unique ID
`virtual:android,1000,AaaS application output,0`, size 720×1280, density 240,
and `FLAG_PRIVATE|FLAG_TRUSTED|FLAG_OWN_CONTENT_ONLY`. The system-UID broker
reported `canHostTasks=true`. ActivityTaskManager placed Settings task 8 on
display 2 and logged `Displayed` for Settings and a later SubSettings Activity.
A controlled `/dev/uinput` pointer event traversed the independent presenter,
socket, adapter, and Binder path targeting display 2. The screenshot
`settings_after_click2.png` in the external session directory shows the actual
Android Network & internet page in the secondary Wayland output.

Composer registered one virtual HAL display (ID 100) and emitted 180 virtual
output frames in the final instrumented run. The virtual presenter reported
180 imports/submissions, 179 releases, 176 presented frames, 4 discarded
frames, and zero rejects. WMS reports full 720×1280 app/task bounds and zero
non-decor Insets on display 2. InputDispatcher lists the Settings window with
the full display touch region; Taskbar and StatusBar input windows remain on
diagnostic display 0. SurfaceFlinger and DisplayManager logged virtual display
removal, Composer logged `destroyVirtualDisplay id=100`, the broker cleared the
published ID, and init stopped its one-shot service during shutdown.

This earlier one-app baseline is retained for comparison; it predates the
concurrent Settings/DeskClock experiment below. Its machine-readable details
and raw log paths remain in `results/m1e/live/trusted_virtual_display.json`.

### Concurrent two-output evidence (2026-10-30)

The two-display extension used separate `AaasTransport` instances, virtual
display states, output/client-target slots, locks, and generations. Runtime
created Composer IDs 100 and 101 and sent frames on both independent sockets.
Android assigned displays 2 and 3; Settings task 8 and DeskClock task 9 were
observed on them. The broker used one ImageReader/VirtualDisplay per output and
released both during full-session shutdown. The cap-two binary and source hashes
are recorded in `results/m1e/build_receipts/multi_output.json`. Live task, frame,
input, window and shutdown facts are in `results/m1e/live/two_app_outputs.json`.

In the initial two-output run, the two Wayland toplevels had distinct title/app-ID
pairs, but KWin placed both at `(600,0,720,1280)`. Each was captured individually
as the active window; those initial screenshots did not establish simultaneous
visibility. The later quick-tile experiment below establishes simultaneous
visibility, without claiming user-driven repositioning was tested.
Each adapter completed HELLO with its own display ID. Controlled pointer clicks
visibly changed Settings on display 2 and DeskClock on display 3. Synthetic
`hii` text visibly appeared in Settings Search on display 2; switching KWin focus
caused the corresponding input-adapter focus leave/enter, and no typed key packet
was observed on the unfocused adapter. At that initial checkpoint, DeskClock
text entry and per-output scroll were untested. In that initial run, resize, task-specific close, minimize,
and one-output teardown while the other remained alive were outstanding. Each
presenter also exited with one final outstanding imported frame. The later
bounded teardown run below drained all submitted buffers with no outstanding
or invalidated ownership.

### Independent placement, resize, and per-window close (2026-10-30)

The presenter negotiates standard `xdg_toplevel.configure` dimensions and binds
the standard Wayland `wp_viewporter` protocol. Acknowledged configure sizes are
sent through private per-output resize request files. The system-UID broker
creates a replacement `ImageReader` surface, calls `VirtualDisplay.setSurface`
and `VirtualDisplay.resize`, then logs refreshed metrics after a 500 ms
Handler delay. KWin quick-tile scripting placed Settings at
`(0,0,960,1156)` and DeskClock at `(960,0,960,1156)`; the screenshot
`results/m1e/live/two_app_side_by_side_resize_20261030.png` shows both real
Android interfaces simultaneously.

Android DisplayManager reported both virtual displays at 960×1156 / 240 dpi,
and WindowManager transitions changed both task bounds to 960×1156. In that
run the old-size transition buffers were not returned to Composer, so the
presenter never received replacement-size buffers. A bounded follow-up
isolated the first broken boundary: the presenter's stale/format pre-import
reject path closed received FDs but omitted the wire-v2 RELEASE acknowledgement.
Composer therefore retained the rejected output slot. The presenter now
returns RELEASE for a valid buffer rejected before import, carrying its
acquire fence as the release dependency when supplied. This permits safe reuse
because the presenter never consumed the buffer.

In a real Settings session the chain then completed in both directions:
720×1280 → 960×1156 → 720×1280. On each transition the broker replaced the
ImageReader surface and called `VirtualDisplay.setSurface()` and
`VirtualDisplay.resize()`. Android recreated the Composer virtual display;
Composer client-target/output frames and presenter source buffers then matched
the requested dimensions. The first 960×1156 source frame had stride 3840;
the return 720×1280 frame had stride 2944. Stale transition frames were
explicitly RELEASEd. The presenter drained 176/176 buffers with zero
outstanding or teardown-invalidated buffers. Details and raw artifact hashes:
[`native_resize_release_ack_20261030.json`](../results/m1e/live/native_resize_release_ack_20261030.json).

This validates one output and these two sizes only. No live evidence yet covers
simultaneous two-output resize, rapid resize bursts, landscape, navigation
during resize, or post-resize pointer mapping. No screenshot was captured in
the resize follow-up. `wp_viewporter` remains a transition aid, not the source
of the newly verified Android buffer dimensions.

KWin close on Settings removed task 8/display 2 and the broker acknowledged
`released 2`, while DeskClock task 9/display 3 and its presenter stayed alive.
Closing DeskClock later acknowledged `released 3`, removed the final task, and
stopped the shared Android runtime. Both presenter summaries ended with equal
import, submission, and release counts, with zero teardown-invalidated or
outstanding buffers. Reopening an app without runtime restart and minimize
semantics remain untested. The xdg-shell client protocol used here does not
provide a general minimize/visibility event, so no minimize policy is claimed.

A separate run crashed SurfaceFlinger with SIGSEGV at PC `0x12bf` in a deleted
`/memfd:swiftshader_jit` mapping. The single JIT frame was not symbolicated and
no causal relation to resizing has been established; keep the known SwiftShader
JIT failure as a separate open runtime issue.

The single-output resize follow-up did not reproduce that SIGSEGV, but SurfaceFlinger
logged two `Unexpected onFrameCommitted in Gpu state` transition warnings.
One bounded non-reproduction does not identify or fix the historical JIT fault.
The resize ownership change is separate from the unresolved SwiftShader issue.

### Final input/minimize acceptance update (2026-10-31)

The Android Contacts editor was reused as a second ordinary app input target.
Controlled synthetic typing visibly changed both it and Settings Search after
KWin focus transfers. Ctrl+A and Escape produced their expected visible
Settings actions. KWin minimize/restore preserved visible host-window content
and the remaining app stayed running. Both outputs moved from 720×1280 to real
950×1100 source buffers (stride 3840); stale transition frames were rejected.
At shutdown, Settings had 1837/1837 and Contacts 1822/1822
imports/submissions/releases, with no outstanding buffers. These observations
are bounded to one default-LMKD run and synthetic input. Scroll injections
returned rc=0 without a visible list movement, and 13 transient InputDispatcher
no-focused-window warnings occurred during focus transitions. No ANR or
SwiftShader JIT crash signature appeared in this session, which does not resolve
the historical JIT crash. See
`results/m1e/live/final_input_minimize_acceptance_20261031.json`.

A second, short enhanced source-LMKD/cgroup session showed synthetic `alpha`
in Settings and `beta` in Contacts and then cleaned both outputs and the
delegated cgroup. Its first key attempt lost the initial character, while a
refocused retry succeeded; this is recorded as a remaining focus-entry edge,
not as a resolved race. No enhanced-mode scroll or lifecycle interaction was
tested. See `results/m1e/live/enhanced_keyboard_interaction_20261031.json`.


### Capacity-two runtime selection and memory-pressure boundary

The two-app experimental launcher now selects a separately built Composer
with `AAAS_VIRTUAL_DISPLAY_CAPACITY=2`; the single-app path continues to use
the one-output overlay. In the latest bounded attempt, Composer advertised two
transports and created two outputs, both app launches returned success, both
input adapters completed HELLO, and each presenter observed/released frames.
Android then failed before the foreground session reached RUNNING: logcat shows
lowmemorykiller repeatedly killing framework/app processes under breached
watermarks and swap below the configured ~801 MB minimum. This is the current
observed blocker for repeating live two-app acceptance on this host; it is not
evidence that the cap-two transport or adapter handshake failed. No screenshot
or interactive acceptance is claimed for that attempt. Evidence and hashes are
in [`two_output_capacity_memory_pressure_20261030.json`](../results/m1e/live/two_output_capacity_memory_pressure_20261030.json).
