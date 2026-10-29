# M1E plan: app-first Android windows on Wayland

Status: **IN PROGRESS — one trusted secondary-display output validated; multi-window work pending**
Baseline for this continuation: `162321b` (`master`)
Preservation record: `results/m1e/preservation_manifest.json`

## Product boundary

Android remains the application runtime. KWin owns desktop placement, focus,
decoration, and window lifecycle. AaaS supplies an Android output for each
Android task group that the product chooses to expose. Android Home and global
SystemUI surfaces are not part of normal app presentation. Framework services
remain installed and running where Android applications depend on them.

## Phases

1. **M1E.0 — app-first launch and decoration policy.** Launch a selected,
   installed package directly; select a display policy before the application
   is shown; verify that no Home, status, navigation, Taskbar, or invisible
   system window reserves or intercepts application content.
2. **M1E.1 — task identity and lifecycle.** Maintain an explicit mapping
   between Android task/display identity and the AaaS host window; implement
   Back, close, foreground, background, and failure behavior.
3. **M1E.2 — native window semantics.** Set an application title and app ID;
   make configure/resize, focus, minimize, unmap, and close update Android
   configuration and input mapping rather than stretching an old frame.
4. **M1E.3 — independent windows.** Run two unrelated Android tasks on two
   independently focusable and closable Wayland toplevels in one Android
   runtime. Closing one must preserve the other.
5. **M1E.4 — regression and closure.** Verify M1D, pointer, graphics, memory,
   resource, lifecycle, and evidence requirements. M1E is not PASS until M1E.3
   is demonstrated live.

## Implementation order

1. Keep the M1D single-window runtime as the rollback baseline.
2. `scripts/run_aaas.py --app <package>` resolves a package's Android
   `MAIN`/`LAUNCHER` Activity and uses ActivityManager task state for liveness.
   Settings is the verified package; general compatibility remains untested.
3. The opt-in `--experimental-virtual-display` prototype creates one genuine
   system-owned trusted display, launches Settings task 8 on it, and sends
   Composer virtual output through a second presenter/socket. Android display,
   task, Insets, touch region, rendered screen, input click, and shutdown
   removal have live evidence. Buffer roles are distinct, but their DMA-BUF
   backing aliased in the captured run.
4. Add stable host-window identity after the display owner and task-launch
   boundary are known.
5. Extend output/session management for multiple displays and tasks. Keep
   `wire_v2` and existing input message meanings intact; negotiate a new
   version or use isolated per-output sockets.
6. Add a second application/task, then test independent focus and teardown.
7. Run existing suites and both normal and cgroup/LMKD modes.

## Current verified baseline

- Default and source-LMKD/cgroup sessions reached `RUNNING` and `STOPPED`; the
  enhanced run removed its delegated cgroup.
- The default diagnostic display remains Android display 0 and is preserved.
- The opt-in virtual-display run created Android display 2, a real trusted,
  private, own-content virtual display at 720×1280/240 dpi. Settings task 8
  appeared there, and its rendered Network & internet page was captured in the
  separate Wayland output.
- Composer created HAL virtual display 100 and logged 180 output submissions.
  The virtual presenter imported/submitted 180 frames, released 179, presented
  176, discarded 4, and rejected none. Output and client-target slots are
  separately tracked. Their DMA-BUF inode aliased in the accepted run; a
  distinct-backing path was not proven live.
- WMS/InputDispatcher reported full application bounds and touch region with
  no active StatusBar/Taskbar input window on display 2. The diagnostic primary
  display retains its SystemUI surfaces.
- Broker, framework display, Composer display, presenter, and adapter teardown
  completed on session shutdown. The primary output and v2 stream are retained.
- This is one secondary application output, not two app windows. Resize,
  independent task teardown, custom native title/app ID, and keyboard routing
  to display 2 remain future gates.

## Safety and evidence rules

- Keep the rootfs immutable and deploy checksum-guarded overlays only.
- Do not hide system windows by cropping, transparency, or input overlays.
- Do not uninstall Home/SystemUI packages to make a screenshot look app-first.
- Do not grant launch permissions globally. Any trusted virtual-device/display
  owner must be a narrowly scoped AaaS platform component.
- Do not call Android Binder return success an application interaction result.
- Each acceptance entry identifies automated, live-runtime, or manual evidence.
- Maintain the existing workspace ceiling and reserve; run the workspace check
  before large artifacts or builds.
