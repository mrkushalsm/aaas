# M1E architecture evaluation

Status: **architecture audit complete; selected direction is provisional pending a one-display prototype**
Android framework reference: pinned AOSP `frameworks/base` commit
`99b01a65cc4c104933788b3143285ab6bae65827` from
`manifests/android16-r1-subset.json`.
Android graphics interface reference: pinned `hardware/interfaces` commit
`5688f7eb1e117ed26e642a695de300b7683acb87`.

## Observed AaaS runtime boundary

The launcher now accepts `--app <package>` (defaulting to
`com.android.settings`), resolves that package's `MAIN`/`LAUNCHER` component
through Android PackageManager, and starts the resolved component. The host
presenter still owns one `xdg_toplevel`,
one Android frame socket, and one pointer/keyboard input endpoint. The current
input packet carries Android display ID 0. Composer3 connects to the single
`/dev/aaas/wayland.sock` path and its single ComposerClient keeps one
client-target slot array. Its AIDL virtual-display methods are explicit stubs:
`createVirtualDisplay()` returns `EX_UNSUPPORTED`, and
`getMaxVirtualDisplayCount()` returns 0.

The live Android probe reported one logical display: ID 0, 720×1280, trusted,
and able to host tasks. Settings was task 8 and top-resumed. A Launcher HOME
task existed but was invisible. WindowManager's `DisplayPolicy` had a StatusBar
window and a Taskbar navigation window; the Taskbar contributed bottom Insets
of 126 pixels. The Android app window reported full display bounds in that
probe, but the system navigation window and touch ownership still exist. This
is not sufficient evidence of full app-accessible bounds.

## Candidate comparison

| Candidate | Reuse and rendering | Android policy and security | Cost / principal risk | Assessment |
|---|---|---|---|---|
| **A. One virtual display per app task** | Android already models a display with its own logical size, layer stack, WindowManager policy, and output target. Composer3 defines virtual-display allocation and output-buffer operations. The current AaaS Composer explicitly implements none of that and the transport has no output identity. | A non-default display can have its own system-decoration/Home policy. However, Android limits activity starts on untrusted/private displays; `ActivityTaskSupervisor` performs a launch-display authorization check. A system-owned trusted virtual device/display path is required; simply passing `--display` is not a safe or general bypass. | Requires virtual-display allocation, per-display buffers/fences, one transport/output per window, scoped display creation and app task launch, display-specific input, and teardown. | **Best staged output model**, conditional on a trusted-display prototype proving ordinary apps can launch and the Composer output is exportable. |
| **B. Task-level SurfaceControl output** | Android tasks already group an application's Activity stack, which is the right lifecycle unit. But the AaaS host currently receives only the whole-display Composer client target. It cannot obtain a task's independent surface from the current transport. | A task organizer/SurfaceControl bridge would require privileged framework ownership and strict surface/input authorization. Activities, dialogs, transitions, and child windows must remain composed consistently. | Requires task organizer/transaction infrastructure, SurfaceControl capture or reparenting, independent buffer export/release fences, z-order/animation handling, and input routing. Not a direct DMA-BUF stream merely because the Task has a SurfaceControl. | Better long-term if proven capture/export is available, but substantially more invasive and no reuse proof exists. Do not start here. |
| **C. Hybrid: task identity on per-task virtual displays** | Use Android task identity for launch, lifecycle, Back, and close; use a dedicated Android virtual display as the output unit mapped to one Wayland toplevel. Keep app-internal Activities and dialogs in that task/window. | Requires a narrow system-owned display/task broker. Display decoration and Home support are configured before launch. Cross-task Activities need an explicit policy (same window if launched in the task; new window only for an independently exposed task). | Adds a broker and output routing, but avoids one container per app and avoids manually extracting individual app layers. Trust, launch policy, output-buffer ownership, and app compatibility remain prototype gates. | **Recommended staged architecture** for M1E, subject to Candidate A prototype. It maps one Android task group to one display/output and preserves Android lifecycle semantics. |

## Android 16 source contracts

Pinned source files (URLs point at the immutable commit used by the project):

- [`DisplayManagerService`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/services/core/java/com/android/server/display/DisplayManagerService.java): virtual-display creation, flags, display device/logical display registration, and display ownership.
- [`VirtualDisplayConfig`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/core/java/android/hardware/display/VirtualDisplayConfig.java): display dimensions, flags, output `Surface`, trusted/home support and related config contract.
- [`ActivityTaskSupervisor`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/services/core/java/com/android/server/wm/ActivityTaskSupervisor.java): launch-on-display authorization; private/untrusted display launch is not just an ActivityOptions routing decision.
- [`PackageManagerShellCommand`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/services/core/java/com/android/server/pm/PackageManagerShellCommand.java): `resolve-activity --brief` resolves an Activity component and prints the flattened component. M1E's package option uses this existing Android resolver and validates package syntax before constructing its runner command.
- [`VirtualDisplaySurface`](https://android.googlesource.com/platform/frameworks/native/+/2827a4a16b0340ecd07c2d5a6c89991799b362bb/services/surfaceflinger/DisplayHardware/VirtualDisplaySurface.cpp): output-surface buffers are passed through `setOutputBuffer`; optional GPU/client composition is a distinct `setClientTarget` operation.
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
prototype must register a Composer virtual display, retain per-display output
buffer slots and acquire fences, submit that specific output buffer through a
stream with its own identity, and return a release fence that allows Android's
output-surface producer to recycle it. Existing client-target behavior must
remain independent.

The framework `VirtualDisplayConfig` surface is the output sink supplied at
display creation. The system-owned broker must own that sink's BufferQueue
lifetime and ensure that buffer identities, generations, and fences cross the
Composer/host boundary without aliasing the primary client-target slots. A
Wayland window is not itself an Android `Surface`, so the host presenter alone
cannot create this Android output endpoint.

## Recommendation and prototype exit criteria

Proceed with **Candidate C as a staged hypothesis**, using one Android virtual
display per host window and an Android task (or task group) as the lifecycle
identity. This is not yet a final architecture decision: its source contracts
are understood, but no display has been created and no frame has traversed
Composer's virtual-display output path. Implement no parallel Android
container per app. Before treating Candidate C as selected, a minimal
prototype must prove, in order:

1. The chosen Android-owned display creation path is trusted only for the AaaS
   broker and can launch a normal installed app without granting global
   privileges. The existing shell has no create-display command, and the
   tested launch uses the existing Settings package only.
2. The virtual display has no Android Home, status/navigation bar, Taskbar, or
   system-owned touch region; WMS Insets and InputDispatcher window state agree.
3. Composer3 output-surface buffers are handed off independently from the
   client target with correct acquire/release ownership and per-output
   transport identity.
4. One Android task renders to one distinct Wayland toplevel; resize updates
   Android configuration and touch mapping.
5. A second task/window can be destroyed without affecting the first.

If step 1 or 3 fails, stop before building the per-window host interface and
re-evaluate the task-surface alternative using a source-backed SurfaceFlinger
capture path. A host `Surface`/BufferQueue consumer plus Composer output
forwarding may be the narrowest virtual-display prototype, but its buffer
ownership and Android API privilege boundary must first be established. Do not
fall back to pretending virtual outputs are physical displays. The Android
shell in the current runtime exposes `am display move-stack` only; it has no
shell command to create a trusted display, and an ordinary shell caller cannot
be treated as the privileged display broker.

The current `--app` launch path still checks foreground liveness by expecting
the app process name to match its package ID. Replace that with task-based
liveness before claiming compatibility with launch Activities that declare a
custom `android:process`.
