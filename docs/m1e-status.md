# M1E status

Status: **PARTIAL — two-app placement and per-window close are live; single-output Android buffer resizing now works, while multi-output resize, input isolation, reopen, and crash stability remain incomplete**

Date: 2026-10-30

## Preserved baseline

M1E continues to use one shared rootless Android 16 runtime, the system-owned
trusted-display broker, Composer3's separate per-display transports, and the
existing Wayland presenter/input stack. The default and source-LMKD/cgroup
paths, M1D keyboard/IME support, primary diagnostic output, and earlier M1B–M1C
graphics/pointer work were not replaced. The active Composer overlay was
restored after live testing to its original SHA-256
`456d2201cb28ccccc8f2b35879ea3ebe8ebf740bf116aac34019c7cf34554894`.

The established two-app invocation remains:

```sh
python3 scripts/run_aaas.py --experimental-virtual-display \
  --app com.android.settings --app2 com.android.deskclock --startup-timeout 180
```

## New live results

### Native output resize recovery (2026-10-30)

A bounded single-Settings session reproduced 720×1280 → 960×1156 →
720×1280. DisplayManager and WindowManager reflected 960×1156; Composer
recreated its virtual display; and the first matching output frame had
960×1156 dimensions and a 3840-byte stride. Resizing back produced a matching
720×1280 frame with a 2944-byte stride. This is genuine source-buffer resizing,
not only host viewport scaling.

The first failing boundary was the presenter's pre-import stale-generation
rejection: it closed the received DMA-BUF/fence descriptors without returning
the protocol RELEASE. Composer consequently kept that output slot in flight.
The presenter now acknowledges buffers rejected before import, preserving the
acquire fence as the release dependency when valid. The first frame of the new
size then arrived and was presented. The run ended with 176 imports, 176
submissions, 176 releases, zero outstanding buffers, and no teardown
invalidations. Full trace and hashes are in
[`native_resize_release_ack_20261030.json`](../results/m1e/live/native_resize_release_ack_20261030.json).

This proves one output resizing in both directions. Rapid resize bursts,
landscape, simultaneous independent output resizing, navigation during resize,
and pointer remapping after resize remain untested. No screenshot was captured
in this run. A separate two-app attempt failed before RUNNING when the second
presenter did not accept its input adapter; that failure is not attributed to
the resize fix, and earlier accepted two-app evidence below remains intact.

The continuation session `m1b84_session_8e7pe6lh` created Settings task 8 on
Android display 2 / Composer display 100 and DeskClock task 9 on Android
display 3 / Composer display 101. KWin quick-tiled their separate toplevels
left and right; the real desktop capture shows both live Android applications
at once in [`two_app_side_by_side_resize_20261030.png`](../results/m1e/live/two_app_side_by_side_resize_20261030.png).
The temporary KWin script used compositor-managed quick tiling; it did not
change persistent KWin configuration. Details and raw-log hashes are in
[`two_app_window_resize_close_20261030.json`](../results/m1e/live/two_app_window_resize_close_20261030.json).

### Per-window close and terminal buffer ownership

Closing the Settings toplevel through KWin caused its app state to become
`CLOSED`; the broker released Android display 2 and Android removed task 8.
DeskClock task 9 and its presenter remained running. Closing DeskClock then
released display 3; as the last app window, it caused the shared runtime to
shut down. The final state journal and status sentinel both read `STOPPED`,
and the broker shutdown acknowledgement was `released`.

Both presenters reached a terminal ownership state with no active buffers:

| Output | Imports/submissions/releases | Presented/discarded | Teardown invalidated | Outstanding |
|---|---:|---:|---:|---:|
| Settings | 146 / 146 / 146 | 141 / 5 | 0 | 0 |
| DeskClock | 117 / 117 / 117 | 109 / 8 | 0 | 0 |

This is bounded live evidence for closing one output while preserving the
other task/presenter, followed by last-window shutdown. Reopening an app
without restarting Android, minimize/unmap policy, and per-output input
isolation are still unverified.

### Resize boundary

The Wayland `xdg_toplevel` configure path now acknowledges the compositor's
size and uses the standard Wayland `wp_viewporter` protocol to keep the host
surface at that size while Android rebuilds its output resources. Broker
resize generation 2 was acknowledged for both outputs at 960×1156. Android
DisplayManager reported each virtual display at 960×1156 and 240 dpi, and
WindowManager transitions changed each task's bounds from 720×1280 to
960×1156.

The Android frames crossing Composer3 still measured 720×1280 (stride 2944);
no 960×1156 source frame reached the presenter in this run. The viewporter
That earlier run's 720×1280 frames exposed a presenter-side ownership bug,
not a missing Android resize allocation. In the follow-up, the replacement
ImageReader surface and `VirtualDisplay.resize()` caused Android and Composer
to recreate output resources. The stale-size transition frame was rejected and
RELEASEd, after which Composer delivered a new-size frame. The previous run
therefore does not establish failed Android resize propagation.

### Separate crash observation

A previous resize experiment (`m1b84_session_byh_9r3y`) failed when SurfaceFlinger
pid 186/tid 216 received SIGSEGV at PC `0x12bf` in
`/memfd:swiftshader_jit (deleted)`, with only one unsymbolicated JIT frame.
Both output producers disconnected; its broker close handshake timed out.
That run is excluded from clean lifecycle acceptance and demonstrates that the
historical SwiftShader JIT fault remains unresolved. The clean
`8e7pe6lh` lifecycle run completed separately without that crash.

## Acceptance boundaries

| Capability | Result | Evidence limit |
|---|---|---|
| Two Android tasks, trusted displays, Composer outputs, Wayland toplevels | PASS, bounded live | IDs recorded in the session evidence; IDs are not constants. |
| Both windows simultaneously visible and independently placed | PASS, bounded live | KWin quick-tile arrangement and genuine screenshot; user-driven repositioning was not separately tested. |
| Per-window task/display close | PASS, bounded live | Settings closed while DeskClock remained running; then DeskClock closed and runtime stopped. |
| Buffer/fence terminal ownership | PASS, bounded live | Both summaries show imports=submissions=releases, zero invalidated/outstanding. |
| Single-output Android framebuffer resize | PASS, bounded live | 720×1280 → 960×1156 → 720×1280; Composer and presenter source dimensions/strides matched after each transition. No screenshot or post-resize coordinate test was captured. |
| Concurrent two-output resize | NOT TESTED | No live evidence for resizing one app while the other remains unchanged. |
| Keyboard on both outputs, scrolling, focus isolation | PARTIAL / NOT TESTED here | Prior Settings secondary keyboard evidence remains; this continuation did not type into DeskClock or test scrolling on both outputs. |
| Reopen app without restarting runtime | NOT TESTED | No broker create-after-destroy request exists in this experiment. |
| Minimize/unmap lifecycle | NOT TESTED | `xdg-shell` does not provide a general minimized notification; no visibility policy is claimed. |
| Hide primary diagnostic presenter in normal app mode | NOT IMPLEMENTED | The primary diagnostic presenter still starts; this continuation did not hide it. |
| Distinct DMA-BUF copy on real Mixed composition | NOT TESTED LIVE | GPU-only alias path and component-level stride/copy tests remain as previously documented. |
| SwiftShader JIT crash freedom | PARTIAL | One separate live SurfaceFlinger JIT SIGSEGV remains unresolved. |
| Resize/JIT relationship | OPEN | The resize follow-up did not reproduce the historical JIT SIGSEGV; it logged two `Unexpected onFrameCommitted in Gpu state` warnings. The old fault remains unsymbolicated and open. |

## Verification

The final automated runs for this continuation passed:

- `python3 -m unittest discover -s tests -v`: **153 tests**.
- `make -C experiments/m1a test`.
- `make -C experiments/m1a -B build/wayland-host-presenter test`.
- `make -C experiments/m1c/input_adapter -B all`.
- `make -C experiments/m1b/composer_aaas test`.
- `make -C experiments/m1e/display_broker -B all`.
- `python3 scripts/android_workspace.py --workspace /run/media/mrkus/Homework/aaas-workspace check`.

The external workspace remained on `/dev/sda2` (NTFS3, UUID
`A2ACEDF2ACEDC0C1`) at about 22.8 GB used, under its 80 GiB ceiling with the
20 GiB safety reserve. Build hashes and IDs are in
[`window_resize_lifecycle_20261030.json`](../results/m1e/build_receipts/window_resize_lifecycle_20261030.json).

## Next verified work

1. Diagnose the unresolved SwiftShader JIT/SF crash and repeat bounded stability runs.
2. Verify resize bursts, landscape, pointer-coordinate mapping, and resize isolation across two live outputs.
3. Diagnose the latest second-presenter/input-adapter readiness failure, then verify two-way keyboard, scroll, and focus isolation.
4. Add a broker create-after-destroy lifecycle so apps can reopen without restarting Android.
5. Define/test minimize behavior only where the Wayland/KWin protocol exposes reliable visibility state.
6. Add an explicit app-mode policy for not showing the primary diagnostic output while retaining a diagnostic option.
7. Repeat expanded two-app resize, close/reopen, input, and shutdown under default and source-LMKD/cgroup modes.

Overall M1E remains **PARTIAL**. Two live Android apps have previously been
shown side by side, with independent task close and drained buffers. A later
single-output run verifies genuine Android-sized buffer changes in both
directions. Full two-output resize, complete per-window input, reopen/minimize,
primary diagnostic-output suppression, and the historical SwiftShader JIT
crash boundary remain open.
