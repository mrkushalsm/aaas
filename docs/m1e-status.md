# M1E status

Status: **PARTIAL — two-app rendering, independent resize, visible typing and vertical scrolling in both apps, per-window close/reopen, and app-mode primary-output suppression are live; focus-edge and stability coverage remain incomplete**

Date: 2026-10-31

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
in this run. A later cap-two retry (described below) reached both Android activity launch
commands and both display-specific input HELLO handshakes, then failed before
RUNNING because Android lowmemorykiller reported exhausted host/container swap
and killed both app processes. This supersedes the earlier second-presenter
readiness diagnosis.

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

This was bounded live evidence for closing one output while preserving the
other task/presenter, followed by last-window shutdown. Reopening and input
isolation were verified in later sections; Android minimize lifecycle sync
remains unverified.

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
| Per-window task/display close and reopen | PASS, bounded live | Two create-after-destroy cycles reused each slot while the other app remained RUNNING; final stop shut down the shared runtime. |
| Buffer/fence terminal ownership | PASS, bounded live | Both summaries show imports=submissions=releases, zero invalidated/outstanding. |
| Single-output Android framebuffer resize | PASS, bounded live | 720×1280 → 960×1156 → 720×1280; Composer and presenter source dimensions/strides matched after each transition. No screenshot or post-resize coordinate test was captured. |
| Concurrent two-output resize | PASS, bounded live | Settings and DeskClock both transitioned from 720×1280 to matching 960×1156 Android source buffers. Settings then resized independently to 960×578 with a matching source buffer while DeskClock remained at 960×1156 / generation 2. Resize-back-to-original and landscape/burst sequences remain untested. |
| Keyboard on both outputs, vertical scrolling, focus isolation | PARTIAL, visible synthetic text and vertical scroll in both; focus warnings remain | Settings Search and Contacts editor visibly accepted text in the prior live session. The 2026-10-31 follow-up corrected Android 16 `input` argument order; Settings All apps and Contacts editor then visibly scrolled independently in default and enhanced runs. Each scroll changed only the targeted app rectangle. Transient InputDispatcher no-focused-window warnings and a one-time initial key miss remain documented. See `scroll_routing_fix_20261031.json`. |
| Reopen app without restarting runtime | PASS, bounded live | Settings reopened as task 10/display 4 and DeskClock as task 11/display 5 in the same session. Third launch returned `capacity_exhausted`. |
| Minimize/unmap lifecycle | PASS, bounded user-visible restore; Android lifecycle sync NOT TESTED | KWin minimize/restore hid and restored Contacts while Settings remained visible; both runtime slots stayed RUNNING. No Android pause/resume synchronization is claimed because the presenter has no standard minimized-state signal. |
| Hide primary diagnostic presenter in normal app mode | PASS, bounded live | Experimental app sessions with selected apps skip the primary presenter; Android display 0 remains intact. `--show-primary-diagnostic` restores diagnostic presentation. This verifies no primary Wayland output, not removal of internal Android SystemUI. |
| Distinct DMA-BUF copy on real Mixed composition | NOT TESTED LIVE | GPU-only alias path and component-level stride/copy tests remain as previously documented. |
| SwiftShader JIT crash freedom | PARTIAL | One separate live SurfaceFlinger JIT SIGSEGV remains unresolved. |
| Resize/JIT relationship | OPEN | The resize follow-up did not reproduce the historical JIT SIGSEGV; it logged two `Unexpected onFrameCommitted in Gpu state` warnings. The old fault remains unsymbolicated and open. |

## Verification

The final automated runs for this continuation passed:

- `python3 -m unittest discover -s tests -v`: **170 tests** in the latest run, including an Android 16 input-shell argument-order regression test.
- `make -C experiments/m1a test`.
- `make -C experiments/m1a -B build/wayland-host-presenter test`.
- `make -C experiments/m1c/input_adapter -B all`.
- `make -C experiments/m1b/composer_aaas test`.
- `make -C experiments/m1e/display_broker -B all`.
- `python3 scripts/android_workspace.py --workspace /run/media/mrkus/Homework/aaas-workspace check`.

The external workspace remained on `/dev/sda2` (NTFS3, UUID
`A2ACEDF2ACEDC0C1`) at 22.9 GB used, under its 80 GiB ceiling with the
20 GiB safety reserve. Build hashes and IDs are in
[`window_resize_lifecycle_20261030.json`](../results/m1e/build_receipts/window_resize_lifecycle_20261030.json).

After adding resource snapshots and the app-mode presentation option, the
Python suite passed **164 tests** in the earlier resource-diagnostics run; the focus-sync follow-up passed **165 tests**. M1A, forced presenter rebuild/tests, forced
input-adapter build, Composer component tests, forced display-broker build,
and the workspace guard passed again. Default and enhanced two-app app-mode
sessions reached RUNNING then STOPPED; the enhanced session cgroup was removed.
The explicit primary diagnostic opt-in also reached RUNNING and stopped cleanly.

## Remaining live work

1. Expand input acceptance for horizontal scroll, dedicated touchpad-source routing, and post-resize coordinate corner cases.
2. Verify two-output resize-back, landscape, and resize-burst coverage.
3. Keep focus-transition warnings and the one-time first-key miss under observation; bounded sessions had no ANR.
4. Continue bounded investigation of the unresolved SwiftShader JIT/SF crash.

Overall M1E remains **PARTIAL**. A new bounded live session used Settings and
the installed Android Contacts editor in separate windows. Controlled
`/dev/uinput` typing visibly changed both applications, Android focus followed
the selected window, and no InputDispatcher ANR signature occurred. A KWin
minimize/restore cycle preserved the other window and restored the Contacts
editor. Both outputs produced matching native 950×1100 Android buffers after
resize, and each presenter ended with imports=submissions=releases and zero
outstanding buffers. The initial scroll attempt was not accepted because it targeted the Settings
home page rather than a confirmed scrollable view. A later scrollable-list and
Contacts-editor experiment exposed and fixed Android 16 argument ordering;
visible independent vertical scrolling then passed in both default and
enhanced runs. See
[`scroll_routing_fix_20261031.json`](../results/m1e/live/scroll_routing_fix_20261031.json). Transient InputDispatcher no-focused-window warnings, horizontal/touchpad-specific scroll coverage, full resize matrix, and the historical SwiftShader JIT crash remain open.

The minimize limitation is confirmed in the host source: the presenter binds
`xdg_wm_base` no higher than version 3, and `toplevel_configure()` discards the
state array. No supported hidden-state signal is consumed, so M1E does not
claim Android task pause, producer suspension, or frame throttling on minimize.

### Two-app visible input and minimize follow-up (2026-10-31)

The runtime reused the installed `com.android.contacts/.activities.ContactEditorActivity`
as an ordinary-app input target; no custom privileged test APK was built. Its
First name and Last name `EditText` fields provided visible Android-side
consumption evidence. In one shared session (Settings task 8/display 2 and
Contacts task 9/display 3), controlled `/dev/uinput` text appeared as `alpha`
in Settings Search and `beta`/`hii` in Contacts. A later focus sequence
changed each focused app independently, and Ctrl+A replaced the Settings query
with `beta` while the Contacts fields stayed unchanged. The screenshots are
[`input_two_apps_alpha_beta_20261031.png`](../results/m1e/live/input_two_apps_alpha_beta_20261031.png),
[`input_two_way_focus_20261031.png`](../results/m1e/live/input_two_way_focus_20261031.png),
and the Ctrl+A capture referenced in the JSON evidence.

KWin minimized and restored the Contacts window using its normal window state.
Settings remained visible during minimization; both app slots remained RUNNING;
restoring Contacts showed the editor contents intact. This establishes visible
host-window restore behavior only, not Android Activity pause/resume semantics.
Screenshots are linked from the same evidence record.

After KWin resized both toplevels to 950×1100, each presenter first rejected
one stale 720×1280 transition frame, then imported a matching 950×1100 source
frame with 3840-byte stride. Synthetic text editing remained visible after
resize. The run reached STOPPED in both journal and status sentinel. Settings
ended at 1837/1837 imports/submissions/releases and Contacts at 1822/1822;
both had zero teardown invalidations and zero outstanding buffers. No
InputDispatcher ANR or SwiftShader JIT SIGSEGV was found in this session log,
but 13 transient `Focused display ... does not have a focused window` warnings
were logged while the other display had focus.

At this earlier checkpoint, scrolling remained unverified: the initial trial
used the Settings home view and screenshots did not change. Subsequent testing
confirmed per-output scroll on actual scrollable views and identified the
argument-order defect; see the current scroll acceptance section below.


### Android 16 per-output scroll routing correction (2026-10-31)

Source inspection of pinned Android 16 [`InputShellCommand`](https://android.googlesource.com/platform/frameworks/base/+/99b01a65cc4c104933788b3143285ab6bae65827/services/core/java/com/android/server/input/InputShellCommand.java) found it parses the optional input-source token before the optional `-d DISPLAY_ID`. The per-display
adapter had emitted `input -d DISPLAY mouse scroll ...`; it now emits
`input mouse -d DISPLAY scroll ...`. A focused regression test checks this order.
The adapter rebuilt successfully (SHA-256
`0c99c919f4d9ef484a70fbe3664a5f17a884ac46748af6476456256e6e692fb1`, build ID
`85eeab0132a204c0e7b3340fa099652dd99fd018`).

In default mode, a vertical wheel sequence visibly moved Settings' All apps
list by 132,813 changed pixels while the Contacts output changed zero pixels.
Scrolling Contacts' new-contact editor changed 232,138 pixels in its output and
zero in Settings. Enhanced source-LMKD/cgroup mode reproduced both operations
(132,994 and 232,138 target pixels, zero in the other output for each). Both
runtime journals and sentinels reached STOPPED; the enhanced delegated cgroup
was removed. Presenters ended with imports=submissions=releases, zero outstanding
buffers, and no teardown invalidations. The screenshots and raw session hashes
are in [`scroll_routing_fix_20261031.json`](../results/m1e/live/scroll_routing_fix_20261031.json).

This accepts bounded vertical mouse-wheel routing/isolation on these two views.
It does not cover horizontal scrolling, dedicated touchpad gesture-source
routing, every resize corner, or Android Activity lifecycle synchronization
with minimize. The broader keyboard/focus matrix and SwiftShader JIT residual
risk remain open, so M1E stays PARTIAL.

### Android focus synchronization and dynamic app reopening (2026-10-30)

The earlier Settings InputDispatcher ANR was traced to host-only Wayland focus:
the presenter changed its local focus state while Android still focused the
other display/task. Commit `54ac74d` now sends a nonce- and focus-generation-
tagged request to the system-owned display broker, which activates the task
through Android 16 `ActivityTaskManager.setFocusedTask()` before the adapter
accepts keyboard focus. Five live KWin transitions matched Android's focused
display/window state in the earlier follow-up; this continuation also recorded
focus acknowledgements for recreated Settings task 10/display 4 and DeskClock
task 11/display 5. No InputDispatcher ANR signature was present in the new
session logcat. This does not prove application consumption on every app.

The foreground two-output session now exposes a private, mode-0600 Unix control
socket and `scripts/aaasctl.py` commands for `list`, `launch PACKAGE`,
`close SLOT`, and `stop`. A launch uses a free one of the two provisioned output
slots: the host starts that slot's presenter, the broker creates a new trusted
Android display, and the Android session runner starts a display-targeted input
adapter and resolved launcher Activity. The Android-assigned display ID is
published by the broker; task/display IDs are not reused as constants. Creation
is bounded to two concurrent outputs. A third launch returns
`capacity_exhausted`. A session started without `--app2` has only one Composer
transport and explicitly rejects dynamic launches with
`capacity_requires_two_output_session`.

The default diagnostic-LMKD live session `m1b84_session_r06sumim` performed two
create-after-destroy cycles without restarting Android:

1. Settings task 8/display 2 closed; DeskClock task 9/display 3 remained
   RUNNING. Settings reopened as task 10/display 4 and produced frames.
2. DeskClock task 9/display 3 closed while Settings remained RUNNING. DeskClock
   reopened as task 11/display 5 and produced frames.
3. A third package request returned `capacity_exhausted` without changing the
   two active windows.

The captured side-by-side screenshot records Settings and DeskClock after the
first reopen in
[`dynamic_reopen_two_windows_20261030.png`](../results/m1e/live/dynamic_reopen_two_windows_20261030.png).
The structured transaction, Android IDs, log hashes, capacity result, and
ownership summaries are in
[`dynamic_reopen_control_20261030.json`](../results/m1e/live/dynamic_reopen_control_20261030.json).
At final shutdown the state journal and status sentinel were both `STOPPED`,
the broker acknowledged `released`, and presenter summaries showed no
outstanding or teardown-invalidated buffers. The enhanced source-LMKD/cgroup
session `m1b84_session_0i1yonse` also reopened Settings as display 4 while
DeskClock remained active, then stopped cleanly; cgroup `memory.events` had
zero OOM counters and the delegated hierarchy was removed.

Keyboard behavior remains bounded. The recreated Settings SearchActivity was
opened on display 4 and the caret appeared, but a nonsensitive `/dev/uinput`
fixture did not produce a confirmed visible text change in this session.
DeskClock's tested Clock Activity still has no editable field, so its adapter
events are not evidence of app consumption. The earlier visible Settings text
entry remains valid; two-app visible keyboard consumption, per-output scroll,
and post-resize input are still PARTIAL/NOT TESTED. The historical SwiftShader
JIT fault remains unexplained.


### Capacity-two retry and low-memory failure (2026-10-30)

The two-app launcher now builds/selects a Composer configuration advertising
two virtual outputs. Its runtime log reports two independent transport sockets,
`getMaxVirtualDisplayCount -> 2`, and Composer display IDs 100 and 101. Settings
launch on Android display 2 and DeskClock on display 3 both returned `Status: ok`;
both input adapters received HELLO, and both presenters imported and released
frames (144/144 and 127/127, with zero outstanding buffers at teardown).

The session did not reach `RUNNING`. Android logcat recorded repeated
lowmemorykiller decisions because memory watermarks were breached and swap was
far below its 801380 kB threshold. It killed Settings and DeskClock, among other
processes. This identifies the previous readiness failure as memory pressure,
not a missing second-presenter HELLO. The attempt did not produce a valid
simultaneous-window screenshot and establishes no new UI/input acceptance.
Host swap was effectively exhausted after the run, so no immediate retry was
started. The two-output build identity, state history, and raw log hashes are
in [`two_output_capacity_memory_pressure_20261030.json`](../results/m1e/live/two_output_capacity_memory_pressure_20261030.json).

The capacity-two runtime configuration is now selected by the two-app
experimental launch path; one-app mode retains its existing Composer overlay.
This does not resolve two-output resizing, per-output keyboard/scroll testing,
app reopen, minimize, or the historical SwiftShader JIT crash. Primary
diagnostic presentation was still present at the time of this earlier record;
its later app-mode suppression is documented below. Overall M1E remains
**PARTIAL**.


### Two-app LMKD/memory comparison (2026-10-30)

The original pre-`RUNNING` failure used the default diagnostic `/system/bin/lmkd`
overlay (SHA-256 `9780759b…`). Its `killinfo` records show only 68 KiB of host-visible
free swap at Settings victim selection, with low/min watermarks still breached;
Settings (RSS 264,256 KiB, adj 102) and DeskClock (RSS 237,560 KiB, adj 0) were
killed after earlier cached-process kills. The failed attempt did not record
contemporaneous host PSI, `MemAvailable`, or a per-session cgroup event baseline,
so the particular host workload that exhausted swap cannot be identified.

A bounded same-mode comparison then ran one app and two apps under the same
default diagnostic LMKD. Both reached `RUNNING`, remained there for 20 seconds,
and shut down to `STOPPED`; neither log recorded an LMKD kill. During the two-app
run, host `MemAvailable` reached a minimum of 5,039,856 KiB, `SwapFree` 1,228,836
KiB, and memory PSI `full avg10` peaked at 0.18%. This shows the prior failure
was not deterministic for the two-app workload.

A bounded source-LMKD plus delegated-cgroup run also reached `RUNNING` and
`STOPPED`. It loaded source-built LMKD (SHA-256
`a36135b6948342163186fe57acb9de0245fe00aeafcb9556c48a2e4c52f291ce`, build ID
`96eadc7560482189dfeb5772c0150e3728cc30ac`) from Android 16 source revision
`291e98ff95c3ce2647e44a29628dfae51c5d2634`. LMKD reclaimed ten background/cache
processes (adj 955–985) while Settings and DeskClock survived. During this run,
minimum host `MemAvailable` was 4,927,184 KiB, minimum `SwapFree` 1,207,828 KiB,
and memory PSI `full avg10` peaked at 0.72%. The cgroup policy monitor reported
10 ticks, 0 errors, 93 transitions, and `degraded=false`; teardown removed the
policy cgroup with session `oom=0` and `oom_kill=0`. The sampled maximum PSS
was 106,783 KiB for Settings and 79,522 KiB for DeskClock (RSS 272,044 and
238,736 KiB respectively); system_server peaked at 301,360 KiB PSS and
SurfaceFlinger at 61,955 KiB. These process PSS figures do not account for
DMA-BUF allocations not charged to those processes.

The evidence supports real global host swap/reclaim pressure in the original
failure, and does not support relaxing LMKD thresholds or OOM protection. It
does not establish whether AaaS allocations or another host workload consumed
the swap. The follow-up did not establish a Composer/ImageReader/SwiftShader
allocation leak: exact per-DMA-BUF memory accounting and a contemporaneous
failed-run cgroup snapshot are absent. The persistent AaaS parent cgroup has
cumulative OOM counters without a pre-run baseline, so they are not attributed
to these runs; the enhanced session's own policy cgroup recorded zero OOMs and
was removed. No LMKD policy change was made. Full interactive two-window input,
concurrent resize, close/reopen, and the separate historical SwiftShader JIT
crash remain open. Overall M1E remains **PARTIAL**. Structured measurements and
raw-log hashes: [`two_app_memory_comparison_20261030.json`](../results/m1e/live/two_app_memory_comparison_20261030.json).

### App-mode presentation policy and bounded resource snapshots (2026-10-30)

For `--experimental-virtual-display` sessions with an application selected, the
launcher now skips creating the primary diagnostic Wayland presenter by
default. `--show-primary-diagnostic` opts back into the previous diagnostic
window. This does not change Android display 0, SurfaceFlinger, SystemUI, or
framework startup. A live default two-app run reached `RUNNING`; startup output
reported the suppressed presenter, both secondary presenters handled frames,
and the session IPC directory exposed the two `wayland-vdisplay` endpoints
without a primary `wayland.sock`. A real desktop screenshot shows DeskClock
content rather than the Android launcher/primary desktop; it is a single
foreground window capture, not new side-by-side evidence:
[`app_mode_primary_suppressed_20261030.png`](../results/m1e/live/app_mode_primary_suppressed_20261030.png).
The `--show-primary-diagnostic` escape hatch was also exercised live in a
single-app session: both `wayland.sock` and `wayland-vdisplay.sock` were
created with their presenters, then the session reached STOPPED on Ctrl+C.

The opt-in `--resource-diagnostics` flag records mode-0600 startup,
shutdown-begin, and post-cleanup JSON snapshots. An optional
`--resource-sample-interval N` records bounded periodic JSONL samples (maximum
3600) while the session is RUNNING. Snapshots read host MemAvailable/SwapFree,
memory/IO/CPU PSI, cgroup limits/events/pressure, selected Android process
RSS/PSS and `oom_score_adj`, and external workspace free space. They do not
change memory policy or persist command lines or typed text. The collector
supports both `/proc/<pid>/cgroup` hierarchy paths and absolute cgroup paths;
its tests cover both forms.

The default diagnostic-LMKD two-app run `m1b84_session_jdaldf3f` reached
RUNNING and STOPPED, wrote three periodic samples, and both app tasks remained
alive at the shutdown boundary. Sampled host MemAvailable ranged from
5,057,820 to 5,088,460 KiB and SwapFree from 1,044,980 to 1,045,140 KiB;
Settings PSS was about 99 MiB and DeskClock PSS about 73–77 MiB. The later
enhanced run `m1b84_session_62xzkt6n` also reached RUNNING and STOPPED; its
session cgroup had `oom=0`, `oom_kill=0`, `high=0`, and `max=0`, then was
removed. At shutdown-begin, host MemAvailable was 5,169,880 KiB and SwapFree
was 1,043,804 KiB; Settings and DeskClock PSS were 106,177 and 74,087 KiB.
These are process-accounting snapshots, not total graphics memory; DMA-BUF
allocations may not be represented in process PSS. Both presenters completed
all submitted-buffer releases with zero outstanding buffers. Full structured
evidence and session paths are in
[`app_mode_resource_diagnostics_20261030.json`](../results/m1e/live/app_mode_resource_diagnostics_20261030.json).

### Concurrent virtual-display resize and per-display keyboard routing (2026-10-30)

In `m1b84_session_nltb51xu`, KWin quick-tiled Settings and DeskClock as separate
native toplevels. Both started at 720×1280, then their configure events caused
Android displays 2 and 3 to advance independently to resize generation 2 at
960×1156 / 240 dpi. The broker logged updated DisplayManager metrics for both;
WindowManager recorded task 8 on display 2 and task 9 on display 3 with
960×1156 bounds. Composer and both presenters received Android source buffers
at 960×1156 with 3840-byte stride. The genuine full-desktop screenshot
[`two_output_native_resize_20261030.png`](../results/m1e/live/two_output_native_resize_20261030.png)
shows both Android applications simultaneously.

Settings was then resized alone to 960×578. Android WindowManager changed
display-2/task-8 bounds, broker generation 3 was acknowledged, and its
presenter received a matching 960×578 source buffer. DeskClock remained on
display 3 at 960×1156 and generation 2; its presenter logged no new configure
or source-size transition. This verifies independent native resizing of one
output while the other remains at its prior dimensions. It does not cover
resizing both back to 720×1280, landscape, rapid bursts, or post-resize input
coordinate mapping. At shutdown Settings ended 215/215 imports/submissions/
releases and DeskClock 197/197, both with zero outstanding buffers.

A separate session `m1b84_session_u6innd8w` verified per-display keyboard
delivery at the transport boundary. A controlled `/dev/uinput` pointer click
opened Settings Search; synthetic h-i-i appeared visibly in the display-2
editor. After focus changed to DeskClock, synthetic Tab/Enter DOWN/UP events
were injected by the display-3 adapter only. The Settings adapter had logged
keyboard focus leave and no subsequent key injection. The DeskClock Activity
has no text editor and no visible application response to those keys was
established; this remains partial keyboard acceptance. The screenshots
[`two_app_keyboard_route_20261030.png`](../results/m1e/live/two_app_keyboard_route_20261030.png)
and the detailed packet/focus/frame evidence are in
[`two_output_resize_keyboard_20261030.json`](../results/m1e/live/two_output_resize_keyboard_20261030.json).

Both sessions reached `RUNNING` then `STOPPED`; the state journal and sentinel
matched. The new concurrent-resize and keyboard-routing sessions did not
reproduce the historical SurfaceFlinger SwiftShader-JIT crash, but the old
unsymbolicated SIGSEGV remains unexplained and is not considered fixed.

I also ran a default-mode two-app smoke session `m1b84_session_eo2lkqum` for
about 60.6 seconds. Both apps stayed alive and presented concurrently; Ctrl+C
produced matching `STOPPED` journal/sentinel state. The presenters reported
146/146 and 125/125 imports/submissions/releases with zero outstanding buffers.
Periodic host snapshots showed MemAvailable down to 5,170,536 KiB, SwapFree
662,180 KiB, and memory PSI `some avg10` of 0.0. The shared AaaS parent cgroup's
OOM counters were already nonzero at the first snapshot and unchanged at the
last, so those cumulative counters are not attributed to this session. The
historical SwiftShader JIT fault did not recur. No resize was performed in
this smoke session. Details and external raw-log hashes are in
[`two_app_startup_shutdown_resource_probe_20261030.json`](../results/m1e/live/two_app_startup_shutdown_resource_probe_20261030.json).

An enhanced-mode run `m1b84_session_koo55mvl` also remained RUNNING for 66.2
seconds before Ctrl+C shutdown. The source-built LMKD logged 14 cached or
background process kills after swap fell below its configured watermark; the
Settings and DeskClock tasks remained alive in the collected interval. The
delegated session cgroup had zero OOM and OOM-kill events and was removed at
shutdown. Each presenter ended with all 401/401 and 378/378 imported,
submitted, released buffers and zero outstanding. This is bounded startup and
cleanup evidence only: no interaction or deliberate pressure injection was
performed. See
[`two_app_enhanced_lmkd_cgroup_smoke_20261030.json`](../results/m1e/live/two_app_enhanced_lmkd_cgroup_smoke_20261030.json).

### Continuation lifecycle audit (2026-10-30)

A further default two-app session reached `RUNNING`. Android assigned Settings
task 8/display 2 and DeskClock task 9/display 3. During the attempted keyboard
interaction, Settings had no focused window and InputDispatcher reported an
ANR; Android later removed task 8. DeskClock remained running until I stopped
the shared session. This is not a successful Settings interaction test or a
normal KWin-close acceptance result. Both display-specific adapters logged
validated key events and Binder `rc=0`, but this did not establish visible
application consumption on DeskClock.

Ctrl+C then completed shutdown with the state journal and status sentinel both
at `STOPPED`. Settings and DeskClock presenters reported respectively 352/352
and 334/334 imports/submissions/releases, zero outstanding buffers, and zero
teardown invalidations. This session is useful for shutdown accounting, not for
the missing input-isolation or reopen gates. Structured observations and raw
log hashes are in
[`continuation_runtime_audit_20261030.json`](../results/m1e/live/continuation_runtime_audit_20261030.json).

At the prior checkpoint, the launcher supported only its initial `--app` /
`--app2` pair. The dated follow-up below adds a coordinated session-local
two-slot control interface rather than an isolated broker create operation.

The focus-sync follow-up regression run passed 165 Python tests. The latest
dynamic lifecycle regression run passed 169 Python tests, M1A tests, the forced
presenter build/tests, input-adapter build, Composer tests, forced broker
build, and the workspace guard. The inherited untracked
`experiments/m1b/composer_aaas/build/` directory remains untouched and is not
part of source changes. Overall M1E remains **PARTIAL**.

### Wayland-to-Android focus synchronization follow-up (2026-10-30)

The previous ANR trace had a confirmed gap: a Wayland keyboard-focus enter
updated only the host adapter. Android's InputDispatcher continued to focus the
other display, so a key could be injected while the Settings task had no
focused Android window.

The per-output adapter now sends a nonce- and focus-generation-tagged request
to the existing trusted-display broker before accepting keyboard focus. The
system-owned broker locates the task assigned to that broker-owned display and
calls Android 16 `ActivityTaskManager.setFocusedTask()`. It acknowledges only
a request matching that display's task. Repeated polling of the same request is
suppressed; no host-global input capture or arbitrary task/display target is
introduced.

In live session `m1b84_session_80wfe0wl`, repeated KWin activation produced
five matching transitions between Settings/display 2 and DeskClock/display 3.
For each transition, `dumpsys input` reported the corresponding
`FocusedDisplayId` and focused application window. Settings SearchActivity was
focused on display 2; DeskClock was the focused window on display 3. Both tasks
remained present. No Settings or InputDispatcher ANR was observed during this
session's bounded focus sequence. The session's screenshot shows both Android
windows at once, with a controlled nonsensitive `/dev/uinput` fixture visible
in the Settings search field and no software keyboard. While DeskClock owned
focus, its adapter received the synthetic key events and the Settings adapter
received none; Settings' displayed text remained unchanged. DeskClock has no
editable control on its tested Clock page, so visible application consumption
on that app is still not established.

The session ended with matching `STOPPED` state journal and sentinel. Settings
and DeskClock presenters reported 872/872 and 848/848 imports/submissions/
releases, zero outstanding buffers, and zero teardown invalidations. Evidence:
[`focus_sync_inputdispatcher_20261030.json`](../results/m1e/live/focus_sync_inputdispatcher_20261030.json),
[`two-window screenshot`](../results/m1e/live/focus_sync_two_windows_20261030.png),
and the filtered Android input/task snapshots beside them.

The same patched focus path was exercised in a separate enhanced
source-LMKD/cgroup two-app session: Settings → DeskClock → Settings produced
matching Android focused-display IDs 2 → 3 → 2. The session reached RUNNING,
stopped cleanly, removed its delegated cgroup, had no observed ANR, and both
presenters ended with zero outstanding buffers. This was focus/lifecycle smoke
coverage only; it did not repeat visible text entry. See
[`focus_sync_enhanced_lmkd_20261030.json`](../results/m1e/live/focus_sync_enhanced_lmkd_20261030.json).

This resolves the reproduced host-focus/Android-display-focus mismatch for
the tested tasks, but it does not close M1E. Two-way application-consumed
keyboard input, independent scrolling, app close/reopen without Android restart,
and other lifecycle gates remain open. The earlier ANR run remains recorded as
a failed experiment, not an accepted close event.

### Enhanced-mode two-app keyboard follow-up (2026-10-31)

A separate `--use-source-lmkd --memory-policy=cgroup` session showed visible
synthetic typing in Settings Search and Contacts' First name field. The first
attempt produced `lpha`, so its first key was missed during the focus-entry
transition. After explicitly clearing/refocusing the editor, the visible text
was `alpha`; Contacts showed `beta`. The cause of the first-key miss is not
isolated. Both apps stayed RUNNING during the test and then shut down cleanly.
Settings and Contacts presenters ended at 697/697 and 683/683
imports/submissions/releases, zero outstanding buffers, and zero invalidated
buffers. The state journal and sentinel matched at STOPPED, and the delegated
cgroup was removed. This was a short text-entry smoke only; enhanced-mode
scrolling, minimize, resize, and close/reopen were not repeated. Evidence:
[`enhanced_keyboard_interaction_20261031.json`](../results/m1e/live/enhanced_keyboard_interaction_20261031.json).

### InputDispatcher focus-readiness follow-up (2026-10-31)

The missed-first-key investigation found that the trusted broker's earlier focus
acknowledgement meant only that `ActivityTaskManager.setFocusedTask()` returned.
That return can precede publication of the app's focused input window to
InputDispatcher. The broker now waits for Android's `dumpsys input` focused
window list to contain a nonempty entry on the broker-owned display before it
acknowledges that focus generation. A bounded timeout produces an explicit
negative acknowledgement; the input adapter does not blindly replay key events.

The default-mode live session `m1b84_session_y5s8nhsj` showed Settings (task 8,
display 2) and Contacts (task 9, display 3) side by side. After switching focus,
one controlled synthetic first key appeared visibly as `a` in Settings Search.
The broker logged per-display focused-window matches before the adapter logged
`android_display_focus_ready`. Both presenters ended with imports equal to
submissions and releases (698/698 for Settings, 690/690 for Contacts), zero
outstanding buffers, and zero teardown invalidations. The state journal and
status sentinel both reached `STOPPED`. The screenshot is
[`focus_readiness_first_key_20261031.png`](../results/m1e/live/focus_readiness_first_key_20261031.png); structured evidence and external log hashes are in
[`focus_readiness_followup_20261031.json`](../results/m1e/live/focus_readiness_followup_20261031.json).

This is bounded evidence for one first character in Settings, not a complete
reliability result. Contacts did not visibly consume text in this session, and
transient InputDispatcher “focused display does not have a focused window”
warnings remain (no ANR signature was found in this session's log). The broker
currently obtains the readiness snapshot by launching the fixed Android
`/system/bin/dumpsys input` command and parses its per-display focused-window
section; this is a diagnostic interface, so the focus matrix must be repeated
and the query contract kept under review. Modifiers, repeated first-key trials,
post-resize input, scroll variants, and minimize/restore were not covered by
this session. M1E remains **PARTIAL**.

The same broker and adapter build also reached `RUNNING` in enhanced
source-LMKD/cgroup mode (session `m1b84_session_3195sxc9`). Both displays
received focus-ready acknowledgements; shutdown reached `STOPPED`, removed the
session cgroup, and drained presenter buffers (135/135 and 124/124 releases).
This run did not switch focus or type into either app, so it is startup/cleanup
evidence only: [`focus_readiness_enhanced_smoke_20261031.json`](../results/m1e/live/focus_readiness_enhanced_smoke_20261031.json).

### Repeated two-window first-key acceptance (2026-10-31)

The focus-readiness path was exercised in two fresh Settings/Contacts sessions,
one using default diagnostic LMKD and one using source-LMKD with delegated
cgroup v2. A single persistent synthetic pointer and keyboard remained attached
through each trial; this avoids the earlier disposable-pointer harness, whose
device teardown itself caused host focus loss and invalidated those trials.

Each session alternated focus 20 times. Settings Search received markers
`a01`–`a10`; Contacts' First name field received `b01`–`b10`. The first
character was visible in every target field, the other field retained its
previous marker, and no duplicate or cross-window insertion was visible in the
captured sequence. This is 20/20 visible first-key transitions in default and
20/20 in enhanced mode. Synthetic `/dev/uinput` evidence only; physical
keyboard attribution is not claimed. The OCR helper confused some `0` glyphs
with `o`; the pass count comes from direct screenshot inspection, and OCR text
is retained as diagnostic metadata rather than used as the acceptance oracle.
See the genuine screenshot contact sheets
[`default`](../results/m1e/live/repeated_focus_fields_default_20261031.png) and
[`enhanced`](../results/m1e/live/repeated_focus_fields_enhanced_20261031.png),
final simultaneous captures
[`default`](../results/m1e/live/repeated_first_key_focus_20261031.png) and
[`enhanced`](../results/m1e/live/repeated_first_key_focus_enhanced_20261031.png),
and structured per-transition results in
[`repeated_focus_typing_20261031.json`](../results/m1e/live/repeated_focus_typing_20261031.json).

The broker observed InputDispatcher focused-window matches on the requested
display before readiness acknowledgements. The observed snapshot-readiness
query duration was 224–236 ms in the default run and 226–249 ms in enhanced
mode. Logcat still contains 40 default and 26 enhanced warnings stating that a
focused display temporarily had no focused window. Neither bounded log has an
ANR signature, and no visible marker was lost. These are classified as
recoverable focus-publication/transition warnings for this tested sequence, not
suppressed; the logs do not correlate every warning individually to a broker
request, so the broader warning behavior remains a limitation. Both sessions
ended with journal and sentinel `STOPPED`. Default presenters drained 1566 and
1560 buffers; enhanced presenters drained 593 and 573. Every import was
released, with zero outstanding buffers and zero teardown invalidations. The
enhanced delegated cgroup was removed.

The test covered Ctrl+A replacement and ordinary letters/digits. It did not
complete the Shift/Caps/Alt/navigation/repeat matrix, rapid adversarial focus
races, input immediately after resize/minimize/reopen, post-resize corner
coordinate checks, landscape/resize-burst testing, or horizontal/touchpad
scroll-source acceptance. The historical SwiftShader JIT SIGSEGV remains
unexplained. M1E therefore remains **PARTIAL** despite the repeated first-key
result. Both runtime logs and all individual screenshot hashes are recorded in
the structured result; raw session logs and full frame sequences remain under
the external workspace session directories.

The full regression set was rerun after these sessions: 171 Python tests,
M1A tests, forced presenter build/tests, forced input-adapter build, Composer
component tests, display-broker build, and workspace guard all passed.
