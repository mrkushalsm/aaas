# M1E status

Status: **PARTIAL — package-selected launch added; display/window integration remains unimplemented**
Date: 2026-10-30
Initial commit: `73dd794d3a265df869b774abc8b02cfda7620c8c`
Preservation record: `results/m1e/preservation_manifest.json`
Live display probe: `results/m1e/live/display_task_probe.json`

## Completed this turn

- Confirmed a clean `master` worktree at M1D closure and no configured Git
  remote. The external NTFS3 workspace is mounted from `/dev/sda2`, using
  22,067,859,968 bytes against the 80 GiB ceiling, with the 20 GiB reserve
  intact.
- Recorded hashes for the launcher, runner, presenter, protocol, Composer3,
  input adapter, and active graphics/runtime overlays.
- Reproduced the default session twice. Both reached `RUNNING`; both reached
  `STOPPED` on Ctrl+C. The display-inspection run presented 250 submissions,
  247 frames, released 249, rejected 0, and discarded 3. No new screenshot was
  taken, so this is runtime evidence, not a new visual claim.
- Captured a bounded Android `dumpsys display`, `dumpsys window displays`, and
  `dumpsys activity activities` probe in the external workspace.
- Evaluated per-app virtual displays, task-level SurfaceControl, and a hybrid
  task-on-virtual-display model. Candidate C is recommended provisionally; a
  trusted virtual-display/Composer output prototype remains mandatory.
- Added `--app <package>` to resolve an installed package's `MAIN`/`LAUNCHER`
  Activity through Android PackageManager. The package ID is syntax-validated
  before being embedded in the generated runner; a missing resolved component
  fails startup. The default remains `com.android.settings`.
- Live-tested `python3 scripts/run_aaas.py --app com.android.settings` through
  `RUNNING` and clean Ctrl+C shutdown. Android logcat records the Settings
  ActivityTaskManager launch and `Displayed`/`Fully drawn` events. This is a
  package-selected launch check, not proof of arbitrary-package compatibility.
  The current foreground-liveness check expects the Android process name to
  match the package ID; apps declaring a custom main process need task-based
  liveness before this option is considered generally compatible.
- Ran the enhanced source-LMKD/cgroup session to `RUNNING`; Ctrl+C stopped the
  session and removed its delegated hierarchy. Its summary recorded nine
  monitor ticks, zero errors, and no OOM/high events in this bounded run.
- Captured a live Android shell capability probe. `cmd activity help` exposes
  moving a stack to an existing display, while `cmd display help` provides no
  create-display interface. A trusted display therefore needs a scoped Android
  system-side broker.
- Fresh regression checks passed: 134 Python tests, M1A tests, presenter
  build/tests, input-adapter rebuild, and external workspace guard.

## Current state established by the live probe

- Android reports one logical display, ID 0, 720×1280, trusted, task-hosting.
- Settings is the top-resumed Activity in task 8 on display 0.
- Android starts HOME/setup activities while booting, then AaaS resolves and
  launches the selected package. The HOME task is invisible once Settings is
  foreground, but this does not prove the home surface was never presented.
- WindowManager lists StatusBar and Taskbar. Taskbar is the navigation-bar
  Insets source at y=1154..1280 (126 pixels). Thus M1E's no-system-decoration
  and full touch-region requirements are **not met** on the current display.
- The current Composer3 returns zero virtual displays and `EX_UNSUPPORTED` from
  its virtual-display creation method. It uses one fixed transport endpoint.
- Pinned Android 16 `VirtualDisplaySurface` sends the output-surface buffer
  through Composer `setOutputBuffer`; an optional client target is distinct.
  Current AaaS only transports client targets, so virtual displays need
  independent output-buffer slots, fences, stream identity, and release
  handling.
- Current protocol v2 has no output-stream/window target. Input currently
  targets display 0. There are no independent Android app outputs or Wayland
  toplevels.

## Gate summary

| Gate | Status | Evidence boundary |
|---|---|---|
| G1 M1D baseline preserved | PASS | Commit and hash manifest; default live sessions reached RUNNING/STOPPED. Full M1D suite was not rerun in this audit. |
| G2 Android 16 architecture assessed | PASS (audit) | `docs/m1e-architecture.md`, pinned source links, live display/task/window probe, current Composer source. Prototype not yet validated. |
| G3 Direct selected-app launch | PARTIAL | `--app` resolves and starts Settings live; a second package and no-launcher failure are not live-tested. |
| G4 Home presentation removed | PARTIAL | Launcher task is invisible while Settings is active; no app-completion/Home-fallback behavior tested. |
| G5 Global decorations removed | FAIL | WMS currently has StatusBar and Taskbar windows on display 0. |
| G6 Insets/touch regions correct | FAIL | Existing Taskbar has 126-pixel bottom Insets; M1E full-bounds requirement not met. |
| G7 Native Wayland app identity | NOT TESTED | Generic presenter title; no Android app label/app ID association. |
| G8 Window lifecycle | PARTIAL | Single-window close shuts down runtime; task-specific close/minimize behavior not implemented. |
| G9 Resize integration | FAIL | Current presenter reports configure size to a single Composer stream; actual Android display reconfiguration is not implemented. |
| G10 Keyboard/pointer routing | PASS (baseline only) | M1D accepted behavior preserved; multi-window routing remains absent. |
| G11 Two independent windows | NOT TESTED | One logical display/output only. |
| G12 Independent focus | NOT TESTED | No per-window Android display/task mapping. |
| G13 Independent teardown | NOT TESTED | No multi-output lifecycle. |
| G14 Graphics integrity | PASS (bounded baseline) | 250 imports/submissions; 247 presented; 249 released; zero rejects; full M1D stress not rerun. |
| G15 Memory integration | PASS (bounded smoke) | Default and enhanced runtime reached RUNNING; enhanced cgroup was removed on shutdown with zero monitor errors. No induced pressure experiment was run. |
| G16 Reproducibility | PARTIAL | Pinned source refs, source hashes, build IDs, launch code, and live logs are recorded; no M1E native display build exists. |
| G17 Automated tests | PASS (baseline + launch option) | 134 Python tests; M1A; presenter build/tests; input-adapter rebuild; workspace guard. These do not verify a new output/display implementation. |
| G18 Live UI acceptance | PARTIAL | Real Settings runtime observed in live sessions, but no app-first/no-decoration/multi-window acceptance. |

Overall M1E remains **PARTIAL**. The package-selection path is implemented,
but Android HOME/setup activities can start during framework boot and the live
default display still owns StatusBar/Taskbar windows. No system-decoration,
Insets, independent resize, or multi-window behavior is claimed. Next work is
the privileged one-secondary-display prototype described in
`docs/m1e-plan.md` and `docs/m1e-architecture.md`.

## Preserved artifacts and limitations

The Android image, M1D input/graphics source, and prior diagnostic overlays were
not changed. `scripts/run_aaas.py` and its focused tests are the only runtime
source changes so far. Raw probe data and logs remain in the external workspace.
Development-only SELinux and Keystore compatibility remain non-production
security boundaries. No M1E feature commit was created in this audit.
