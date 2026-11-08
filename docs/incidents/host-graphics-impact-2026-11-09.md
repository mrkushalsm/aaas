# Host graphics impact during relocated M4 runtime checks

Date: 2026-11-09

## Observed symptoms

The operator reported a blank SDDM greeter that accepted a password entered
blindly, and a Qt platform-plugin initialization failure when using Spectacle.
The KDE desktop recovered after the compositor process restarted. Do not restart
SDDM or terminate the current desktop as part of investigating this event.

## Evidence collected

- SDDM's current-boot journal shows its Xorg server and `sddm-greeter-qt6` were
  started at 01:26:39. It records the `Layan` theme load and a successful
  greeter-session start. At 01:49:26 it records successful authentication and
  greeter shutdown. This confirms process/session startup, not that the greeter
  rendered visibly; the reported blank screen is not explained by these logs.
- The SDDM configuration files and `/etc/environment` predate this task. The
  repository changes contain no SDDM configuration, package, or host display
  manager edits. The user's `.profile` Qt theme/style exports also predate the
  task. The current shell has no Qt plugin path or `LD_PRELOAD` override.
- At 01:53:58, `kwin_wayland` (PID 2335896) terminated with SIGABRT. Its core
  backtrace enters `libgallium` and then KWin's OpenGL frame completion path
  (`GLVertexBuffer::endOfFrame`, `ItemRendererOpenGL::endFrame`, and
  `WorkspaceScene::paint`). This is a host compositor/driver crash, not an
  Android process failure.
- The AaaS session active in this period ran the Wayland presenter with an
  Android virtual-display stream. Its log showed submitted frames and presenter
  slot exhaustion without Wayland buffer-release events. The timing and
  rendering path make presenter buffer import/release a plausible trigger or
  stressor for the Mesa/KWin crash. The core does not identify the originating
  Wayland client or prove causation, so this remains a correlation.
- KWin restarted under the existing Plasma session manager. SDDM remains
  running, the desktop is currently active, and no AaaS runner, presenter,
  Android process, or AaaS/Binder mount remains in the host namespace.
- A Qt plugin scan in the user's Spectacle journal enumerated and loaded the
  system Qt 6 Wayland platform plugin, KDE platform theme, and Kvantum style;
  it then unloaded them. A bounded `spectacle --version` check exited normally
  with the current Qt environment and with the theme/style overrides removed.
  The reported failure was not reproduced, and the observed plugin scan does
  not establish that a screenshot capture succeeded.
- The isolated runner uses `unshare` user, mount, PID, and network namespaces.
  BinderFS/proc/sys operations are prepared within that runner namespace; no
  corresponding mounts remain on the host. No task diff operation changes
  system packages, host mount tables, SDDM configuration, or global Qt files.

## Safe correction proposed (not applied)

Disable host Wayland presentation for this installation on this host until the
presenter DMA-BUF import, synchronization, and release path has been validated
without exposing the active KWin session. Keep storage and Android runtime
checks separate from graphical presentation. Re-enable the presenter only
after a bounded isolated compositor test demonstrates correct buffer release,
and after review of the KWin/Mesa crash evidence. No second presenter run was
made during this investigation.

## Current M4 storage evidence and limits

Rootless temporary-directory tests for shared-storage layout, mapped UID/GID
ACL repair, userdata initialization, workspace enrollment, and bundle
installation passed. The complete Python suite passed 475 tests with one
existing skip. These results do not constitute a live shared-storage test in
the relocated Android runtime. The KWin crash blocks further live presenter
acceptance until the proposed correction can be reviewed and safely tested.

The historical Android userdata, original `rootfs_m1b1`, and existing bundle
were not modified by this investigation.
