# M1E status

Status: **PASS / CLOSED for the supported two-output Wayland desktop contract; historical SwiftShader and untested compatibility paths remain documented residuals**

Date: 2026-11-01

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

### Corrected runtime SwiftShader default (2026-11-01)

The ordinary runner now selects the separate no-tracing SwiftShader candidate
that contains the odd-height paired-row bounds correction. It verifies the
source revision/diff hash, diagnostics-disabled setting, ELF Build ID, manifest
hash, and pinned binary hash before launch. The historical
`m1b83_sampling_lock_vulkan.so` remains byte-identical and separate.

A normal two-app run resized Settings through 960×578, 960×557, 960×565, then
back to 720×1280 while Contacts remained at 720×1280. Every generation reached
a matching Android source buffer. SurfaceFlinger and system_server survived;
both presenters balanced imports/submissions/releases with zero outstanding
buffers; the journal and sentinel reached STOPPED. In source-LMKD/cgroup mode,
Settings then crossed the 960×557 odd-height path and returned to 720×1280,
accepted visible post-resize text editing, and survived three guest minute
boundaries without the AlarmManager failure. The cgroup was removed at clean
shutdown. Records: [`default_runtime_corrected_swiftshader_resize_20261101.json`](../results/m1e/live/default_runtime_corrected_swiftshader_resize_20261101.json)
and [`enhanced_runtime_transition_resize_20261101.json`](../results/m1e/live/enhanced_runtime_transition_resize_20261101.json).

The old v4 stale AHardwareBuffer access remains a separate unresolved
historical lifetime observation; this bounded candidate validation does not
retroactively identify or fix its owner.

### Activity-transition first key (2026-11-01)

The recorded Settings first-key loss occurs below the host focus handshake:
Android `ViewRootImpl.InputStage` drops focused non-Back input while its
`ViewRootImpl` is paused for an Activity transition. A WindowManager/InputDispatcher
focused-window acknowledgement therefore does not establish that the new
Activity's ViewRoot is ready to consume the key.

The runner now builds and selects a hash-checked, session-local framework
overlay from the pinned Android 16 `framework.jar`. For a non-primary display,
it retains at most one focused key event in the original paused ViewRoot. It
resumes that event once when transition pause clears, and only if the same root
is still attached and focused. A one-second Handler deadline or ViewRoot detach
finishes it unhandled. The event is not moved to another display or Activity.
The base framework JAR is not modified. The production SwiftShader overlay is
also unchanged.

In a normal two-app runner launch, Settings Search was focused during its
Activity open transition and synthetic `/dev/uinput` `KEY_A` was sent as soon
as the new `input_focus: Focus entering SearchActivity` log appeared. Android
logged retain and resume; a real screenshot showed one `a` in the Search field.
Closing and reopening Settings in the same Android runtime and repeating the
sequence produced the same visible result. Both presenters ended with
imports=submissions=releases, zero outstanding buffers, and the runtime ended
`STOPPED`. The detailed trace, overlay provenance, hashes, and limits are in
[`activity_transition_key_deferral_20261101.json`](../results/m1e/live/activity_transition_key_deferral_20261101.json).

This is bounded live verification, not the full Activity/key stress matrix.
The concurrent host-focus-loss cancellation path, Contacts Activity-transition
input, and repeated transition count remain untested. The change does not
depend on KWin APIs; KWin only arranged the local test windows.

| Capability | Result | Evidence limit |
|---|---|---|
| Two Android tasks, trusted displays, Composer outputs, Wayland toplevels | PASS, bounded live | IDs recorded in the session evidence; IDs are not constants. |
| Both windows simultaneously visible and independently placed | PASS, bounded live | KWin quick-tile arrangement and genuine screenshot; user-driven repositioning was not separately tested. |
| Per-window task/display close and reopen | PASS, bounded live | Two create-after-destroy cycles reused each slot while the other app remained RUNNING; final stop shut down the shared runtime. |
| Buffer/fence terminal ownership | PASS, bounded live | Both summaries show imports=submissions=releases, zero invalidated/outstanding. |
| Single-output Android framebuffer resize | PASS, bounded live | Stable resize, odd-height, landscape, and resize-back paths have bounded current-candidate evidence in default and enhanced modes. Matching native Android source buffers were observed. In-flight pointer events are held to active presented geometry; full pointer corner grid remains untested. |
| Concurrent two-output resize | PASS_BOUNDED_CURRENT_PATCH; historical v4 crash owner unresolved | Both outputs reached matching resized and restored frames in bounded paired runs. A v10 trace recorded renderer sync before release for 34 imported descriptor-referenced memories. The older v4 unmapped AHardwareBuffer read remains unresolved; see the dated v10 trace records and `swiftshader_coherent_resize_investigation_20261031.json`. |
| Keyboard on both outputs, vertical scrolling, focus isolation | PASS_BOUNDED steady-field isolation and Activity-transition first key; modifier/navigation matrix remains PARTIAL | Repeated first-key tests passed 40/40 steady-field focus transitions across default and enhanced modes. Immediate SearchActivity keys are retained/resumed in the same Android ViewRoot and visibly consumed in default and enhanced runs; older unfixed captures remain historical. Vertical scroll changed only the targeted app rectangle in both modes. See `repeated_focus_typing_20261031.json`, `activity_transition_key_deferral_20261101.json`, `enhanced_runtime_transition_resize_20261101.json`, and `scroll_routing_fix_20261031.json`. |
| Reopen app without restarting runtime | PASS, bounded live | Settings reopened as task 10/display 4 while Contacts remained active. The reopened app accepted visible text after focus readiness; a third launch returned `capacity_exhausted`. Enhanced-mode close/reopen and minimize/restore reached clean STOPPED with cgroup removal. |
| Minimize/unmap lifecycle | PASS, bounded user-visible restore; Android lifecycle sync NOT TESTED | KWin minimize/restore hid and restored Contacts while Settings remained visible; both runtime slots stayed RUNNING. No Android pause/resume synchronization is claimed because the presenter has no standard minimized-state signal. |
| Hide primary diagnostic presenter in normal app mode | PASS, bounded live | Experimental app sessions with selected apps skip the primary presenter; Android display 0 remains intact. `--show-primary-diagnostic` restores diagnostic presentation. This verifies no primary Wayland output, not removal of internal Android SystemUI. |
| Distinct DMA-BUF copy on real Mixed composition | NOT TESTED LIVE | GPU-only alias path and component-level stride/copy tests remain as previously documented. |
| SwiftShader JIT crash freedom | PARTIAL | The historical v4 read from an unmapped AHardwareBuffer address remains without VkImage/descriptor/submission/display-generation ownership. Later corrected-patch traces survived bounded resize sequences but do not retroactively resolve that fault. |
| Resize/JIT relationship | PARTIAL | Corrected-patch resize traces are bounded positive evidence; the historic v4 fault's ownership path remains unknown. |

## Verification

The final automated runs for this continuation passed:

- `python3 -m unittest discover -s tests -v`: **208 tests** in the 2026-11-01 continuation run.
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

### Reopen after prior resize regression (2026-10-31)

A new close/reopen trial exposed a slot-reuse defect. The closed Settings
presenter had left `vdisplay_resize_1` containing `2 960 1156`. On the next
launch, the broker created a fresh 720×1280 Android display, then consumed that
old request and resized the new display before KWin had sent a configure for
the new toplevel. Its presenter remained configured for 720×1280, rejected
every 960×1156 source frame, and never mapped a Wayland window. The failed
presenter summary recorded 0 imports/submissions and 30 format rejections.

The launcher now clears the per-slot resize request before starting a dynamic
presenter. A regression test asserts this ordering. In the follow-up live
session, Settings reopened as a mapped Wayland window with Android task 10 and
display 4 while Contacts task 9/display 3 remained running. The new display
stayed at its initial 720×1280 until host interaction; the stale 960×1156
request was absent. The screenshot
[`dynamic_reopen_stale_resize_fix_20261031.png`](../results/m1e/live/dynamic_reopen_stale_resize_fix_20261031.png)
shows the reopened Settings content. It was captured before retiling, so the
windows overlap; it is evidence of mapping/content, not simultaneous
accessibility. The complete failure/fix trace, external raw-log paths and
hashes are in
[`dynamic_reopen_stale_resize_fix_20261031.json`](../results/m1e/live/dynamic_reopen_stale_resize_fix_20261031.json).

Both presenters ended with imports=submissions=releases, zero outstanding
buffers, and zero teardown invalidations. The session journal and status
sentinel both reached `STOPPED`; no ANR signature appeared. Nine transient
InputDispatcher no-focused-window warnings occurred. Keyboard acceptance on
the reopened Settings window was inconclusive: a controlled `h-i-i` attempt
was visible as `ii`, and a subsequent key-only probe did not yield a verified
editor change. This is not counted as successful reopen input and leaves a
focus-entry issue for follow-up. Resize-back, landscape, burst, and
post-resize corner-input acceptance also remain open. Overall M1E remains
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

### Verified default-mode two-window editor isolation probe (2026-10-31)

A further default-LMKD session (`m1b84_session_6ilda528`) checked that the
test harness really changed KWin focus before attributing key results. The
delayed project pointer probe focused Contacts task 9/display 3, where
Ctrl+A followed by `beta` visibly replaced the First name value. Settings
Search on task 8/display 2 remained `z`. After the delayed pointer probe
focused Settings, `q` appended to its query; Ctrl+A followed by `alpha`
replaced it, while Contacts remained `beta`. The final real desktop capture
shows both app windows and both editor values in
[`two_app_input_isolation_default_20261031.png`](../results/m1e/live/two_app_input_isolation_default_20261031.png).
This establishes one visible input-isolation sample in each direction in
default mode. It is synthetic `/dev/uinput`, not physical-keyboard evidence,
and does not replace the prior 40/40 repeated first-key trials.

This session recorded nine InputDispatcher no-focused-window warnings and no
ANR signature. It did not individually correlate those warnings with each
focus request. Settings finished with 505/505 imports/submissions/releases;
Contacts finished with 488/488. Both had zero outstanding buffers and zero
teardown invalidations. The state journal and sentinel both reached
`STOPPED`; no runtime processes were left. The structured run record contains
the identities, hashes, and exact untested matrix:
[`desktop_input_probe_20261031.json`](../results/m1e/live/desktop_input_probe_20261031.json).

The same run also demonstrated why pointer-test setup must wait for uinput
device registration: an earlier temporary probe left Contacts as KWin's
active toplevel, so its typed text was not accepted as a Settings focus test.
Those exploratory events were excluded. The established delayed pointer
probe and KWin active-window check were used for the accepted interactions.
M1E remains **PARTIAL**: modifier/navigation behavior, post-resize input,
landscape and resize-burst interaction, horizontal/touchpad scrolling,
minimize/restore, dynamic lifecycle stress, and enhanced-mode interactive
coverage remain open.

### SwiftShader JIT bounded review update (2026-10-31)

The retained failure log for `m1b84_session_byh_9r3y` confirms SurfaceFlinger
pid 186 / tid 216 (`Thread<05>`) received SIGSEGV code `SEGV_ACCERR` at 65
seconds of process uptime. Logcat contains only one backtrace frame at PC
`0x12bf` in `/memfd:swiftshader_jit (deleted)` and notes `tombstone_13`; the
complete tombstone artifact and JIT code mapping were not retained. The
historical log SHA-256 is recorded in `acceptance.json`. The known SwiftShader
source checkout is revision `cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5`; the
M1B.8.3 sampling-lock overlay was `1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`
(build ID `48176d3bf7c52ad4a2e1c8445fac8d52b83864ba`). The failed session did
not retain the effective `AAAS_VULKAN_OVERLAY` environment value, so the
historical crash cannot be tied conclusively to that exact overlay. The
current workspace's default overlay file hashes to the original baseline
binary; this current file state is not proof of which binary the earlier
session loaded.

The new default and enhanced focus-typing sessions ran for approximately 496
and 107 seconds respectively with concurrent rendering and twenty alternating
text edits each. Neither log contains the historical JIT SIGSEGV signature.
These were not resize or close/reopen stress runs, so the crash remains
unresolved and no fix or crash-free claim is made.

### Default-mode editing-key acceptance follow-up (2026-10-31)

A further default-LMKD live session ran Settings and Contacts simultaneously
(task IDs 8/9, Android display IDs 2/3) and exercised ordinary Android text
widgets using controlled synthetic `/dev/uinput` keys. Visible captures verified
Home, End, Left/Right cursor movement, Backspace, Forward Delete, Tab focus
traversal, Shift+Left selection, Caps Lock text case, Ctrl+A replacement, and
Enter moving Contacts from First name to Last name. A Shift key was held through
a KWin focus transfer, released after the new Settings focus acknowledgement,
and the following `A` appeared lowercase; this shows no Shift effect at the new
target, but does not establish that a held modifier is automatically released
before an explicit key-up. The captures are
[`final_key_matrix_default_20261031.png`](../results/m1e/live/final_key_matrix_default_20261031.png),
[`final_key_caps_default_20261031.png`](../results/m1e/live/final_key_caps_default_20261031.png),
[`final_key_shift_selection_default_20261031.png`](../results/m1e/live/final_key_shift_selection_default_20261031.png),
[`final_key_enter_default_20261031.png`](../results/m1e/live/final_key_enter_default_20261031.png),
and
[`final_modifier_focus_switch_default_20261031.png`](../results/m1e/live/final_modifier_focus_switch_default_20261031.png).
The key-by-key observations and artifact hashes are in
[`final_key_matrix_default_20261031.json`](../results/m1e/live/final_key_matrix_default_20261031.json).

This was a default-mode synthetic-input check only. Escape/Back, Up/Down,
Ctrl/Alt shortcuts, repeat, and modifier cleanup on close/reopen remain
untested. Logcat contained nine no-focused-window warnings and no ANR
signature; the warnings were counted but not correlated individually with the
focus requests. Both apps were RUNNING immediately before shutdown and the
journal and status sentinel reached `STOPPED`. Contacts' presenter reported
653 imports/submissions/releases with zero outstanding and zero teardown
invalidations. Settings' producer disconnected, but its presenter log contained
no final summary, so this run does not establish its terminal buffer count.
Earlier accepted per-output clean-drain evidence remains separate.

A KWin scripting probe exposed geometry for observation but did not expose a
callable resize method for these xdg toplevels. The method call failed before
changing geometry; no resize, landscape, resize-back, or post-resize input
acceptance is claimed from this session. Horizontal/touchpad source coverage,
enhanced-mode modifier acceptance, combined lifecycle stress, and the bounded
SwiftShader resize/teardown investigation also remain open. M1E remains
**PARTIAL**.

### Enhanced-mode visible editor isolation follow-up (2026-10-31)

A bounded source-LMKD/cgroup session launched Settings task 8 on display 2 and
Contacts task 9 on display 3. Controlled synthetic input changed Contacts'
First name field to `kappaOMEGA` using Ctrl+A and Caps Lock, then switched to
Settings and changed its Search field to `sigma`. The simultaneous desktop
capture shows both values and the unchanged unfocused Contacts field after the
Settings edit in
[`final_enhanced_input_isolation_20261031.png`](../results/m1e/live/final_enhanced_input_isolation_20261031.png);
[`final_enhanced_caps_modifier_20261031.png`](../results/m1e/live/final_enhanced_caps_modifier_20261031.png)
shows the Contacts modifier result. The structured record is
[`final_enhanced_input_isolation_20261031.json`](../results/m1e/live/final_enhanced_input_isolation_20261031.json).

Both app slots remained RUNNING during interaction. The log recorded eight
InputDispatcher no-focused-window warnings and no ANR signature; warning-level
correlation is still incomplete. At shutdown, Settings had 348/348 and
Contacts 329/329 imports/submissions/releases, zero outstanding buffers, and
zero teardown invalidations. Journal and sentinel reached `STOPPED`, the
source LMKD policy summary reported 34 ticks, zero errors, and no degraded
state, and the delegated cgroup was removed. This is enhanced-mode visible
input and cleanup evidence for a subset of keyboard behavior only; no resize,
landscape, minimize, close/reopen, or capacity stress occurred in this run.
The key matrix and resize interaction gates remain open, so M1E remains
**PARTIAL**.

### Two-output landscape resize and reproduced JIT crash (2026-10-31)

A default-LMKD two-app run exercised genuine resizing through KWin quick-tile
and resize operations. Both outputs produced matching Android source buffers
at 960×578 (stride 3840); Settings reached that size while Contacts remained
at 960×1156, confirming independent resize. Contacts then resized to 960×578,
and both outputs subsequently produced matching 960×557 buffers. A later
simultaneous generation-5 request changed both to 960×565. The screenshot
[`two_output_landscape_resize_crash_20261031.png`](../results/m1e/live/two_output_landscape_resize_crash_20261031.png)
shows both app outputs side by side in landscape geometry; a host terminal
covers the lower desktop region. Dimensions and source strides are in
[`two_output_landscape_resize_crash_20261031.json`](../results/m1e/live/two_output_landscape_resize_crash_20261031.json).

Approximately 63 ms after the broker logged the generation-5 resize requests,
SurfaceFlinger PID 189/TID 219 crashed with SIGSEGV (`SEGV_MAPERR`). The only
backtrace frame is PC `0x12bf` in `/memfd:swiftshader_jit (deleted)`, matching
the historical failure signature. The exact causal relationship is not
proven: Android LMKD had reclaimed cached/background processes roughly 18
seconds earlier because guest swap was exhausted, while host resource
snapshots still showed 7.2–7.9 GiB MemAvailable and 3.85–3.93 GiB SwapFree.
Settings and Contacts were not among the observed LMKD kills. The crash's
tombstone/JIT mapping was not retained, so the generated code cannot be
symbolized from this run.

Both SurfaceFlinger clients disconnected and the runner ended in `FAILED`;
the broker shutdown handshake timed out. Settings' presenter reported
214/214 imports/submissions/releases with zero outstanding buffers, but the
Contacts presenter emitted no final summary. Its terminal ownership is
therefore unverified for this failed run. This is a reproduced graphics
stability failure during a simultaneous resize transition, not a successful
resize stress result. No speculative fix or JIT-disable workaround was
applied. Further crash stress should wait until better tombstone and JIT
mapping capture is available. M1E remains **PARTIAL**.

### Tombstone capture and controlled concurrent-resize reproduction (2026-10-31)

Before another resize attempt, a disposable child-process SIGSEGV verified the
Android `tombstoned`/debuggerd export path. The child tombstone was captured,
hashed, and stored in a session-private directory (0700; tombstone and manifest
files 0600); the session journal and sentinel both reached STOPPED. This test
did not crash SurfaceFlinger. See
[`swiftshader_crash_capture_20261031.json`](../results/m1e/live/swiftshader_crash_capture_20261031.json).

A subsequent bounded default-LMKD run reproduced the SurfaceFlinger failure
while both displays resized from 960×557 to 960×565. The KWin configure events
were 1,748 ns apart. Both first emitted stale 960×557 frames, then genuine
960×565 buffers at stride 3840. The clock domains were aligned by converting
presenter monotonic timestamps to UTC; the two stale-frame timestamps align
with the corresponding SurfaceFlinger `Unexpected onFrameCommitted in Gpu
state` logs within 1 ms. SurfaceFlinger crashed about 163 ms after the second
matching 960×565 frame. This is strong evidence for a concurrent-resize
association, not proof that resize is the underlying cause.

This run's complete available tombstone text and protobuf were preserved in the
external session directory. It records all available thread backtraces, 1,066
memory-map entries, JIT mapping boundaries/permissions, and bytes around RIP.
The crash is SIGSEGV/SEGV_MAPERR at JIT PC offset `0x12bf`, in
`Thread<05>`. The captured instruction decodes as a generated-code 8-byte load
from `rcx + rax`; the computed address is immediately beyond an `/i915`
mapping. Register arithmetic is consistent with reading a next row from a
960×565 image with 3840-byte stride. The tombstone cannot identify which
GraphicBuffer owns that mapping or which SwiftShader shader/pipeline generated
the code, so this is an out-of-mapping access clue, not a root-cause finding.
The exact higher-level defect remains unknown; no speculative graphics fix or
JIT-disable workaround was applied.

The crash run used Vulkan overlay SHA-256
`1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`
(Build ID `48176d3bf7c52ad4a2e1c8445fac8d52b83864ba`) with source base revision
`cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5` and the recorded dirty local
changes. Historical sessions did not preserve their exact runtime Vulkan
binary identity, so binary equivalence with those runs is unverified.

The original crash-run capture manifest said `timeout` because the 2-second
host wait expired; the watcher acknowledgement arrived 3.598 seconds after the
request. The crash tombstone was nevertheless among the 100 exported files.
The host wait is now a bounded 10 seconds. A post-change disposable-child run
returned `complete` and STOPPED cleanly. This verifies capture plumbing, not a
second SurfaceFlinger crash capture with the longer timeout.

Failure teardown remained bounded. Both presenters emitted terminal summaries
with imports=submissions=releases, zero outstanding buffers, and zero teardown
invalidations. The broker could not acknowledge display release after
SurfaceFlinger died; the runner retained FAILED, terminated the session-owned
process group, and no matching runtime, presenter, adapter, or SurfaceFlinger
process remained. This is failure-cleanup evidence, not successful Android
display release or a clean runtime stop. The host had about 6.3 GiB
MemAvailable and 3.7 GiB SwapFree at failure, so these snapshots do not support
host-wide memory exhaustion as the direct cause.

The full tombstone, resize timeline, buffer accounting, provenance hashes,
and failure-cleanup record are in
[`swiftshader_resize_reproduction_20261031.json`](../results/m1e/live/swiftshader_resize_reproduction_20261031.json).
The failure is reproducible enough to block M1E closure, but the exact JIT
shader/resource lifetime cause is not yet isolated. No further aggressive
resize stress was run after this informative crash.

The first attempt to validate a narrower tombstone export filter failed before
Android framework startup because a single-quoted fixed grep expression broke
the generated shell's enclosing command. That session is retained as a failed
test, not counted as capture evidence. After changing that pattern to double
quotes, a second disposable-child test reached RUNNING, exported exactly the
matching text and protobuf tombstones (no unrelated tombstones), and reached
STOPPED in both the journal and sentinel. The export directory remained 0700
and the artifacts 0600. See
[`swiftshader_capture_filter_validation_20261031.json`](../results/m1e/live/swiftshader_capture_filter_validation_20261031.json).

After the filter change, the repository regression run passed 178 Python
tests. M1A, the forced presenter build/tests, the Android input-adapter build,
the Composer copy/transport component tests (compiled in `/tmp` to leave the
inherited untracked Composer build directory untouched), the broker build, and
the workspace guard also passed. No concurrent-resize stress was repeated
after the informative SurfaceFlinger crash.

### Host presenter XKB lifetime crash follow-up (2026-10-31)

Two host `wayland-host-pr` cores (PIDs 1611910 and 1635213) had the same
`SEGV_MAPERR` at `0x900000107`, in the installed libxkbcommon instruction at
offset `0x26c15`. Their full traces reached `aaas_android_meta_state()` from a
queued `wl_keyboard.enter` callback dispatched by `drain_wayland_buffers()`.
At the call site, the presenter's `xkb_state` storage contained glibc freed
chunk markers. Source ordering confirmed the lifetime error: `input_teardown()`
released XKB objects before the later Wayland drain dispatched pending input
callbacks. The evidence establishes a presenter use-after-free; it does not
indicate an internal libxkbcommon defect.

The presenter now destroys the keyboard proxy/listener before releasing XKB
state, keymap, and context, and clears those pointers after unref. A source
regression checks this ordering. The forced presenter build/tests and Python
suite (179 tests) pass. A bounded two-app live close test passed after the fix:
closing Settings left Contacts running, closing Contacts stopped the runtime,
and both presenters reported imports=submissions=releases with zero outstanding
buffers. This was normal close-path coverage; forced producer disconnect with a
queued enter callback was not repeated.

In the resize-correlated session, SurfaceFlinger crashed about 951 ms before
its producer disconnect, and the presenter crashed about 4.1 ms after that
disconnect. A second session showed the same presenter teardown crash after
producer disconnect without a SurfaceFlinger fatal event in the checked logs.
This supports a distinct presenter defect that could be exposed by a producer
disconnect; it does not resolve the separate SwiftShader JIT failure. The
complete core findings, hashes, and clock correlation are in
[`presenter_libxkbcommon_crash_analysis_20261031.json`](../results/m1e/live/presenter_libxkbcommon_crash_analysis_20261031.json).

The SurfaceFlinger `PC 0x12bf` fault in `/memfd:swiftshader_jit (deleted)`
remains unresolved. No shader/pipeline or graphics allocation identity has
been tied to the faulting instruction. No SwiftShader correction is claimed,
and M1E remains **PARTIAL**.

### Executable presenter lifetime regression and JIT access analysis

The presenter UAF regression now uses an in-process Wayland server/client with
real `wl_keyboard` and XKB objects. Its control run dispatches a queued enter
while state is live; its teardown run queues the same event, destroys the
keyboard proxy, releases XKB objects, then drains the queue and confirms the
callback is discarded. Both paths passed in a separate ASan/UBSan build, and
the full M1A test target passed from `/tmp`. This exercises the proxy/event
lifetime contract, but is not a forced KWin or Android producer-disconnect
reproduction. See
[`presenter_queued_keyboard_teardown_validation_20261031.json`](../results/m1e/live/presenter_queued_keyboard_teardown_validation_20261031.json).

A complete tombstone from `m1b84_session_wpoyddeu` decodes the SwiftShader JIT
instruction as `movq (%rcx,%rax,1),%xmm1`, an 8-byte read. Its effective
address is exactly the end-exclusive address of a writable `/i915` mapping.
`R8` is at offset `564 * 3840`, the start of the last row if this mapping is
the observed 960×565, 3840-byte-stride source buffer; `RCX` is 1280 bytes into
that row and `RAX` adds one stride. The computed address is therefore
consistent with a read at row 565, x=320, outside that candidate image. The
tombstone contains several same-sized `/i915` mappings and no DMA-BUF,
AHardwareBuffer, GraphicBuffer, Vulkan image, pipeline, or display-generation
identity. This arithmetic narrows the failure but does not prove which
allocation or shader was accessed, nor whether resize caused it. Reactor JIT
debug info was disabled in the Release build. No persistent source-checkout
change or SwiftShader correction is claimed. Full decoded evidence and exact
external artifact hashes are in
[`swiftshader_fault_instruction_analysis_20261031.json`](../results/m1e/live/swiftshader_fault_instruction_analysis_20261031.json).

The verified baseline overlay was built from SwiftShader revision
`cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5` with the existing sampling-cache
lock overlay SHA-256 `1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`.
The pre-existing dirty external source checkout is preserved. A temporary,
opt-in Subzero instrumentation patch was built into a separate overlay. It
records bounded JIT entry names, executable address ranges, and retirement
events to a session-bound file. One single-app run captured 20 named entries;
one two-app run captured 21. Both reached `STOPPED` with exact presenter
release accounting. These were no-resize instrumentation checks, not crash
reproductions. The production overlay hash was unchanged. The diagnostic
stderr path was not captured by session logs, so the trace uses the bound IPC
directory. See
[`swiftshader_jit_routine_trace_20261031.json`](../results/m1e/live/swiftshader_jit_routine_trace_20261031.json)
and the reproducible patch at
[`swiftshader_subzero_jit_trace.patch`](../experiments/m1e/patches/swiftshader_subzero_jit_trace.patch).

A first AHardwareBuffer trace build did fail because the host C++ command
lacked Android platform declarations. A later manually compiled trace object
captured two AHardwareBuffer IDs during a separate diagnostic startup. Both
logged bases exactly matched `/i915` mapping starts; each mapping was 3,768,320
bytes, matching `stride 736 * 4 * height 1280`. This validates the pointer-to-
AHB mapping only for that diagnostic process. It does not identify an
allocation from the historical `0x12bf` fault.

That full diagnostic overlay then crashed SurfaceFlinger during startup, before
any resize, in `AHardwareBufferExternalMemory::exportAndroidHardwareBuffer`,
with `rbp=1` and a store through that invalid base. Its Build ID was a one-off
trace build assembled from selected objects while retaining other objects
built against modified external headers. The stack and Build ID distinguish
this instrumentation/ABI failure from the historical JIT fault. The failed
run and hashes are recorded in
[`swiftshader_ahb_trace_diagnostic_overlay_20261031.json`](../results/m1e/live/swiftshader_ahb_trace_diagnostic_overlay_20261031.json).
That overlay is not suitable for further runtime tests. The expected
sampling-lock overlay was reconstructed and its pinned SHA-256 and Build ID
were verified before restoring the runtime path.

No resize was attempted with the full diagnostic overlay. The routine-only
trace still does not identify the historical fault's data allocation or
resize generation. No SwiftShader fix is claimed; the concurrent-resize crash
remains unresolved and M1E remains **PARTIAL**.

### Coherent diagnostic overlay and resize crash correlation

The former mixed-object diagnostic overlay was replaced by an isolated build
from pinned SwiftShader revision `cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5`.
The complete diagnostic source diff is recorded in
[`swiftshader_coherent_diagnostic.patch`](../experiments/m1e/patches/swiftshader_coherent_diagnostic.patch).
The build compiles the full CMake/Ninja target graph and relinks the generated
objects and archives together with the Android HAL shim and Android runtime
libraries. Its manifest checks source and patch identity, Android compile
definitions, generated input hashes, exported HAL/ICD symbols, dependencies,
ELF Build ID, and the unchanged production overlay. A diagnostic-only runtime
selection option validates that manifest before use.

The resulting v4 overlay (SHA-256
`fd03e647af765fd6b4cc3fbe1f804b724cd6a3775ddfdd1dd128f65a957dc74a`, Build ID
`7aa561d1e5349441898f794382563403f22b5894`) passed bounded single-app and
two-app no-resize runs. In the two-app run, both presenters drained all
imports with zero outstanding buffers, and JIT/AHardwareBuffer diagnostics
were emitted by the same SurfaceFlinger process. This establishes diagnostic
overlay compatibility for those no-resize paths only.

The coherent overlay then reproduced a SurfaceFlinger crash during sequential
resizing, without a near-simultaneous resize request. In session
`m1b84_session_hqgkycni`, a bounded capture of generated PixelRoutine machine
code identified the faulting instruction as an 8-byte `movq` read at
`0x7f31c8ba5000`. The JIT entry was `PixelRoutine_00000042` (routine ID 20).
The same address was the base of AHardwareBuffer ID `3560527888403`, imported
as a 960×578 image with 3840-byte rows. SwiftShader's trace recorded
`AHardwareBuffer_unlock()`/release for that object about 32.5 ms before the
fault; the tombstone shows the referenced page absent, immediately after an
adjacent `/i915` mapping. This confirms a JIT read through an address whose
AHardwareBuffer mapping had been released in that process.

This is a significant memory-lifetime correlation, but it does not identify
the Vulkan image/view/descriptor, command submission, renderer job, Android
display, or resize generation that retained the address. The current evidence
also does not establish whether the caller destroyed memory before pending
work completed or whether SwiftShader failed to preserve the resource through
the relevant work. No graphics fix is claimed. Both coherent diagnostic
resize runs failed with SurfaceFlinger death; the session status remained
`FAILED`, while the presenters emitted complete zero-outstanding summaries.
The production overlay remains unchanged at SHA-256
`1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`.

Detailed build, trace, tombstone hashes, and limits are recorded in
[`swiftshader_coherent_resize_investigation_20261031.json`](../results/m1e/live/swiftshader_coherent_resize_investigation_20261031.json).
M1E remains **PARTIAL** until the resource owner and violated lifetime
contract are established and the resize failure is corrected and retested.


### SwiftShader object trace expansion and v5 runtime attempts (2026-10-31)

The coherent v5 diagnostic build adds process-local identities joining imported
AHardwareBuffers to `VkDeviceMemory`, image bindings, image views, sampled-image
descriptor sets, queue submissions, draw jobs, pipeline IDs, and generated
PixelRoutine addresses. Its one-app Settings smoke reached `RUNNING`, produced
123/123 imports/submissions/releases with zero outstanding buffers, and stopped
cleanly.

Two v5 two-app attempts exposed a separate Android framework failure:
`system_server` crashed in `AlarmManagerService.getAlarmOperationBundle()` at
`PendingIntent.isActivity()` on a null value. One attempt failed before the
runner accepted `RUNNING`; the other reached `RUNNING`, rendered 127 and 114
frames through the two presenters, then failed at guest time 15:32:00.002. Both
presenters reported complete releases and zero outstanding buffers. These are
FAILED runtime sessions, not successful acceptance runs, and no resize was
completed in either. The failure is distinct from the historical native
SurfaceFlinger SwiftShader SIGSEGV; no causal relationship is established.

The new trace observed no Vulkan semaphore-signal events in these runs; the
recorded draw submissions carried fence events and were followed by renderer
synchronization completion. This does not explain the stale AHardwareBuffer read
from the historical resize crash. The v5 trace has not yet captured a successful
resize-correlated crash or established a display-generation owner. See
[`swiftshader_v5_object_trace_20261031.json`](../results/m1e/live/swiftshader_v5_object_trace_20261031.json).

These failure sessions also exposed a host reporting bug: the runner searched
`commands.log` for a death marker as an arbitrary substring, and that log includes
the generated shell script itself. It could therefore mislabel a pre-readiness
Android failure as `surfaceflinger_died`. Classification now accepts only an
emitted standalone death record; focused regression tests cover both the false
positive and a real emitted marker. M1E remains **PARTIAL**.

### SwiftShader descriptor-use tracing and resize probe (2026-10-31)

The v6 coherent diagnostic patch assigns a fresh diagnostic ID when a
descriptor set is allocated, records its retirement when the pool frees or
resets it, and emits `AAAS_DESCRIPTOR_USE` while `PrepareForSampling` walks the
set. Each use includes submission, draw, set, view, image, device-memory, base
address, and extent identities. This avoids inferring a draw's inputs from an
earlier descriptor-write record or reusing an address-only set ID.

The v6 overlay passed a bounded two-app startup and one Settings resize from
720×1280 to 960×578 (Android display 2, broker generation 2); Contacts remained
720×1280. SwiftShader emitted same-process sampled-image records for resized
960×578 images. In this session, the last sampled uses of memory IDs 253 and
259 preceded their release by about 6.8 seconds, and no sampled use after
release was recorded. The release occurred during cleanup after an independent
`system_server` failure in `AlarmManagerService.getAlarmOperationBundle()`;
the run therefore ended **FAILED**, not as successful live acceptance. Both
presenters nevertheless reported complete release accounting (157/157 and
143/143; zero outstanding).

This trace does not reproduce the historical JIT stale read and still does
not attach an Android display ID directly to a SwiftShader object. It provides
a sound per-draw Vulkan image-to-memory link for the next bounded resize
capture. See
[`swiftshader_v6_descriptor_use_resize_20261031.json`](../results/m1e/live/swiftshader_v6_descriptor_use_resize_20261031.json).
The repeated system-server exception is recorded separately from the
SurfaceFlinger JIT failure. No graphics lifetime fix is claimed; M1E remains
**PARTIAL**.


### v7 target-to-draw trace and bounded resize run (2026-10-31)

The coherent v7 diagnostic patch adds `AAAS_DRAW_TARGET` records joining each
draw and pipeline to its color attachment's image view, image, device memory,
backing base, extent, row pitch, render area, and scissor. This complements the
v6 sampled-descriptor records and is built from the same pinned source/header
snapshot. The v7 overlay hash is `355f180a…`; its Build ID is
`758d776e…`. The production overlay hash remains unchanged.

A two-app session resized Settings through 960×578, 960×557, and 960×565
while Contacts remained at 720×1280. Android DisplayManager and presenter source
frames reached each requested Settings size. For the 960×565 draws the trace
identified target image 311 / memory 312 at 960×565, with a 3840-byte row
pitch and render/scissor bounds matching the framebuffer; it separately
identified a 960×557 sampled image. Both presenters drained all imports
(190/190 and 180/180) with zero outstanding buffers.

This session did **not** reproduce a SurfaceFlinger fault. It ended FAILED
after a separate `system_server` crash in
`AlarmManagerService.getAlarmOperationBundle()` at
`PendingIntent.isActivity()` on null. The runner preserved FAILED and the
SurfaceFlinger tombstone manifest truthfully reports no tombstone. Therefore
this is useful bounded trace coverage, not clean runtime acceptance and not a
SwiftShader fix. The historical fault's target/source relation remains
unresolved because that older run did not include target records. See
[`swiftshader_v7_target_trace_resize_20261031.json`](../results/m1e/live/swiftshader_v7_target_trace_resize_20261031.json).

### Odd-height SwiftShader paired-row bounds correction (2026-10-31)

A later diagnostic run captured the exact failure path in the earlier 557-pixel
height crash. `PixelRoutine_00000042` executed a paired-row read in
`PixelRoutine::writeColor()` at `y=556` on a 960×557 color attachment. Its
second-row address was one row (3840 bytes) beyond the 557-row image. The target
trace identified image 244, memory 245, and pipeline 186; this is a concrete
odd-height quad helper-lane bounds defect, separate from the older v4
AHardwareBuffer unlock/unmap observation. The prior v8 attempt had bounded
`readPixel()` and `alphaBlend()` but missed the independent read-modify-write
path in `writeColor()`.

The coherent diagnostic patch now carries the actual color attachment height
into `DrawData`, clamps the paired second-row read at an odd-height edge, and
masks helper-row lanes from writes. Diagnostic v9 (SHA-256
`3a5408010784f1a0823da132651a3071449573d284fd95ce8ef60b022c52173b`, Build ID
`3cffbc0378986480835d3b0511c0b61828c881e9`) completed two bounded live resize
runs without a SurfaceFlinger tombstone. The second run exercised Settings
720×1280 → 960×578 → 960×557 → 960×565 while Contacts remained 720×1280; Android
reported each requested size and the trace recorded draw targets at each size.
Both presenters fully released their buffers (158/158 and 149/149), with zero
outstanding or teardown-invalidated buffers, and the shared runtime reached
STOPPED. The production overlay remains unchanged at its preserved hash.

This validates a specific source-level bounds correction in the diagnostic
build, not universal SwiftShader stability and not the separate historical
AHardwareBuffer resource-owner hypothesis. M1E remains **PARTIAL**: the
production deployment path, enhanced-mode resize, resize-back/landscape/burst
matrix, and post-resize pointer acceptance remain open. Live resizing used the
available KWin session only to issue ordinary Wayland configure events; the
product implementation uses SwiftShader attachment extents and introduces no
KDE/KWin dependency or patch. See
[`swiftshader_odd_height_pair_bounds_20261031.json`](../results/m1e/live/swiftshader_odd_height_pair_bounds_20261031.json).

### Corrected SwiftShader candidate selected by the default runner (2026-11-01)

The runner now selects the separately built no-tracing candidate containing
the paired-row bounds correction. It verifies the candidate's source revision,
source-diff hash, diagnostics-disabled setting, ELF Build ID, manifest hash,
and pinned SHA-256 before launching Android. The historical
`m1b83_sampling_lock_vulkan.so` remains unchanged at its original hash; the
candidate is a distinct versioned artifact, not an overwrite.

A normal default two-app session completed Settings
720×1280 → 960×578 → 960×557 → 960×565 → 720×1280 while Contacts remained
720×1280. Each Android DisplayManager generation produced a matching source
buffer at its requested dimensions. SurfaceFlinger and system_server remained
alive; both presenters ended with imports=submissions=releases, zero
outstanding buffers, and the state journal and sentinel both reached STOPPED.
This validates the default deployment path for this bounded sequence. The
historical v4 stale AHardwareBuffer mapping access remains unresolved and is
not covered by the odd-height bounds fix. Full trace and artifact hashes are
in [`default_runtime_corrected_swiftshader_resize_20261101.json`](../results/m1e/live/default_runtime_corrected_swiftshader_resize_20261101.json).

### Enhanced-mode v9 smoke (2026-10-31)

A short two-app run using diagnostic v9 under source-built LMKD and delegated
cgroup policy reached `RUNNING`, rendered Settings and Contacts, then reached
`STOPPED`. Presenter summaries were 138/138/138 and 127/127/127 imports,
submissions, and releases respectively, with zero outstanding buffers; the
session cgroup was removed. No SurfaceFlinger crash occurred. This smoke did
not resize or exercise input, and therefore does not establish enhanced-mode
resize acceptance. The guest log also showed the existing Bluetooth service
restarting after `libbluetooth_jni.so` was unavailable; the target application
presenters remained active. See
[`swiftshader_v9_enhanced_smoke_20261031.json`](../results/m1e/live/swiftshader_v9_enhanced_smoke_20261031.json).

A subsequent enhanced resize attempt (`m1b84_session_1ky_uksb`) did not reach a
resize request: system_server terminated at guest time 16:48:00 with the
previously observed `AlarmManagerService.getAlarmOperationBundle()` null
`PendingIntent` exception. The session remains **FAILED**, so it is not an
enhanced resize pass. Both presenters emitted complete summaries (137/137/137
and 123/123/123 releases, zero outstanding), and cgroup cleanup succeeded. No
SurfaceFlinger SIGSEGV was observed. This known framework failure is separate
from SwiftShader and KWin; no causal connection is established. See
[`swiftshader_v9_enhanced_resize_blocked_20261031.json`](../results/m1e/live/swiftshader_v9_enhanced_resize_blocked_20261031.json).

A further bounded default-mode v9 run configured Settings to 960×557 while
Contacts remained at 720×1280. DisplayManager and SwiftShader draw-target trace
reported the new 960×557 extent, and the runtime reached `STOPPED`. The resized
presenter accounted for 149 imports/submissions/releases, rejected six stale
old-generation frames, and ended with zero outstanding or teardown-invalidated
buffers; Contacts accounted for 142/142/142. This is one more bounded odd-height
resize pass, not resize-back or input acceptance. The temporary KWin script was
only a test driver for ordinary Wayland configure events; the AaaS and SwiftShader
implementation has no KDE/KWin dependency. See
[`swiftshader_v9_557_resize_20261031.json`](../results/m1e/live/swiftshader_v9_557_resize_20261031.json).

Two intervening attempts are also recorded: one was interrupted by a stale-session
selection bug in the one-off test harness before readiness (all processes in that
specific runtime were subsequently removed; ownership is recorded unknown), and
another failed at the known guest minute-boundary `AlarmManagerService` null
`PendingIntent` exception. Neither is counted as resize acceptance. See
[`swiftshader_v9_failed_probe_attempts_20261031.json`](../results/m1e/live/swiftshader_v9_failed_probe_attempts_20261031.json).

### Odd-height resize-back (2026-10-31)

In session `m1b84_session_oc7xsro8`, the Settings output moved from 720×1280
to 960×557 and back to 720×1280 while Contacts remained at 720×1280. Android
DisplayManager logged both dimensions for display 2. The same SwiftShader color
target pipeline (ID 180) first emitted 960×557 draw targets and then 720×1280
targets; this distinguishes Settings' return from Contacts' unchanged portrait
frames. The Settings presenter ended at generation 3 with 131/131/131
imports/submissions/releases, 20 stale-generation rejects, zero outstanding,
and zero teardown invalidations. Contacts ended at generation 1 with
139/139/139, zero outstanding. The session reached `STOPPED`. This bounded
result does not test input after resize, repeated bursts, dual-output landscape,
or enhanced mode. Evidence:
[`swiftshader_resize_back_odd_height_20261031.json`](../results/m1e/live/swiftshader_resize_back_odd_height_20261031.json).

### Coherent no-tracing build and odd-height validation (2026-10-31)

The coherent SwiftShader source snapshot was rebuilt with Android support enabled
and diagnostic tracing disabled, using the same complete source/object/archive
graph as the tracing build. The no-tracing library is external to Git at
`/run/media/mrkus/Homework/aaas-workspace/tmp/m1e_swiftshader_fixed_notrace_vulkan.so`
(SHA-256 `386bd8cf7857adfb598212aafae73c82e9dfea2b0ea76f0a14aa45aae8a883cb`,
Build ID `b364161b9af0fd1841bb7b7045f77e2a7f5fb543`). The original production
overlay remains unchanged at SHA-256
`1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`.

A live two-app default-mode run reached `RUNNING`. Settings was resized through
720×1280 → 960×557 → 960×565 → 720×1280 while Contacts remained at 720×1280.
Android DisplayManager and the presenter observed matching native buffers for
each Settings generation, including 3840-byte odd-height strides. Settings
reconciled 176 imports/submissions/releases and Contacts 168/168/168, with zero
outstanding buffers and zero teardown invalidations. SurfaceFlinger survived
the resize sequence. The exact session and hashes are recorded in
[`swiftshader_fixed_notrace_resize_20261031.json`](../results/m1e/live/swiftshader_fixed_notrace_resize_20261031.json).

This was not a clean session acceptance: after resize-back, system_server
restarted at guest 17:21:00.001 UTC with the known null-PendingIntent
`AlarmManagerService.getAlarmOperationBundle()` exception. The runner retained
`FAILED`; no SurfaceFlinger crash was found in this run. The resize result is
bounded positive evidence for the SwiftShader odd-height correction, while
clean shutdown under this build and unrelated framework reliability remain
unverified. KWin scripting only generated ordinary Wayland configure events on
the available host. AaaS contains no KWin-specific product dependency.

### Enhanced no-tracing resize validation (2026-10-31)

The same corrected no-tracing SwiftShader build was exercised with source-built
LMKD and delegated cgroup v2. Settings rendered native 960×557 and 960×565
buffers, then returned to 720×1280; Contacts remained independently at
720×1280. Both presenters released all imported buffers (182/182 for Settings,
170/170 for Contacts), with zero outstanding and no teardown invalidations.
The session cgroup was removed. At guest 17:27:00.004 UTC, the known unrelated
AlarmManager null-PendingIntent exception crashed system_server, so the session
correctly remained `FAILED`, not `STOPPED`. See
[`swiftshader_fixed_notrace_resize_enhanced_20261031.json`](../results/m1e/live/swiftshader_fixed_notrace_resize_enhanced_20261031.json).
This is bounded resize-path evidence only; input, landscape, bursts, app reopen,
and clean terminal shutdown under this exact overlay remain unverified.

A separate short default-mode run with the corrected no-tracing build rendered
Settings and Contacts simultaneously and reached `STOPPED` after a user stop.
The two presenters drained 135/135 and 124/124 buffers with zero outstanding.
It was intentionally kept within one guest minute to avoid the observed periodic
system-server AlarmManager exception. The run did not resize or exercise input;
see [`swiftshader_fixed_notrace_default_shutdown_20261031.json`](../results/m1e/live/swiftshader_fixed_notrace_default_shutdown_20261031.json).

A short enhanced-mode two-app run with the same fixed no-tracing build also
reached `STOPPED` cleanly when stopped before the known minute-boundary
framework exception. Source-built LMKD remained active, the delegated session
cgroup was removed, and Settings/Contacts drained 131/131 and 116/116 buffers,
with zero outstanding. It did not exercise resize or input; see
[`swiftshader_fixed_notrace_enhanced_shutdown_20261031.json`](../results/m1e/live/swiftshader_fixed_notrace_enhanced_shutdown_20261031.json).

### Pre-fix reproduction and corrected odd-height path (2026-10-31)

A coherent trace build with the `f38251d` odd-height PixelRoutine correction
excluded reproduced the fault on the exact path `720×1280 → 960×578 →
960×557 → 960×565`. SurfaceFlinger attempted an 8-byte `movq` from the first
address of the guard mapping immediately after the live 960×557 render-target
mapping. Trace identities linked the access to AHardwareBuffer
`919123001401`, VkDeviceMemory 293, VkImage 292, view 296, pipeline 180,
submission 401, draw 1280, and `PixelRoutine_00000042`. The computed access was
row 557 of a 557-row attachment. This establishes an odd-height paired-row
bounds defect for this reproduced failure, rather than a use-after-free of
that target in this execution. The session is correctly recorded as `FAILED`;
both presenters nevertheless emitted complete zero-outstanding summaries.

The same sequence was then run with diagnostic v9, which includes the
`f38251d` correction. DisplayManager and SwiftShader draw targets reached
960×578, 960×557, and 960×565; SurfaceFlinger survived and the shared runtime
reached `STOPPED`. Settings released 177/177 buffers and Contacts 166/166,
with zero outstanding and zero teardown invalidations. This is bounded live
validation of the exact previously failing sequence, not universal stability
proof. Full trace, crash hashes, binary provenance, and limitations are in
[`swiftshader_odd_height_prefx_reproduction_20261031.json`](../results/m1e/live/swiftshader_odd_height_prefx_reproduction_20261031.json).

This result does **not** identify or resolve the separate older v4 observation
of a 960×578 AHardwareBuffer address released before a later JIT fault. That
resource-owner chain remains unresolved, so overall graphics stability and
M1E remain **PARTIAL**. KWin was only the available local compositor/test
driver for standard Wayland configure events; no KDE/KWin product integration
or patch is required by AaaS.

### Even-height resource-lifetime comparison (2026-10-31)

The corrected v9 trace build was also used for one 960×578 resize in default
and enhanced modes. In the enhanced session, same-process events linked the
960×578 AHardwareBuffer to VkDeviceMemory 245, VkImage 244, view 248, pipeline
180, and draw 1218. The draw completed and queue renderer synchronization
returned before the view/image were destroyed and the AHardwareBuffer was
unlocked/released. Both app presenters drained and the session cgroup was
removed. This demonstrates a healthy observed ordering for that execution;
it does not identify the retained owner in the historical v4 crash.

The default-mode run likewise rendered a matching 960×578 frame without a
SurfaceFlinger JIT fault and drained both presenters, but its log contains the
known guest-minute `AlarmManagerService` null-`PendingIntent` system_server
crash. The runner later reached `STOPPED` during explicit cleanup, so this run
is not counted as a healthy Android runtime pass. The enhanced trace, both
run classifications, and hashes are recorded in
[`swiftshader_even_height_lifetime_followup_20261031.json`](../results/m1e/live/swiftshader_even_height_lifetime_followup_20261031.json).

The old v4 crash remains unresolved: its allocation was released before the
fault, but that run lacks the image/view/descriptor/submission/job identifiers
needed to decide which component violated lifetime ordering. The healthy
comparison does not settle that question. M1E remains **PARTIAL**.

The final regression pass after this evidence update completed 198 Python tests,
M1A tests, forced presenter build/tests (including the queued keyboard teardown
regression), input-adapter and display-broker builds, Composer copy/transport
unit binaries built under `/tmp`, and the external workspace guard. The inherited
untracked Composer `build/` directory was not used, staged, or modified.

The same corrected diagnostic v9 sequence also passed once in enhanced mode:
Settings reached matching Android and JIT draw-target dimensions at 960×578,
960×557, and 960×565 while Contacts remained 720×1280. SurfaceFlinger stayed
alive; the session reached `STOPPED`; presenter ownership was fully drained;
and the source-LMKD session cgroup was removed with zero `oom_kill` events.
This strengthens bounded validation of the odd-height fix across both runtime
modes. It does not resolve the separate older v4 stale-AHardwareBuffer fault or
cover input, landscape, resize-back, burst, or dynamic lifecycle in enhanced
mode. See
[`swiftshader_v9_enhanced_odd_height_sequence_20261031.json`](../results/m1e/live/swiftshader_v9_enhanced_odd_height_sequence_20261031.json).

A closer enhanced-mode reproduction layout resized both Settings and Contacts to
960×578, then moved Settings through 960×557 and 960×565 while Contacts stayed
at 960×578. SurfaceFlinger survived, the run ended `STOPPED`, both presenters
released every imported host buffer, and the delegated cgroup was removed. The
v9 Vulkan trace recorded 18 imported 960-wide AHardwareBuffers; 13 had explicit
retirement before process exit. Eleven retired resources had draw uses, and all
eleven were destroyed/released after their last traced draw completion and
queue renderer synchronization. No release-before-sync ordering was observed.
Five imports remained live/unclassified at process exit, so this is not a claim
that every Vulkan allocation has a traced terminal event. The historical v4
fault did not recur and remains unexplained. Details and hashes are in
[`swiftshader_v9_enhanced_two_output_lifetime_20261031.json`](../results/m1e/live/swiftshader_v9_enhanced_two_output_lifetime_20261031.json).

Offline disassembly of the preserved v4 JIT code further narrows the old
960×578 stale-address fault. The exact load at `PixelRoutine_00000042+0x125f`
matches the pinned RGBA8 `PixelRoutine::writeColor` paired-row read from
`cBuffer`, the render-target color attachment. Its effective address is the
released AHardwareBuffer base. This identifies the faulting access role, but
not the VkImage/framebuffer/submission or which side violated the pending-work
lifetime. The missing v4 object/job identities still prevent a justified
lifetime fix. See
[`swiftshader_faulting_target_access_20261031.json`](../results/m1e/live/swiftshader_faulting_target_access_20261031.json).

A temporary queue-semaphore synchronization candidate was built coherently and
started both apps, but the trace recorded no queue semaphore signal events, so
the changed path was not exercised. That session later failed after the known
system_server AlarmManager null-PendingIntent exception; the broker release
errors followed framework death. The candidate patch was removed from the
source tree and did not alter the production overlay. See
[`swiftshader_queue_signal_candidate_20261031.json`](../results/m1e/live/swiftshader_queue_signal_candidate_20261031.json).

### SwiftShader-to-Composer resource identity on one resize (2026-11-01)

The coherent v10 trace build and a two-slot Composer log were used for one
Settings resize to 960×557 while Contacts remained active. Matching stable AaaS
allocator buffer ID `164` and DMA-BUF `st_dev/st_ino` joined the SurfaceFlinger
AHardwareBuffer import to Composer virtual display `102`, Composer slot 0, and
the 960×557 frame generation records. In that SurfaceFlinger process the same
memory ID `246` was bound to VkImage `245` and view `249`; its draw-target records
include pipelines `48`, `120`, and `179`. The traced 960×557 draw jobs completed
before the image and AHardwareBuffer were destroyed/unlocked. This provides a
direct resource-identity chain for this healthy resize observation, not for the
historical v4 crash.

The Android broker recorded logical display 2, resize generation 2. Composer
recorded destruction of its previous virtual output and creation of Composer
display 102 at 960×557. These are correlated by the ordered single-output resize
in the same session; the two layers do not yet share an explicit unique token.
The session later ended `FAILED` after the known AlarmManager null-PendingIntent
system_server exception and a broker shutdown timeout. Both presenters reported
all buffers released, with zero outstanding or teardown-invalidated buffers;
no SurfaceFlinger fault was observed. The resize result is therefore bounded
diagnostic evidence, not a healthy-session or stability pass. The v4 stale
960×578 target attachment lifetime remains unresolved. See
[`swiftshader_resource_identity_resize_20261101.json`](../results/m1e/live/swiftshader_resource_identity_resize_20261101.json).

The diagnostic build and Composer changes are compositor-neutral and introduce
no KDE/KWin product dependency. KWin was only used locally to emit standard
Wayland toplevel configure events.

The saved trace was replayed through the committed correlation tool: 42
AHardwareBuffer imports, 303 Composer frames, and 1,198 draw-target joins were
parsed. The replayed joined output is 3,888,985 bytes with SHA-256
`4a92c05328f98faf38b23c669ced2a591f3f4308ef1b9232fc541156c5e18feb`. Regression
verification passed: 202 Python tests, M1A tests, presenter build/tests, input
adapter build, broker build, Composer linear-copy and transport-pool tests, and
the external workspace guard. The Composer component tests were compiled into
`/tmp` to leave the inherited untracked Composer build directory untouched.

### v10 traced resize boundary follow-up (2026-11-01)

A second v10 diagnostic two-app session completed Settings display 2
resize generations 2–4 at 960×578, 960×557, and 960×565 while Contacts
remained on display 3. Android dimensions, Composer frames, and SwiftShader
AHardwareBuffer imports were correlated through stable allocator IDs and DMA-BUF
identity: buffer 167 / Composer display 102, buffer 174 / display 103, and
buffer 181 / display 104. For each traced color-target buffer in this sequence,
its recorded draw completions preceded the Vulkan AHardwareBuffer reference
release. SurfaceFlinger did not crash during the resize sequence.

The session did not complete normal shutdown: at guest time 18:45:00.005,
`system_server` hit the recurring AlarmManager null-PendingIntent exception,
and the session remained `FAILED` after broker shutdown timed out. Both
presenters reported 223 imports, 223 submissions, 223 releases, zero
outstanding, and zero teardown invalidations. No resize-back, concurrent
request, or post-resize input was performed. This bounded successful resize
sequence does not identify the older v4 use-after-unmap owner or validate clean
runtime acceptance. See
[`swiftshader_v10_resize_sequence_20261101.json`](../results/m1e/live/swiftshader_v10_resize_sequence_20261101.json).

### v10 resize-back follow-up (2026-11-01)

A third v10 diagnostic session took Settings through 960×578, 960×557,
960×565, then back to 720×1280 while Contacts remained at its original
720×1280. The returned Settings output joined to Composer display 100, buffer
144, and its 720×1280 AHardwareBuffer; Contacts remained on display 101 with
buffer 154. The three resized generations had matching stable allocator IDs
across SurfaceFlinger AHardwareBuffer imports and Composer frames, plus matching
DMA-BUF device/inode. All traced target draw completions preceded release for
the correlated target resources. SurfaceFlinger survived the full resize-back
sequence. The presenters later reported 253/253/253 and 241/241/241 imports,
submissions, and releases, with zero outstanding and zero teardown
invalidations.

The run still ended `FAILED`, not `STOPPED`: system_server hit the recurring
AlarmManager null-PendingIntent exception at guest time 18:48:00.001 and broker
shutdown timed out. There was no SurfaceFlinger SIGSEGV in this run, and it does
not resolve the historical v4 release-before-fault observation. Concurrent
resize, input after resize, and app lifecycle were not tested. See
[`swiftshader_v10_resizeback_sequence_20261101.json`](../results/m1e/live/swiftshader_v10_resizeback_sequence_20261101.json).

### AlarmManager handler fallback: listener alarm correction (2026-11-01)

The recurring system_server exception was traced to the rootless alarm-driver
fallback, not to a malformed PendingIntent. `timerfd_create(CLOCK_*_ALARM)` is
denied with `EPERM`; the resulting `ALARM_EVENT` handler drained due alarms and
unconditionally called `getAlarmOperationBundle()` and `PendingIntent.send()`.
Android alarms may instead be direct `IAlarmListener` alarms with a null
`operation`. The internal `TIME_TICK` listener is scheduled for each minute
boundary, matching the repeated failure timing. The exact Alarm object from the
historical crash was not logged, so attribution to that specific listener is
strongly indicated by timing and the source path, not directly captured.

The M1E services overlay now routes handler-fallback due alarms through the
framework's existing `deliverAlarmsLocked()` path while holding the expected
`mLock`, then reschedules the next alarm and refreshes alarm-clock state. This
preserves listener callbacks, completion tracking, PendingIntent behavior,
wake-lock/accounting semantics, and repeat scheduling. It does not modify the
stock services.jar or alarm policy. The source reference is the Android
framework's [`AlarmManagerService`](https://android.googlesource.com/platform/frameworks/base/+/a38d32bb09756370c5c28d210a051415e85e0be2/apex/jobscheduler/service/java/com/android/server/alarm/AlarmManagerService.java),
whose ordinary delivery path is listener-aware; the overlay is built from the
pinned local services diagnostic JAR using the pinned Apktool binary.

In session `m1b84_session_jglvfw9y`, both Settings (task 8/display 2) and
Contacts (task 9/display 3) stayed RUNNING from guest 19:00:50 through 19:04:32,
covering four minute-boundary alarm opportunities with one system_server PID
and no recurrence of the null-PendingIntent fatal exception. Normal stop reached
STOPPED. Presenter accounting was 162/162/162 and 153/153/153 imports,
submissions, and releases, with zero outstanding or teardown-invalidated
buffers. No direct TIME_TICK receiver trace was enabled. This is bounded
validation of the corrected M1E framework fallback, not proof of universal
AlarmManager correctness and not the complete resize/input acceptance matrix.
See [`alarm_fallback_two_app_tick_validation_20261101.json`](../results/m1e/live/alarm_fallback_two_app_tick_validation_20261101.json).

The independent historical SwiftShader v4 read-after-unmap observation remains
unresolved. The healthy v10 resource-order traces and this framework fix do not
retroactively establish its owner or cause. M1E remains **PARTIAL**.

### Clean resize validation after AlarmManager correction (2026-11-01)

After the M1E-only AlarmHandler fallback was corrected, three v10 traced
Settings/Contacts sessions completed with `STOPPED` rather than the earlier
minute-boundary `system_server` failure. In default mode, both outputs reached
960×578; Settings then moved independently through 960×557 and 960×565 while
Contacts remained at 960×578, then Contacts reached 960×565. Both returned to
720×1280. In enhanced source-LMKD/cgroup mode, both reached 960×578, Settings
reached 960×557 while Contacts stayed unchanged, and both returned to
720×1280; the delegated cgroup was removed. A third default run took both
outputs to 960×557, then issued the 960×565 configure updates from one local
compositor test call. The broker observed those requests 2 ms apart. Both
Android displays and Composer outputs reached 960×565, returned to 720×1280,
and the session stopped cleanly.

Across all three runs, SurfaceFlinger survived, the captured draw enqueue/work
start/completion counts balanced, and for the selected traced color-target
memory resources checked, draw completion preceded the matching Vulkan AHB
reference release. Both presenters ended with imports=submissions=releases,
zero outstanding buffers, and zero teardown invalidations. The historical v4
stale-AHB read remains unresolved: these bounded v10 sessions do not identify
the old reader or establish its ownership invariant. Landscape, configure
bursts, visible post-resize pointer-corner probes, and the full interaction and
lifecycle matrix remain open. The exact sessions, request times, Composer frame
identities, trace counters, binary provenance, and artifact hashes are in
[`swiftshader_clean_resize_after_alarm_fix_20261101.json`](../results/m1e/live/swiftshader_clean_resize_after_alarm_fix_20261101.json).

### Current-patch odd-height resize validation (2026-11-01)

The current coherent source patch was rebuilt with diagnostics disabled into a
separate no-tracing SwiftShader candidate. The build manifest records pinned
revision `cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5`, patch SHA-256
`49c1ce42f0cb09dd69a81645c9a3bec91a390c958ac3d49ff2bd3edf4df86ece`, overlay
SHA-256 `e42a0bd8dfe3e0eea6c3d6753f9f9fa254d348366847241ca3c7e4b9ac9affee`, and
Build ID `603ff4f389a1050a89743c1adef98c7a39dfefb4`. The preserved original
production overlay remains byte-identical at SHA-256
`1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`; the new
candidate was selected explicitly for these validation runs and is not called
the original production overlay.

In default session `m1b84_session_4kmgsc62` and enhanced
`m1b84_session_ono2a5yn`, Settings reached matching Android source frames for
960×578, 960×557, 960×565, and 720×1280 while Contacts remained at 720×1280.
Both SurfaceFlinger and system_server survived. Both runs reached STOPPED;
presenter import/submission/release counts balanced, outstanding buffers were
zero, and teardown invalidations were zero. The enhanced session cgroup was
removed.

One bounded paired-output run `m1b84_session_zl3l6zm5` then resized both
applications to 960×557, to 960×565, and back to 720×1280. The two configure
events were 8.84 microseconds apart for 960×557 and 19.02 microseconds apart
for 960×565; both outputs produced matching generation-specific Android
source frames at every stable size. SurfaceFlinger and system_server survived,
shutdown reached STOPPED, and both presenters drained with zero outstanding
buffers. This is one bounded successful paired trial, not proof of general
crash freedom. Detailed logs, metrics, build identity, and hashes are in
[`swiftshader_no_trace_current_patch_default_resize_20261101.json`](../results/m1e/live/swiftshader_no_trace_current_patch_default_resize_20261101.json),
[`swiftshader_no_trace_current_patch_enhanced_resize_20261101.json`](../results/m1e/live/swiftshader_no_trace_current_patch_enhanced_resize_20261101.json),
and
[`swiftshader_current_patch_near_simultaneous_resize_20261101.json`](../results/m1e/live/swiftshader_current_patch_near_simultaneous_resize_20261101.json).

These runs validate the odd-height correction in the explicitly selected
current-patch binary across default/enhanced modes and a bounded paired resize.
They do not identify the owner of the separate historical v4 stale
AHardwareBuffer access. The original production overlay was preserved rather
than overwritten. M1E remains **PARTIAL** while that historical graphics
observation and remaining input-transition/modifier acceptance gates remain
open. No KDE/KWin API or patch was added to the AaaS runtime; KWin remained only
the locally available test compositor used to generate standard Wayland
configure events.

### Two-way visible input after resize; Activity transition drop (2026-11-01)

In default session `m1b84_session_eeynp99l`, both Settings and Contacts reached
matching 960×578 Android source frames. Contacts visibly accepted `beta` in
Create new contact / First name. Settings Search visibly accepted `alpha`
while Contacts remained `beta`; Contacts then visibly accepted `gamma` while
Settings remained `alpha`. The interaction screenshots and raw session hashes
are referenced by
[`postresize_two_way_input_transition_20261101.json`](../results/m1e/live/postresize_two_way_input_transition_20261101.json).
Both presenters finished with balanced imports/submissions/releases, zero
outstanding buffers, and zero teardown invalidations; the session ended
STOPPED.

The same session also observed an Android transition edge. After the Settings
search UI was opened, `ViewRootImpl` logged a key-down dropped while
`SearchActivity` was paused for transition. InputDispatcher had a focused
window and the adapter's Binder call succeeded, but those facts do not prove
widget consumption. A later screenshot showed the complete `alpha` marker;
the interval was not measured as a bounded readiness delay. This remains
PARTIAL and is distinct from steady-window focus switching. No arbitrary delay
or blind key replay was added.

KWin was used only as the available local test compositor and to issue ordinary
Wayland window-geometry changes during live testing. The runtime has no KWin
patch, private KWin API, or KDE product dependency; its resize path remains
standard Wayland `xdg_toplevel` configure handling.

The regression pass accompanying these sessions completed 204 Python tests,
M1A protocol/synchronization/input tests, the forced presenter build and test
(including the executable queued-keyboard teardown cases), the input-adapter
build, the Composer linear-copy and transport-pool tests compiled directly to
`/tmp`, the forced display-broker build, and the workspace guard. The inherited
untracked `experiments/m1b/composer_aaas/build/` directory was not used or
staged. The structured resize record contains the exact commands and results.

### Production input transition and enhanced reopen follow-up (2026-11-01)

The production-overlay session `m1b84_session_ns31107y` confirmed visible
Contacts editing after a native 960×578 resize. Settings Search exposed a
narrower input boundary: immediately after tapping the Settings search entry,
the rapid `alpha` stream left `ha` visible. Android logged the A, L, and P
`ACTION_DOWN` events as dropped by `VRI[SearchActivity]` while that ViewRoot was
paused for an Activity transition. Adapter records show those key packets were
received and Binder injection returned success; the Android application log,
not that return code, establishes non-consumption. The host monotonic event
times and Android `KeyEvent.eventTime` values match within 0.1 ms. Once Search
was settled, a retry visibly produced the complete `alpha` marker. The focus
handshake reports an InputDispatcher focused window on the Android display; it
does not assert that a newly launched Activity's ViewRoot or editor is ready.
No blind replay or arbitrary delay was added. This is recorded as an Android
transition-time input drop, separate from the previously passing 40/40
steady-editor focus-switch matrix.

The enhanced source-LMKD/cgroup session `m1b84_session_ebztrs3p` visibly edited
Settings (`sigma`) and Contacts (`omega`) at 960×578. Settings was closed and
reopened in the same Android runtime as task 10/display 4, resized to 950×578,
and accepted more visible input (`zetatheta`). Contacts was also closed and
reopened as task 11/display 5. A third concurrent launch returned
`capacity_exhausted`. The final two-window shutdown reached `STOPPED`; the last
presenter summaries had imports=submissions=releases, zero outstanding
buffers, and zero teardown invalidations. The session-specific cgroup was
removed. Neither `system_server` AlarmManager null-PendingIntent failure nor a
SurfaceFlinger JIT fatal signature appeared in this bounded run.

These runs used KWin only as the available local compositor and geometry test
driver for standard Wayland configure events. No AaaS component depends on KDE,
KWin, or a compositor patch. Cropped, actual desktop captures and raw-log
hashes are referenced from
[`postresize_input_transition_and_enhanced_reopen_20261101.json`](../results/m1e/live/postresize_input_transition_and_enhanced_reopen_20261101.json).

This does not close M1E. Pointer corner mapping, landscape and configure-burst
acceptance, a full post-reopen Contacts editor probe, and the historical v4
SwiftShader stale-AHardwareBuffer ownership remain open. The observed Android
ViewRoot transition drop is also a documented behavior boundary; the existing
focus acknowledgement does not cover app-client transition pause state.

### Production post-resize pointer navigation (2026-11-01)

In default production-overlay session \`m1b84_session_vmb1g31u\`, Settings and
Contacts both reached Android display generation 2 at 960×578. Safe, visible
Settings controls were exercised around the top-right search row, center
settings rows, bottom Apps row, and top-left back control. Settings visibly
navigated to Search, Network & internet, Connected devices, and Apps. Contacts
First name visibly accepted \`beta\`. Per-display adapter records show the
expected local Android coordinates after removing each window's host origin
and 40-pixel content inset. The broker recorded both logical display metrics
at 960×578. This is application-visible pointer evidence, not only successful
MotionEvent injection.

Both presenter summaries ended with matching imports, submissions, and
releases, zero outstanding buffers, and zero teardown invalidations. The state
sentinel reached \`STOPPED\`. This run did not cover an in-flight resize race,
landscape, or configure bursts; Settings did not expose safe controls at every
absolute corner. Evidence and screenshot hashes are in
[postresize_pointer_navigation_20261101.json](../results/m1e/live/postresize_pointer_navigation_20261101.json).

### Mixed-orientation resize and resize-back (2026-11-01)

Default-mode session m1b84_session_rltgozc0 exercised independent output
changes in one shared Android runtime. Settings changed to 960×578 while
Contacts remained 720×1280; Settings then changed to 950×1100 while Contacts
remained 960×578. Contacts moved to 1000×650 while Settings stayed at
950×1100. The dimensions were then swapped (Settings 960×578, Contacts
950×1100), followed by both outputs returning to 720×1280. Android
DisplayManager metrics and each presenter's source_frame_dimensions events
matched the final source size for each generation, including row stride.
SurfaceFlinger and system_server survived, the terminal state was STOPPED,
and both presenter summaries had matching imports/submissions/releases and
zero outstanding or teardown-invalidated buffers.

The log also contains repeated com.android.bluetooth process crashes caused
by the image's missing libbluetooth_jni.so; these were not SurfaceFlinger or
system_server failures. No configure-burst or near-simultaneous resize was
included in this run. The historical v4 SwiftShader stale-AHardwareBuffer
observation remains unresolved. Full generation and hash data are in
[mixed_orientation_resize_back_20261101.json](../results/m1e/live/mixed_orientation_resize_back_20261101.json).

### Bounded configure burst and stale-frame recovery (2026-11-01)

Default production-overlay session m1b84_session_axspxtmq issued a bounded
rapid Settings geometry sequence (960×578, 950×1100, 960×557, 960×565) while
Contacts stayed at 720×1280. The compositor coalesced those writes before the
presenter observed them: only the final 960×565 configure reached Android.
Settings produced a matching native source buffer at 960×565 and was then
restored to 720×1280. A 960×565 buffer that arrived after the restore
configure was rejected as stale and release-acknowledged; the following
720×1280 source buffer matched. Contacts remained at its original size.

Both presenters ended with imports=submissions=releases, zero outstanding
buffers, zero teardown invalidations, and the session reached STOPPED.
SurfaceFlinger and system_server survived. This validates bounded configure
coalescing and stale-frame recovery, not rendering at every transient size.
The event trace and hashes are in
[configure_burst_coalescing_20261101.json](../results/m1e/live/configure_burst_coalescing_20261101.json).

### Enhanced-mode mixed resize and restore (2026-11-01)

The source-LMKD/cgroup session m1b84_session_cfecknv8 exchanged the
independent output geometries: Settings 950×1100 with Contacts 1000×650,
then Settings 1000×650 with Contacts 950×1100, followed by both returning to
720×1280. Android display metrics and presenter source buffers matched each
stable generation. Superseded-generation frames were rejected with release
acknowledgements. SurfaceFlinger and system_server remained alive; both
presenters ended with matching imports/submissions/releases, zero outstanding
buffers, and zero teardown invalidations. The state journal and sentinel
ended STOPPED, and the session-specific delegated cgroup was removed.

This was a bounded resize/ownership run, not a full input run. Evidence and
artifact hashes are in
[enhanced_mixed_orientation_20261101.json](../results/m1e/live/enhanced_mixed_orientation_20261101.json).
The historical v4 SwiftShader ownership question remains unresolved.


### Current continuation summary (2026-11-01)

The AlarmManager listener-alarm fallback correction remains in place. Recent
production-overlay default and enhanced sessions crossed guest minute
boundaries without the prior system_server null-PendingIntent failure. The
odd-height paired-row bounds correction remains separately evidenced in the
coherent diagnostic patch/build; the original production overlay hash is
preserved and must not be described as containing that diagnostic correction.
The independent historical v4 stale-AHardwareBuffer owner remains unresolved.

Additional bounded default and enhanced sessions verified mixed portrait /
landscape Android source buffers, resize-back to 720×1280, generation-aware
stale-frame release, and clean buffer drain. A default configure burst was
coalesced by the compositor to its final geometry and recovered cleanly. A
post-resize pointer run caused visible Settings navigation and Contacts text
editing. The app runtime path remains standard Wayland and contains no KDE or
KWin dependency; local KWin use was limited to test geometry changes.

The final regression run passed 204 Python tests, M1A, presenter (including
queued keyboard teardown), input adapter, Composer component tests run from an
isolated tracked-source archive, display broker, and the workspace guard. Raw
logs and their hashes are recorded in the external regression manifest; the
repository index is [regression_suite_20261101.json](../results/m1e/live/regression_suite_20261101.json).

M1E remains **PARTIAL**. Open acceptance includes the unresolved historical
v4 resource owner, complete modifier/navigation and scroll-source matrices,
input behavior during Android Activity transition pauses, and pointer mapping
during an in-flight resize. No universal crash-freedom claim is made.


### Enhanced held-modifier close and reopen (2026-11-01)

In source-LMKD/cgroup session `m1b84_session_aqcjppfg`, Settings and Contacts
were both running on displays 2 and 3. Settings had focus when synthetic Shift
was pressed. Closing Settings released display 2 while Shift was still held; the
presenter emitted Shift-up before focus leave and adapter shutdown. Only after
the slot reported CLOSED was the synthetic host Shift released. Reopening
Settings reused slot 1 on a new Android display (display 4, task 10) while
Contacts remained running on display 3/task 9. After the new focus-ready event,
the Settings Search field visibly contained lowercase `beta`, including a
lowercase first character. This is bounded evidence of modifier cleanup and
input after reopen, not the complete modifier matrix.

The app manager rejected a third concurrent launch with `capacity_exhausted`.
At final shutdown, both slots' presenter summaries had imports=submissions=
releases, zero outstanding buffers, and zero teardown invalidations; the session
ended STOPPED and the delegated cgroup was removed. Logcat also contains
repeated `com.android.bluetooth` process failures caused by the runtime image's
missing `libbluetooth_jni.so`; `system_server` and SurfaceFlinger remained alive.
The screenshots, event timestamps, and raw log hashes are in
[enhanced_modifier_close_reopen_20261101.json](../results/m1e/live/enhanced_modifier_close_reopen_20261101.json).

### Diagnostic v10 historical resize sequence (2026-11-01)

Default-mode session `m1b84_session_ey3820js` used the coherent v10 SwiftShader
diagnostic overlay (SHA-256 `7a3190fb690f8e231d41bd835a284fcf1e90a430e63386710ced813fde727c73`,
Build ID `78aa60b0eebcc475f8308e38e98dee5e7e6a0e91`) with Settings on
display 2/task 8 and Contacts on display 3/task 9. Settings traversed
720×1280 → 960×578 → 960×557 → 960×565 → 720×1280 while Contacts stayed at
720×1280. The presenter reported matching Android source frames for every
stable configure generation, including odd heights; stale previous-generation
frames were observed before the matching frame and rejected by the generation
path. SurfaceFlinger (guest PID 230) and system_server (guest PID 370) remained
alive through the run. The journal and sentinel reached STOPPED.

The same-process trace recorded 1,363 draw completions and 452 queue renderer
synchronizations. Descriptor bindings were applied in trace order and joined to
draws. For all 18 released imported memory IDs with descriptor-linked completed
draws, the last observed draw completion and submission renderer sync preceded
AHardwareBuffer release. Fifteen other referenced imports had no explicit
release event before process teardown and remain unclassified. This is bounded
diagnostic evidence, not proof of the historical v4 resource's owner or a
general crash-freedom result. Both presenters drained all 217/217/217 and
208/208/208 imported/submitted/released buffers with zero outstanding buffers
and zero teardown invalidations.

The production overlay remains unchanged at SHA-256
`1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`; this
session explicitly selected the diagnostic overlay. Logcat contains repeated
optional `com.android.bluetooth` process failures caused by the missing
`libbluetooth_jni.so`; neither target app, system_server, nor SurfaceFlinger
failed. The historical v4 stale-AHardwareBuffer read remains unresolved and
M1E remains **PARTIAL**. Structured details and hashes are in
[swiftshader_v10_resize_back_followup_20261101.json](../results/m1e/live/swiftshader_v10_resize_back_followup_20261101.json).

### Diagnostic v10 two-output resize correlation (2026-11-01)

A second bounded default-mode v10 run, `m1b84_session_30bampm8`, matched the
two-output historical setup more closely: both Settings and Contacts first
reached 960×578, Settings then reached 960×557, and both were requested at
960×565 12.39 ms apart before returning independently to 720×1280. Every
stable configure generation produced a matching Android source frame. The
same SurfaceFlinger process logged 1,507 completed draws, 485 queue renderer
synchronizations, and 55 AHardwareBuffer releases. The trace joined descriptor
bindings to 34 released memory IDs with completed draws; in all 34 cases the
last observed draw completion and submission renderer sync preceded release.
The remaining descriptor-referenced memory IDs without explicit release before
process teardown are unclassified. SurfaceFlinger and system_server survived,
both presenters drained 212/212/212 and 203/203/203 buffers with no outstanding
ownership, and the session reached STOPPED.

This is stronger bounded evidence for current draw/resource ordering and the
odd-height correction in the diagnostic overlay; it still did not reproduce
the separate v4 stale-address fault or identify its owner. The production
SwiftShader overlay remains unchanged. Details, monotonic request times, trace
and log hashes are in
[swiftshader_v10_two_output_resize_trace_20261101.json](../results/m1e/live/swiftshader_v10_two_output_resize_trace_20261101.json).
M1E remains **PARTIAL**.

### Reproducible v10 memory-retirement trace analysis (2026-11-01)

The trace analyzer now parses descriptor image bindings, draw enqueue/completion,
queue renderer synchronization, imported AHardwareBuffer memory IDs, and release
records. Four deterministic tests cover valid ordering, release-before-completion,
missing release, and parsing of release events. Reanalysis of session
`m1b84_session_30bampm8` produced 34 imported descriptor-referenced allocations
with observed draw-completion → renderer-sync → release order and 7 allocations
without an explicit release before process exit. This agrees with the prior
manual 34/7 summary. The analyzer reports trace order only; it does not establish
independent Vulkan happens-before or identify the allocation from the historical
v4 fault. See
[swiftshader_v10_lifetime_order_reanalysis_20261101.json](../results/m1e/live/swiftshader_v10_lifetime_order_reanalysis_20261101.json).

### Post-resize visible input on both outputs (2026-11-01)

Default-mode session `m1b84_session_h3cvpe8y` resized Settings and Contacts to
950×1100. Broker DisplayManager metrics and both generation-2 Android source
buffers matched that size (Settings frame 138, Contacts frame 125; both 3840-byte
stride). Following stable-generation pointer clicks, Settings Search visibly
changed from `alpha` to `gamma`; Contacts visibly accepted `beta`/`delta` in
First name and `qa` in Email. The final screenshot shows both application
surfaces and their independent editor values. Presenter ownership was balanced
(641/641/641 and 627/627/627) with zero outstanding buffers; the journal and
sentinel reached STOPPED. Input came from controlled `/dev/uinput`; physical
keyboard behavior is not inferred. KWin scripting set geometry only as a local
test driver; AaaS itself uses standard Wayland configure events and has no KWin
product dependency. The run does not establish corner mapping, in-flight-resize,
landscape, resize-burst, or enhanced-mode input coverage. Evidence and hashes:
[postresize_visible_input_20261101.json](../results/m1e/live/postresize_visible_input_20261101.json),
[screenshot](../results/m1e/live/postresize_visible_input_20261101.png).

### Enhanced asymmetric resize, reopen, and minimize/restore (2026-11-01)

Enhanced source-LMKD/cgroup session `m1b84_session_fyb0501r` kept Contacts at
720×1280 while Settings reached a matching 960×578 Android source frame. Settings
visibly accepted `omega`, was closed, then reopened in slot 1 as display 4/task
10 while Contacts remained display 3/task 9. The replacement output was resized
to 960×578 and visibly accepted `zeta` after focus readiness. With Settings
minimized, a click changed Contacts to its navigation drawer; restoring Settings
preserved `zeta`. The third app was rejected with `capacity_exhausted`. Across
the initial and reopened Settings presenter lifecycles and Contacts, imports,
submissions, and releases balanced with zero outstanding buffers. SurfaceFlinger
and system_server survived, the journal and sentinel reached STOPPED, and the
delegated cgroup was removed. The log recorded the non-protected
`UPDATE_CT_LOGS` broadcast warning during alarm delivery but no null
PendingIntent fatal or system_server death. Repeated Bluetooth process failures
from the missing `libbluetooth_jni.so` remain an unrelated image limitation.
Evidence:
[enhanced_asymmetric_reopen_minimize_20261101.json](../results/m1e/live/enhanced_asymmetric_reopen_minimize_20261101.json),
[screenshot](../results/m1e/live/enhanced_asymmetric_reopen_minimize_20261101.png).
KWin only drove local test geometry/minimize actions; product behavior stays on
standard Wayland protocols. Cross-compositor live testing remains untested.


### Consolidated acceptance and regression rerun (2026-11-01)

The latest tracked acceptance records now distinguish the bounded post-resize
visible pointer/editor probes from untested in-flight-resize coordinate mapping.
Default session `m1b84_session_h3cvpe8y` shows independent Settings and Contacts
editor changes after both Android displays reached 950×1100. Enhanced session
`m1b84_session_fyb0501r` covers asymmetric resize, visible input after close and
reopen, minimize/restore, two-slot capacity rejection, STOPPED shutdown, and
cgroup removal. These tests used KWin only as the locally available host window
geometry driver; the AaaS presenter uses standard Wayland protocols and has no
KDE/KWin product API dependency. Cross-compositor live testing remains
unavailable in this environment.

A fresh regression rerun passed 208 Python tests, M1A tests, forced presenter
build/tests, input-adapter build, Composer component tests, display-broker
build, and the external workspace guard. Per-command logs and SHA-256 values
are kept outside the repository; the structured summary is
[`regression_suite_continuation_20261101.json`](../results/m1e/live/regression_suite_continuation_20261101.json).
The historical v4 SwiftShader stale-AHardwareBuffer ownership remains open;
later healthy v10 ordering and corrected-patch resize results are not treated as
a root-cause fix. M1E remains **PARTIAL**.

### In-flight resize pointer mapping follow-up (2026-11-01)

A default-mode live session exposed a mismatch between pointer coordinates and
presentation: the presenter stretches the full source rectangle to the
configured Wayland viewport destination, while the previous input transform
used aspect-fit/letterbox math. `input_map.c` now uses the same per-axis stretch
as `wp_viewport_set_destination`. `gpu_presenter.c` also rejects mapping while
the active Android frame dimensions differ from the configured surface, and
records the stale-frame interval. This prevents events from being sent to the
new Android display using coordinates from an older displayed buffer.

In session `m1b84_session_ijzzq43q`, Settings changed from 950×1100 to 960×565
while Contacts stayed at 950×1100. During the mismatch the presenter recorded
`input_mapping_blocked_until_matching_frame` with the old 950×1100 frame. The
matching 960×565 Android source frame arrived later with a 3840-byte stride;
then the mapping-ready event was recorded. A subsequent click at surface
(400,64) mapped to Android (400,64), opened Search, and controlled typing
visibly produced `alpha`. The run ended STOPPED. Settings and Contacts each
reported imports=submissions=releases (1199 and 1195 respectively), zero
outstanding buffers, zero teardown invalidations, and zero input drops.
Structured details and hashes are in
[`pointer_mapping_inflight_resize_20261101.json`](../results/m1e/live/pointer_mapping_inflight_resize_20261101.json).

This is a bounded pointer correctness result, not a full corner/landscape/burst
matrix. The click itself occurred after the matching frame; the stale interval
was exercised by pointer enter/motion and mapping was blocked. The explicit
stale-click rejection log added afterward is covered by the rebuilt presenter
but was not itself observed in that live run. Activity-transition key loss
remains unresolved and M1E remains PARTIAL.

A further default-mode run (`m1b84_session_9x2l23oc`) used the ordinary runner
with the corrected SwiftShader candidate, waited for the newly emitted
SearchActivity focused-window event, then sent one synthetic `KEY_Q` pair.
Android logged retention at 22:31:57.277 and same-ViewRoot resume at
22:31:57.532; the screenshot visibly showed one `q`. Both presenters balanced
all 494/480 imports, submissions, and releases, with zero outstanding buffers,
and the session reached `STOPPED`. The attempted focus-loss cancellation setup
did not reach a second SearchActivity transition because its tap arrived before
Android focus readiness and was rejected (`rc=-3`); cancellation remains
untested. This session also logged optional `com.android.bluetooth` process
failures because the runtime image lacks `libbluetooth_jni.so`; SurfaceFlinger,
`system_server`, Settings, and Contacts stayed alive. See
[`activity_transition_latest_runtime_probe_20261101.json`](../results/m1e/live/activity_transition_latest_runtime_probe_20261101.json).

The latest full regression run passed 214 Python tests, M1A, a forced presenter
rebuild and test, input-adapter rebuild, Composer component tests, display-broker
rebuild, and the external workspace guard. The inherited Composer build
contents were not cleaned or rebuilt. Exact commands and workspace usage are in
[`regression_suite_final_20261101.json`](../results/m1e/live/regression_suite_final_20261101.json).

A corrected cancellation probe (`m1b84_session_7x8bm9kt`) then exercised the other transition branch. After Android focused Settings SearchActivity, a synthetic `KEY_W` was retained by its original ViewRoot. Host focus moved to Contacts; InputDispatcher entered Contacts, the Settings key-up was rejected with `rc=-3`, and the input adapter released the held key on focus leave. The original ViewRoot logged `finishing retained key without redelivery`; the screenshot showed an empty Search field and unchanged Contacts. The session ended `STOPPED`, with Settings 559/559/559 and Contacts 547/547/547 imports/submissions/releases and zero outstanding buffers. This is one bounded cancellation observation, not a repeated rate. See `results/m1e/live/activity_transition_cancel_20261101.json` and the external screenshot/hash referenced there.

A separate default-mode session (`m1b84_session_a2g0d4ue`) exercised the in-flight resize boundary and slot reuse. When Settings configured 960×565, the presenter rejected a click while its visible Android frame was still 760×1100. The matching generation-3 Android frame (960×565, stride 3840) arrived about 30.5 ms after configure; a subsequent click opened Search. Settings was then closed while Contacts remained RUNNING and reopened as task 10/display 4 with a fresh 720×1280 generation-1 source frame. A synthetic `KEY_Q` immediately after SearchActivity focus was visibly consumed. A third launch returned `capacity_exhausted`. The run ended STOPPED; both presenter summaries had imports=submissions=releases and zero outstanding buffers. Six optional Bluetooth process crashes due to absent `libbluetooth_jni.so` were observed; neither SurfaceFlinger, `system_server`, nor AlarmManager fatal signature appeared. Evidence: `results/m1e/live/inflight_resize_reopen_validation_20261101.json`.

### Enhanced two-app Activity input and resize-back validation (2026-11-01)

Enhanced source-LMKD/cgroup session `m1b84_session_x9jcwmdc` ran for about
6m55s and ended `STOPPED`. Settings used display 2/task 8 and Contacts display
3/task 9. Contacts' ordinary `ContactEditorActivity` visibly contained `beta`
in First name and `delta` in Last name; Backspace changed the latter to `delt`.
Settings Search independently showed `alpha`, then `gamma`, while Contacts
remained unchanged. The Settings output was resized through 960×578 and 960×565
and returned to 720×1280; the matching Android source generations had strides
3840 and 2944 bytes. Contacts remained 960×578. After resize-back, Settings
visibly showed `omega` while Contacts still showed `beta`/`delt`.

For an Activity transition, InputDispatcher logged SearchActivity focus at
23:04:27.815 guest time. The framework overlay logged a key retained 3ms later
and resumed in the same ViewRoot at 23:04:28.081; the resulting Search field
visibly contained `alpha`. This is bounded synthetic `/dev/uinput` evidence,
not physical-keyboard evidence. The cgroup was removed on shutdown. Settings
and Contacts presenters reported respectively 865/865/865 and 854/854/854
imports/submissions/releases, zero outstanding buffers, and no teardown
invalidations. SurfaceFlinger and system_server remained alive through normal
shutdown. No AlarmManager null-PendingIntent fatal occurred in this session.
The full trace hashes, overlay provenance, and screenshots are in
[`enhanced_activity_resize_text_acceptance_20261101.json`](../results/m1e/live/enhanced_activity_resize_text_acceptance_20261101.json).

This updates the earlier Activity-transition and resize results with one
additional enhanced run; it does not erase the old failures. The historical
v4 SwiftShader stale-AHardwareBuffer owner is still unidentified. The current
corrected odd-height candidate and bounded resize runs provide positive
current-build evidence, not proof that the old fault was fixed. Corner-grid
pointer probes and the full modifier/navigation matrix remain limited to the
existing records and have not been exhaustively repeated in this run. Keep
those limitations visible in the acceptance decision.

### Current-head regression verification (2026-11-01)

After the enhanced live session, `python3 -m unittest discover -s tests -v`
passed **214 tests**. M1A, forced presenter build/tests, forced input-adapter
build, Composer component tests, forced display-broker build, and the external
workspace guard also passed. The inherited Composer build directory remained
untracked and was not cleaned or rebuilt; the Composer target executed its
existing component-test binaries. See
[`regression_suite_current_head_20261101.json`](../results/m1e/live/regression_suite_current_head_20261101.json).

The accepted bounded input/resize behavior is stronger than the baseline but
does not retroactively identify the historical v4 SwiftShader stale mapping
owner. Retain that distinction in the milestone decision.

### Final bounded M1E interaction acceptance (2026-11-01)

A final default-mode session (`m1b84_session_hhuj2bsk`) exercised five fresh
Settings SearchActivity transitions. On each transition the test waited for the
Android focused-window event, then sent one distinct synthetic key. All five
keys (`q`, `w`, `e`, `r`, `t`) were retained and resumed in the same ViewRoot;
each cropped live screenshot shows its expected character, while Contacts
remained unchanged. This is **5/5 bounded application-visible first-key
results**, not physical keyboard evidence or a statistical reliability claim.
The same session visibly verified Escape/Android Back returning to the Settings
home screen and held-key repeat (`x` followed by repeated `a` characters).
Up/Down packets did not visibly change the Settings Search result view, so no
application-level Up/Down action is claimed for this fixture. Raw log, adapter
sequence IDs, per-transition screenshots and hashes are recorded in
[`activity_transition_key_matrix_repeat_20261101.json`](../results/m1e/live/activity_transition_key_matrix_repeat_20261101.json).

That session crossed an AlarmManager delivery interval without the prior
null-PendingIntent `system_server` fatal, ended with matching STOPPED state and
sentinel, and both presenters balanced every import/submission/release with
zero outstanding buffers. Optional Bluetooth process failures caused by the
image's missing `libbluetooth_jni.so` remained visible; SurfaceFlinger,
`system_server`, Settings and Contacts stayed alive. The enhanced
source-LMKD/cgroup interaction evidence is separately recorded in
[`enhanced_activity_resize_text_acceptance_20261101.json`](../results/m1e/live/enhanced_activity_resize_text_acceptance_20261101.json).

#### M1E closure decision

M1E is **CLOSED for the bounded supported two-output Wayland path**. Default
and enhanced sessions cover two independently usable app windows, Android
native resize and resize-back (including odd heights and a bounded paired
resize), visible per-app text and pointer input, first-key Activity transitions,
vertical-scroll isolation, minimize/restore, dynamic close/reopen, capacity-two
enforcement, and clean resource shutdown. The current-head regression record
shows 214 passing Python tests and the established M1A, presenter,
input-adapter, Composer, broker, and workspace checks passing.

Closure does not claim universal compatibility or universal crash freedom. The
historical v4 SwiftShader stale-AHardwareBuffer access remains an unresolved
incident: its exact Vulkan image/descriptor/submission owner was not recovered.
The later odd-height paired-row bounds correction is a separate confirmed fix,
and current corrected-candidate resize tests are bounded survival evidence,
not retroactive proof of that historical incident's cause. The preserved
production sampling-lock overlay remains unchanged.

Additional unverified compatibility limits are live testing on other
compositors, real distinct-DMA-BUF Mixed-composition copying, and hardware
specific horizontal/touchpad scroll sources. KWin was used only as the local
standard-Wayland test driver; AaaS has no KDE/KWin API or patch dependency.
No generic Android Activity pause/resume synchronization is claimed for host
minimize/restore.

### Native desktop-window integration completion (2026-11-01)

M1E was reopened to cover the user-facing window behavior that the earlier
two-output acceptance had omitted. The presenter now delegates its single
xdg-shell role and decoration lifecycle to libdecor. With the local KWin 6.7.5
compositor, compositor-owned title bars were visibly present. A separate run
forced libdecor's Cairo client-side plugin and visibly showed the title,
minimize, maximize/restore, and close controls. The product has no KDE/KWin API,
patch, scripting, or product dependency; KWin was the available live test
compositor. CSD hosts need libdecor plus a compatible installed plugin.

Real pointer interaction verified title-bar movement, right-edge resizing, and
a top-left corner resize. The corner probe changed the host configure from
720×1280 to 670×1280 and then 670×1230; Android first presented an older
670×1280 generation, which was identified as not matching the current
configure, then presented the matching 670×1230 source with 2688-byte stride.
The corner-test session stopped normally with 166 imports, submissions, and
releases and zero outstanding buffers. Maximize/restore, F11 fullscreen entry
and exit, minimize and desktop restore, visible close, and app-specific
close/reopen were also exercised. In one CSD fullscreen exit the compositor
restored 720×1304 rather than 720×1280; the presenter followed that configure
and the Android source matched. A separate maximize/restore returned to
720×1280.

The enhanced source-LMKD/cgroup session visibly verified Android Up/Down
navigation in the Settings list. Adapter records showed Linux KEY_DOWN (108)
translated to Android DPAD_DOWN (20), and KEY_UP (103) to DPAD_UP (19), with
ordered down/up events targeted to display 2 and focus generation 3; Contacts
did not receive the arrow events. The enhanced session ended STOPPED, both
presenters balanced their buffer ownership with zero outstanding buffers, and
the delegated session cgroup was removed. Default CSD and single-app corner
sessions also ended STOPPED with no outstanding presenter buffers.

The decoration screenshots, presenter/input log hashes, state transitions,
source dimensions, build identities, and test results are in
[`native_window_integration_20261101.json`](../results/m1e/live/native_window_integration_20261101.json).
The images are retained under `results/m1e/live/` with their SHA-256 hashes.
The presenter state regression and DPAD mapping regression passed with the
current automated suite (215 Python tests, M1A tests, and a forced presenter
build/test).

#### Updated M1E decision

M1E is **PASS / CLOSED for the supported two-output Wayland desktop contract**.
The accepted scope includes compositor-negotiated decorations where offered,
the libdecor CSD fallback, visible window controls, user-driven move/edge and
corner resize, maximize/restore, fullscreen, minimize/restore, app-specific
close/reopen, Android-backed geometry transitions, and visible DPAD navigation
in addition to the previously accepted two-app graphics, focus, resize,
pointer, scroll, lifecycle, and runtime-mode behavior.

This bounded acceptance does not claim universal compositor compatibility or
crash freedom. Other compositors were not available for live testing; the
historical v4 SwiftShader stale-AHardwareBuffer owner remains unknown; the
Mixed distinct-DMA-BUF path and hardware-specific touchpad sources remain
unverified. Minimize/restore correctness is user-visible, but no Android
Activity pause/resume synchronization is claimed. These are recorded as
residual limitations, not as resolved defects.

The inspected 2026-11-01 decoration, enhanced-input, and corner-resize
sessions each logged six optional `com.android.bluetooth` process restarts
because the base image lacks `libbluetooth_jni.so`. These are classified as a
known peripheral image limitation: the selected Settings/Contacts tasks,
SurfaceFlinger, and `system_server` remained alive. No Bluetooth workaround was
applied. Session logcat hashes are recorded in the native-window evidence.
