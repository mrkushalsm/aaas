# M1E status

Status: **PARTIAL — one trusted secondary display and independent Wayland output validated**
Date: 2026-10-30
Baseline: `162321b` (`docs(m1e): align gate labels with verified evidence`)

## Delivered prototype

- `--experimental-virtual-display` starts a system-UID Android display broker,
  creates a real private/trusted/own-content Android virtual display, and
  launches the selected Settings task on it. The normal primary-display path
  remains available and is unchanged in behavior.
- Android assigned display ID 2, unique ID
  `virtual:android,1000,AaaS application output,0`, at 720×1280 and 240 dpi.
  DisplayManager reports `FLAG_PRIVATE`, `FLAG_TRUSTED`,
  `FLAG_OWN_CONTENT_ONLY`, and `canHostTasks=true`. The broker requests the
  display using system-owned DisplayManager APIs; it does not expose Binder to
  host clients.
- Settings task 8 and its SubSettings Activity were observed on display 2.
  WMS reports full-display app/task bounds with no non-decor Insets. The
  display-specific InputDispatcher window list contains Settings with a
  full-display touch region; StatusBar and Taskbar input windows remain on
  diagnostic display 0.
- Composer reports one virtual HWC display (ID 100) only when its dedicated
  virtual-output Wayland endpoint is connected. It retains output-buffer slots
  separately from client-target slots, waits both acquire fences, routes
  frames through a second transport/presenter, and returns the host release
  fence to Android. The primary output continues using wire protocol v2 and its
  original presenter.
- In the instrumented live run, the virtual presenter recorded 180 imports and
  submissions, 179 releases, 176 presentations, 4 discards, and zero rejects.
  These counts are not treated as proof that all frames were displayed.
- A controlled host `/dev/uinput` pointer click was delivered to Android
  display 2 and opened Settings' Network & internet page. The captured
  screenshot is real Android content from that output; its path and hash are
  in `results/m1e/live/trusted_virtual_display.json`.
- Shutdown requests the broker to release its `VirtualDisplay` and
  `ImageReader`, waits for the display ID to clear, then stops the one-shot
  init service. SurfaceFlinger and DisplayManager logged display removal and
  Composer logged virtual display destruction.
- The launcher now uses ActivityManager task/activity state for selected-app
  liveness rather than assuming the Android process name equals the package.
  This avoids premature session termination for apps with custom process
  names; exact task-ID ownership is still future work.

## Output-buffer ownership caveat

The output buffer and client target are distinct Composer API roles and have
separate slot records. In the captured Settings run, both handles referred to
the same DMA-BUF inode (`alias=1`), so Composer correctly waited both acquire
fences and forwarded the allocation without a self-copy. The different-backing
copy path now has DMA-BUF CPU-sync calls and a host row-copy component test,
but it has not been exercised with real DMA-BUFs in a live Android run.
Therefore this prototype does **not** establish that SurfaceFlinger always
provides physically separate allocations, nor does it establish concurrent
multi-display ownership. Keep the primary output as a diagnostic baseline.

### 2026-10-30 continuation probe

A bounded live experiment retained one previous `ImageReader` image while
running the same virtual-display session, to see whether consumer retention
would make the output and client target use separate allocations. It did not:
all four sampled pairs still had the same DMA-BUF device/inode. The presenter
imported, submitted, and presented 65 frames with 64 releases before shutdown,
zero discards, zero rejects, and 65 explicit-sync frames. Shutdown reached
`STOPPED`, removed the Android task, and sent presenter `CLOSE`. No screenshot
was captured in this probe. The temporary broker change was reverted; the
committed broker behavior and primary display path are unchanged.

The pinned Android source clarifies the result: GPU-only virtual-display
composition uses the sink/output buffer as the GPU producer buffer, while
`CompositionType::Mixed` uses a scratch source. Therefore the alias is expected
for the observed GPU-only path. It does not validate the Composer's
distinct-backing copy path. Keep the one-display cap until that copy path is
covered by a distinct-allocation correctness test and multi-display resource
isolation is implemented. The host test verifies different memfd backing,
strides, visible pixel bytes, and unchanged padding; it does not prove DMA-BUF
cache behavior. The copy branch now uses DMA_BUF_IOCTL_SYNC around CPU access,
rejects unsupported non-RGBA/BGRA formats, and fails the frame on sync/copy
errors. The patched regular Composer reached RUNNING and STOPPED in both
default and source-LMKD/cgroup sessions. A patched virtual Composer also
completed a live GPU-only session with 66 presented frames, zero rejects, and
no invocation of the distinct-backing branch. Its build and evidence limits are in
`results/m1e/build_receipts/distinct_copy.json`,
`results/m1e/live/distinct_backing_probe.json`, and
`results/m1e/live/distinct_copy_component.json` and
`results/m1e/live/composer_copy_runtime_smokes.json`.

## Remaining M1E work

- Only the installed Settings application has been exercised on the secondary
  display. General package compatibility and launch-failure cases remain
  untested.
- The experiment creates one secondary display and one independent Wayland
  toplevel in addition to the diagnostic primary window. It does not yet
  support two independently managed application tasks/windows.
- Android display resizing, native app title/app ID, minimize/unmap behavior,
  task-specific close, and independent output teardown while another app
  continues are not implemented or verified.
- The primary diagnostic display still has SystemUI StatusBar/Taskbar windows.
  The secondary display has no corresponding active input windows or Insets
  sources in the captured WMS/InputDispatcher state. No broad SystemUI removal
  is claimed.
- No induced memory-pressure experiment was run in this continuation. The
  default and source-LMKD/cgroup smoke sessions reached RUNNING and stopped
  cleanly; the enhanced session removed its delegated cgroup.

## Verification

The prior regression run is recorded in `results/m1e/acceptance.json`. In this
continuation, 142 Python tests, M1A, presenter build/tests, input-adapter
rebuild, and the workspace guard passed again. The bounded live
distinct-backing probe is separately recorded above. Default, enhanced, and
experimental virtual-display smoke evidence remains in the baseline records.
M1D keyboard and desktop-IME behavior remain the established
baseline; this prototype additionally verified display-targeted pointer
delivery, but did not repeat every M1D manual keyboard test.

Overall M1E remains **PARTIAL**. This continuation passes the first trusted
secondary-display/output experiment. It is not full M1E acceptance until two
independent Android app windows, real resize/configuration updates, and their
independent input, lifecycle, and buffer cleanup are demonstrated.
