# M1E architecture evaluation

Status: **one-display trusted virtual-output prototype validated; multi-window architecture remains partial**
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
`--experimental-virtual-display` path creates one system-owned trusted Android
virtual display, starts Settings on its Android display ID, and uses a second
Composer transport socket and Wayland toplevel. The primary display, wire
protocol v2, and primary input route remain unchanged. This proves one
secondary output; it is not yet a general multi-window session manager.

The live Android probe reported one logical display: ID 0, 720×1280, trusted,
and able to host tasks. Settings was task 8 and top-resumed. A Launcher HOME
task existed but was invisible. WindowManager's `DisplayPolicy` had a StatusBar
window and a Taskbar navigation window; the Taskbar contributed bottom Insets
of 126 pixels. The Android app window reported full display bounds in that
probe, but the system navigation window and touch ownership still exist on
that diagnostic display. The experimental secondary display has a separately
verified WMS/InputDispatcher state recorded below.

## Candidate comparison

| Candidate | Reuse and rendering | Android policy and security | Cost / principal risk | Assessment |
|---|---|---|---|---|
| **A. One virtual display per app task** | Android models display policy/output separately. Composer3 now allocates one virtual output and the prototype transports it over a dedicated socket. | The scoped system-UID broker creates a trusted, private, own-content display. The installed Settings app launches successfully on it. This is a privileged prototype, not an unrestricted host Binder interface. | Multi-display scalability, resize, secondary app compatibility, and concurrent buffer ownership remain unverified. | **Single-display prototype passed; scale-out pending.** |
| **B. Task-level SurfaceControl output** | Android tasks already group an application's Activity stack, which is the right lifecycle unit. But the AaaS host currently receives only the whole-display Composer client target. It cannot obtain a task's independent surface from the current transport. | A task organizer/SurfaceControl bridge would require privileged framework ownership and strict surface/input authorization. Activities, dialogs, transitions, and child windows must remain composed consistently. | Requires task organizer/transaction infrastructure, SurfaceControl capture or reparenting, independent buffer export/release fences, z-order/animation handling, and input routing. Not a direct DMA-BUF stream merely because the Task has a SurfaceControl. | Better long-term if proven capture/export is available, but substantially more invasive and no reuse proof exists. Do not start here. |
| **C. Hybrid: task identity on per-task virtual displays** | One Android task is launched onto one virtual display and mapped to a dedicated presenter/toplevel. The primary diagnostic output remains independent. | The display broker is system-owned and creates the display locally. Task ID 8 was observed on display 2. | One-task output is demonstrated; task-aware close, multiple task outputs, resize, and independent two-app operation remain. | **Validated as the M1E prototype direction**, not yet a finished multi-window design. |

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
unverified. Do not increase Composer virtual-display capacity until the
distinct DMA-BUF path and concurrent per-display ownership are validated. See
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
virtual display per app task and a dedicated presenter socket/toplevel. The
first display and frame path are live-tested. Do not create a parallel Android
container per app. Before claiming full M1E, the remaining work must prove:

1. Validate additional installed apps and launch failures.
2. Implement task-specific close/minimize and display restart behavior.
3. Verify Composer output/client-target ownership with both aliased and distinct
   backing allocations.
4. Implement resize as an Android display/configuration update, not host-only
   scaling.
5. Demonstrate two tasks in independent Wayland toplevels and independently
   destroy one output while the other continues.

The initial trusted-display and output-path gate passed for one Settings task.
Keep the primary display as a diagnostic baseline until multi-output ownership
and teardown are proven. Do not fall back to pretending virtual outputs are
physical displays. The Android shell exposes no trusted-display creation
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

Machine-readable details and raw log paths are in
`results/m1e/live/trusted_virtual_display.json`. M1E remains **PARTIAL**: no
second app/window, Android resize integration, or task-specific close policy
has been demonstrated.
