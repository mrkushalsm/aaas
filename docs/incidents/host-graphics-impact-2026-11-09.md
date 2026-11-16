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
  Android virtual-display stream. Its log shows 32 submitted CPU-staged frames,
  then `slot_registry_exhausted` for the next frames. The presenter source
  confirms that `release_ack=true` on this rejection means its AaaS IPC
  `buffer_rejected` reply was sent; it is not a Wayland `wl_buffer.release`
  event. The Android runner later logged `Error flushing display: Broken pipe`
  after KWin died. The timing and rendering path make the presenter a plausible
  trigger or stressor for the Mesa/KWin crash. The core does not identify the
  originating Wayland client or prove causation, so this remains a correlation.
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

The latest stopped Android session shows user 0's `emulated;0` volume becoming
`MOUNTED` through normal framework startup. The AaaS startup hook nevertheless
issued a second `sm mount emulated;0` about six seconds later; `vold` rejected
the duplicate request with `-16` because the volume was already mounted. The
mount remained present, MediaStore reported `external_primary` mounted, and
the shared Android media path was backed by the relocated workspace. The source
runner now checks the volume state before requesting a mount and exits with a
clear diagnostic if it remains unmounted. The focused runner tests and full
Python suite pass after this source change (476 tests, one existing skip); a
temporary-shell regression covers already-mounted, unmounted, and failed-mount
states. The already installed bundle still contains the pre-fix runner, and no
live Android test has been run with the correction.

Rootless temporary-directory tests for shared-storage layout, mapped UID/GID
ACL repair, userdata initialization, workspace enrollment, and bundle
installation passed. These results do not constitute fresh end-to-end
shared-storage acceptance. The KWin crash blocks further live presenter
acceptance until the proposed correction can be reviewed and safely tested.

The historical Android userdata, original `rootfs_m1b1`, and existing bundle
were not modified by this investigation.

## Follow-up: isolated headless storage verification

After the above incident review, the relocated runner was refreshed from the
corrected source (`runtime/scripts/run_aaas.py`, SHA-256
`1237e264658ad3da7df8b37cc1cee24775f0b02b6387d44870adaf5eab02fd93`). Three
headless sessions (`m1b84_session_xec0v0at`, `m1b84_session_h3osoj6k`, and
`m1b84_session_35eaufrt`) reached `RUNNING`, observed `sys.boot_completed=1`,
`system_server`, `vold`, and the normal `emulated;0 mounted` volume. The
idempotent hook logged `AAAS_EMULATED_STORAGE_ALREADY_MOUNTED` and did not issue
a duplicate mount. Android-created shared-storage sentinels were visible on the
host with matching SHA-256 values; a host-created file was scanned by Android
MediaScanner and returned by MediaStore as
`content://media/external_primary/file/18`. A prior Android-created sentinel
remained visible and queryable after stop/start as
`content://media/external_primary/file/19`. Each session stopped with status
`STOPPED`; no AaaS runner, presenter, or installation workspace mount remained
in the host namespace. Detailed machine-readable results are in
**`results/m4/headless-shared-storage-2026-11-09.json`** (maintainer archive only).

These tests did not launch the Wayland presenter, access the active KDE
compositor, or exercise the SAF picker. Android-to-host writing used the
headless session shell rather than an Android app permission context. The
KWin/Mesa crash remains correlated but causation is not established; this
follow-up does not resolve or attribute that crash and does not close graphical
acceptance.

## Later isolated-compositor storage run (2026-11-09)

The presenter was subsequently exercised only against a disposable Weston 15
headless compositor running llvmpipe in isolated user, mount, PID, and network
namespaces. The active KDE Wayland socket was not passed to the runner. An
Android `ACTION_OPEN_DOCUMENT` selection returned the expected host file URI
and the app read its content. One bounded presenter session reported 12 frame
presentations, 11 compositor buffer releases, one buffer invalidated during
teardown, and zero outstanding buffers. Another picker session sent real input
events to Android display 2 and returned the same URI. Test session IDs and
hashes are recorded in `results/m4/saf-shared-storage-2026-11-09.json`.

This is bounded isolated-test evidence for the storage picker flow only. The
compositor had no physical output, and no human visual inspection was made.
Separate synthetic burst testing did not model the Composer producer's
two-frame backpressure contract and is not evidence of a fix for the earlier
32-slot exhaustion. The KWin/Mesa crash's cause remains undetermined; no claim
is made that the presenter is safe against the active host compositor. No
system graphics setting or active desktop process was changed.

## Presenter synchronization source review (2026-11-09)

A source review found a distinct acquire-synchronization defect in the
presenter's no-syncobj fallback. If an incoming DMA-BUF carried an acquire
`sync_file` but the compositor did not negotiate `linux-drm-syncobj-v1`, the
presenter closed that fence immediately before attaching the buffer. It now
waits up to two seconds for the actual fence to signal before submission. On
timeout or wait error it rejects the unimported buffer and returns its acquire
dependency through the existing transport rejection path. This does not fake
completion or change the normal Wayland release ownership rule.

The focused source-contract test passed, the native presenter rebuilt with
`-Werror`, and the complete Python suite passed (487 tests). Existing
historical Weston/KWin/Sway evidence continues to show balanced ownership in
its recorded sessions, but no new presenter session was run in this follow-up.
The host presenter allocates/imports GBM DMA-BUFs through a host DRM render
node; this host has no isolated render device, and that node shares the host
graphics driver. Repeating a graphical load test could therefore affect the
active KDE session even when Weston is on a private socket. No fresh
Wayland-frame, Android-window, resize, multi-window, or compositor-disconnect
test was run. The active KWin session remained running after the bounded
64×64 GBM/syncobj exercise in the existing wire-v2 native test; no conclusion
about KWin safety follows from that small allocation test.

The `slot_registry_exhausted` trace follows 32 imported CPU-staged buffers and
then rejects the next buffer. The producer implementation uses two GBM
buffers and waits until one is released before reuse. The prior 96-frame burst
ignored that producer contract and was correctly rejected at the registry
cap. This explains that burst result, but does not establish why the earlier
KWin/Mesa crash occurred. The core stack points into KWin's Mesa Gallium frame
completion path, without identifying a client or proving causation. KWin
presentation remains an unresolved safety gate.

## Software-isolated presenter follow-up (2026-11-09)

The active KWin session was not used. Weston 15.0.2, pinned to
`de09947fc128d4c7af3d8e292a1044a812aee954`, ran with the headless backend and
pixman renderer. Weston and the presenter each ran in bubblewrap user, mount,
PID, network, IPC, UTS, and cgroup namespaces with a private runtime directory
and `/tmp`; `/dev/dri` was empty in both namespaces and the active KDE socket
was not passed in. A synthetic producer exercised the presenter's real
Wayland SHM buffer path with two memfd buffers and only reused a buffer after
the transport returned it following compositor release.

Two sequential 1,024-frame sessions and two sequential 256-frame sessions
completed. Each session reported all submitted frames imported, zero
rejections, actual Wayland release callbacks for all but the final attached
buffer, one separately counted teardown invalidation, and zero ownership
remaining after teardown. The producer observed a maximum of two buffers in
flight. Headless presentation-feedback counts varied and were lower than
submissions; no physical display or human-visible presentation was observed.
Test records and artifact hashes are in
**`graphics-software-isolated-2026-11-09.json`** (maintainer archive only).

An initial run completed frame accounting but crashed in cleanup because the
new `wl_shm`-only mode unconditionally destroyed a NULL linux-dmabuf proxy.
The core backtrace identified `zwp_linux_dmabuf_v1_destroy` called with NULL.
Cleanup now checks the optional proxy; subsequent strict native builds and
repeated runs exited cleanly. This is a confirmed test-mode teardown defect
and correction, not an explanation of the earlier KWin crash.

The acquire-fence fallback now polls while dispatching Wayland and input
events, release timelines, close acknowledgments, and scheduled resize work;
it also flushes queued Wayland requests and cancels on shutdown. It retains
the two-second deadline and rejects timeout/error without fabricating
completion. The software test path deliberately has no DRM device, so this
follow-up did not validate an actual DRM `sync_file`, explicit sync, DMA-BUF,
GBM, or Android Composer frame. No Android session, input, resize, concurrent
multi-window, or compositor-disconnect workload was run. KWin/Mesa causation
remains unproven; active KDE presentation remains unapproved. The host KWin
process remained active after these tests, and no test presenter/compositor
process remained.

## Forensic comparison and staged-buffer bound (2026-11-09)

The accepted M2 source head was `11f91ec514249f3c22fea318eb7e4edb23316466`.
The last repository head before the crash sessions was
`35c5cbe947651a1174e8578d3261010d90f42726`; this is only an upper bound because
the historical session manifests did not record the exact presenter executable
hash or checked-out source revision. At those two source heads,
`gpu_presenter.c`, `wire_v2.c`, and `sync_util.c` are byte-identical. The only
change in `wayland_host_presenter.c` is its default socket path. This makes a
tracked presenter source regression less likely, but does not prove which
executable was loaded during either session.

The successful M2 session `m1b84_session_7n1k5nlw` recorded 238 commits and 238
actual Wayland releases, with zero outstanding ownership. The later successful
M4 Settings/Contacts session `m1b84_session_we0dsscc` recorded 92 commits and
92 releases, also with zero outstanding ownership. Both ran on KWin 6.7.5; the
recorded Mesa package version was already installed before the accepted M2
session. The M4 Composer overlay hash was
`668bfd8198d5457d50a17b53c0ee37d5693b7ea34133e90441c2903c61a55f3d`.

The recorded Composer binaries differ across these executions: the 00:39
portrait session used hash `cd55e7418a469e84c839bfec287b1bce238a43daa28f50900acf3174c17e3a46`,
and the 01:53 experimental virtual-display session used
`456d2201cb28ccccc8f2b35879ea3ebe8ebf740bf116aac34019c7cf34554894`. Both
crash sessions used the same SwiftShader and framework overlay hashes as the
successful M4 control, while the Composer variants differed; the service
overlay also differed between the two crashes. The source/build receipts do
not establish a Composer code regression from these hashes alone.

In the 00:39 incident session `m1b84_session_plvyq3rz`, 32 frames were copied
to presenter staging BOs and committed, but no actual `wl_buffer.release` was
logged. In the 01:53 session `m1b84_session_5pll6kjw`, 32 were copied and
committed, with one release. Both used 720×1280 frames with 2944-byte stride.
The first advertised explicit-sync capability and used Wayland syncobj on its
frame commits; the second did not advertise explicit sync and used the
implicit Wayland path. The commit trace's `explicit_sync` field describes
presenter/Wayland syncobj use; it does not prove an incoming Composer acquire
sync-file was present. The incident logs do not record incoming acquire-FD
presence. The later acquire-fence fallback correction therefore is not
established as a cause of either crash.

For both sessions the Intel `execbuf ENOMEM` journal warning followed the final
commit/slot-cap interval. KWin's SIGABRT followed that warning by about 14.7
seconds. The presenter's broken pipe followed KWin's abort. Presenter event
times are monotonic and align with the same-boot monotonic journal. This is a
strong temporal association, not proof that AaaS caused Mesa's abort. Coredump
metadata has the same main-thread path through `libgallium`, KWin
`GLVertexBuffer::endOfFrame`, `ItemRendererOpenGL::endFrame`, and
`WorkspaceScene::paint`; the core bytes and abort detail were not available.
The crash therefore remains unattributed.

The 32 entries did not imply 32 distinct Composer source buffers. The
transport's `COPY_COMPLETE` returns a source allocation after the CPU staging
copy, while the presenter retains a separate staging BO and Wayland buffer
until actual compositor release. Consequently the Composer's two source
buffers did not bound presenter-owned staging allocations. The previous 32
slot cap prevented indefinite allocation but admitted 32 live staging buffers
before rejecting subsequent frames.

For 720×1280 frames at stride 2944, those 32 buffers represent about 115 MiB
of row payload (`32 × 2944 × 1280`) before GBM allocation overhead. The Intel
`execbuf ENOMEM` warning shortly after the last commit makes retained staging
memory a possible contributor. Actual BO residency, concurrent GPU clients,
and the Mesa assertion are unavailable, so memory pressure is not established
as the root cause.

The presenter now limits early source-copy credits to two active staged slots,
defers later `COPY_COMPLETE` until the corresponding actual Wayland release
returns source ownership, and caps active staged imports at four. Over-limit
frames are rejected without allocating a stage BO. This corrects the
demonstrated staged-resource/backpressure defect and bounds the local staged
resource set; it is classified `CONFIRMED_DEFECT_NOT_PROVEN_CAUSAL`, not as a
KWin crash fix. The native presenter rebuilt with `-Werror`; the policy test
passed. Two isolated pixman/Weston SHM runs each completed 1,024 submissions,
observed 1,023 releases plus one teardown invalidation, zero rejects, and zero
outstanding buffers. SHM does not execute the GBM staging-credit branch.

The machine-readable comparison and exact artifact references are in
**`graphics-known-good-vs-incident-2026-11-09.json`** (maintainer archive only).
The active KDE render nodes are shared host devices, so no post-fix GBM or
DMA-BUF presentation run was made. The historical KWin/Mesa cause and
accelerated-path correction remain unverified; active-KWin presentation is
still not approved.

### Staging-backpressure follow-up (2026-11-09)

The historical coredump list contains 12 KWin `SIGABRT` entries from 00:39
through 01:53 local time. Session logs show recent AaaS presenter commits at
each corresponding crash time and a broken display connection as KWin exited.
The first and last incidents are the detailed cases above; the other ten
sessions show 32 or 33 commits, zero or one observed Wayland release, and
varying counts of slot-cap rejections. This confirms AaaS presentation activity
coincided with the repeated crashes. It still does not establish which client
or resource caused Mesa to abort: the cores remain inaccessible and contain no
recoverable assertion detail. The full per-PID/per-session table is in the
**forensic comparison artifact** (maintainer archive only).

The staged-resource defect was then tested on a disposable QEMU/KVM guest with
its own virtio-GPU DRM device and Debian Weston GL compositor. The guest had no
physical GPU passthrough, virgl, host Wayland socket, or active KDE socket; its
renderer was llvmpipe. The production presenter imported GBM-exported
DMA-BUFs, received real guest Wayland release callbacks, recovered after a
paused compositor, and rejected an over-cap probe before allocating a fifth
staging buffer. The compliant two-source-buffer producer completed 160 frames
in the healthy run and another 160 after delayed-release recovery. A 64-frame
cap-probe run also completed and drained ownership. Peak active staging was
four and all runs ended with zero outstanding buffer ownership.

This verifies the staged-credit/GBM lifecycle on a virtual DRM device. It does
not validate Intel hardware, the host Mesa build, explicit sync files, Android
Composer/SurfaceFlinger, or the original KWin failure. Staging accumulation is
a confirmed resource-retention defect and its bound is now exercised on the
production code path; KWin crash causality and active-host-KWin safety remain
unresolved. See
**`staging-backpressure-acceptance-2026-11-09.json`** (maintainer archive only).

## Controlled live retest (2026-11-09)

A controlled active-KWin test was authorized for the development runtime. The
first attempt after that authorization reproduced a KWin SIGABRT in Mesa
Gallium. The AaaS presenter had selected NVIDIA renderD128 while KWin advertised
Intel renderD129 as its dma-buf main device, and AaaS had forced implicit sync.
The presenter committed three early frames before release progress stalled;
Intel logged execbuf ENOMEM before the KWin abort. This is a concrete
configuration mismatch and a plausible resource/synchronization contributor,
but the evidence does not prove it caused Mesa's abort.

The runtime now selects the compositor-advertised main render node, fails
closed if multiple devices exist and that identity is unknown, removes the
hardcoded renderD128 fallback, and permits the Wayland explicit-sync
negotiation instead of forcing implicit sync. On subsequent sessions using
Intel renderD129, presenters negotiated explicit sync and logged thousands of
commits with matching actual Wayland releases, bounded peak active staging
slots, and zero outstanding ownership at shutdown. KWin remained alive during
those retests. These results verify the corrected configuration on this host;
they do not establish the root cause of the earlier crash or certify general
KWin/Mesa safety.
