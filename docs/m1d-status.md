# M1D — Native keyboard input and Android text entry

Status: **PASS / CLOSED — keyboard, focus, and desktop IME acceptance met; advanced Unicode composition deferred**
Baseline: M1C.1 commit `3b2eb73`
Runtime: Android 16 x86_64, rootless container, KWin Wayland, portrait 720×1280


## Final acceptance: 2026-10-30 — PASS / CLOSED

The user manually confirmed that a physical Linux keyboard types into Android
text fields, focus returns after switching between Linux windows, Caps Lock and
Tab work, and mouse/touchpad interactions remain functional. This is recorded
as `USER_MANUAL_VERIFIED`; no hardware identifiers or logs were generated for
that manual test. The user pressed Ctrl and Alt but did not establish an
observable application action, so that portion remains bounded rather than
being claimed as fully user-verified.

A controlled live modifier probe supplemented that report. With the real
Settings Search editor focused, synthetic Ctrl+A visibly selected the complete
query. Android `dumpsys input` recorded Ctrl as `META_CTRL_ON` (`0x1000`) on the
Ctrl and A events. A separate Alt+A sequence reached Android with
`META_ALT_ON` (`0x2`); no app-level Alt shortcut or clipboard behavior is
claimed. XKB native regression tests now cover Tab translation and Ctrl, Alt,
combined Ctrl+Alt, and Caps Lock state transitions. The controlled screenshot
and session trace hashes are in
**`final_acceptance_followup.json`** (maintainer archive only);
**`ctrl_a_selection.png`** (maintainer archive only) shows the
Android editor selection.

The final direct default launch (`python3 scripts/run_aaas.py`) and enhanced
source-LMKD/cgroup launch both reached `RUNNING` and then `STOPPED` on Ctrl+C.
Both logs show normal user-0 `RUNNING_UNLOCKED` progression and Settings
startup. The enhanced run reported removal of its delegated cgroup. The
software-keyboard escape hatch continues to restore LatinIME. Desktop mode
continues to preserve the live `InputConnection`, suppress the IME surface and
Insets, and avoid IME-driven app resizing.

The Taskbar is a distinct SystemUI overlay at the bottom 126 pixels; it is not
an IME surface or an editor-focus reservation. A Settings result at Android
y=950 remained clickable while the IME was suppressed. The Taskbar's own
bottom region and content behind it were not tested. This did not prevent the
verified Settings search/control workflow; the overlay is separate from the
IME. No Taskbar hiding or SystemUI removal was made. Add an application-first
system-navigation policy to the future app-first runtime milestone.

M1D is **PASS / CLOSED** under the agreed acceptance boundary: basic physical
keyboard entry and focus restoration are user-confirmed; editing, navigation,
repeat, focus-loss isolation, Android IME suppression, and both runtime modes
have execution evidence. Ctrl is additionally verified by an Android-visible
selection action. Alt delivery is verified at Android meta-state, while any
specific application shortcut remains unclaimed. General Unicode, dead-key,
Compose, and IME text composition are not implemented by the current
KeyEvent-only adapter and remain a separately bounded text-input integration
item. The keyboard packet carries a Unicode scalar, but the adapter injects a
KeyEvent with null character payload; unsupported keysyms are not converted
into fabricated text.

Final verification: 132 Python tests passed; M1A, presenter build/tests,
input-adapter rebuild, and workspace checks passed. The enhanced cgroup smoke
reported clean removal, and process inspection found no AaaS runtime processes
left after shutdown. See **`acceptance.json`** (maintainer archive only) for
the gate-by-gate evidence classification.


## 2026-10-30 follow-up: desktop-native software keyboard policy

A focused search editor previously caused Android to show LatinIME because the
container injects Android `KeyEvent`s over Binder but does not enumerate a
hardware keyboard. Android reports `KEYBOARD_NOKEYS`; the stock
`InputMethodService.onEvaluateInputViewShown()` therefore selects a visible
soft keyboard even when `Settings.Secure.show_ime_with_hard_keyboard=0`.
Registering a host event node was not suitable: the node is not accessible to
the unprivileged session, and exposing it would bypass Wayland window focus.

The normal desktop launch is `python3 scripts/run_aaas.py`; it mounts a
checksum-guarded, read-only `framework.jar` overlay and sets a session-scoped
`Settings.Secure.aaas_desktop_mode` policy before launching Settings. The narrow Android 16 `InputMethodService` visibility-hook
adaptation returns false in desktop mode. The IME service remains bound to the
editor, preserving its `InputConnection`; Android does not show the soft-input
window. This is not a visual hide or off-screen surface workaround. The
`--software-keyboard` option disables desktop mode and restores stock LatinIME
behavior as an accessibility/mobile escape hatch.

The source patch applies exactly to the pinned Android 16 `frameworks/base`
revision `99b01a65cc4c104933788b3143285ab6bae65827`; source and generated
framework provenance, hashes, and reproducibility are recorded in
**`desktop_ime_build_receipt.json`** (maintainer archive only).
The original framework JAR remains unchanged. The runtime overlay hash is
`701d2fd4afe62e4b02a3f2da603daab492a4369dea3bd4d3baefe52789623a0b`.

In the live default desktop-mode session, Android focused the real Settings
Intelligence `SearchActivity`; `SearchAutoComplete` was served with an active
`EditableInputConnection`. LatinIME reported its decor/window/input view
hidden. WindowManager reported the IME window with no surface, off-screen and
not visible; IME Insets were not visible. The active InputDispatcher per-display
window list contained the full-screen SearchActivity and no InputMethod window.
The app bounds remained 720×1280, and the focused app window's touchable region
covered the display. The Android Taskbar remains a separate SystemUI window over
the bottom 126 pixels in this image; it is not an IME reservation. Controlled
synthetic `h`/`i` input appeared in the real field. A search result at Android
y=950 remained reachable; a separate
`--software-keyboard` run showed LatinIME with visible IME Insets and reduced
app bounds of 720×1154. Screenshots and the structured state record are linked
from **`desktop_ime_policy.json`** (maintainer archive only).

Desktop-mode regression checks also verified Backspace, Shift+A, Left/Delete,
Enter and Escape delivery; Escape returned to Settings. A 1.1-second synthetic
key hold produced visible repeat while the IME remained hidden. In a controlled
host focus switch to Xterm, AaaS received no new keyboard packets; a held Shift
release was observed before focus-leave. Binder injection timing for 19
synthetic events had a median of 1.916 ms and a maximum of 6.408 ms. These
figures cover Binder injection only, not the visible frame latency. Default and
source-LMKD/cgroup sessions reached RUNNING and shut down cleanly; the cgroup
was removed.

The final automated run passed 132 Python tests, M1A tests, presenter build and
tests, input-adapter rebuild, and the external-workspace guard. The measured
workspace remains within its 80 GiB ceiling and 20 GiB reserve. The real
physical keyboard was not independently tested: host event-node permissions
were left unchanged. Focus restoration after returning from another host
window, Caps Lock/Ctrl/Alt/Tab combinations, Unicode/dead-key composition, and
a full M1C physical pointer/touchpad regression during this final policy run,
and content interaction underneath the existing bottom Taskbar remain
unverified. At that checkpoint M1D remained **PARTIAL**. The later manual acceptance and
final closure section above supersedes that intermediate status.

## 2026-10-30 follow-up: user unlock and Settings text entry

The earlier user-0 lock and missing-editor findings below are historical and
are superseded by this follow-up. The cause was not a stalled init restorecon
worker: the diagnostic rootfs contained a 24-byte `/system/bin/vdc` shell stub
that returned success without doing the requested work. Android init's
`init_user0` built-in calls `/system/bin/vdc --wait cryptfs init_user0` (see
the pinned `core-android16/init/builtins.cpp`, `ExecVdcRebootOnFailure`). With
the stub, Vold never ran `fscrypt_init_user0`; the later CE storage setup and
user-unlock lifecycle were incomplete.

The foreground launcher now requires a checksum-matched copy of the original
Android 16 image's `vdc` executable and read-only binds it over the stub in
each private runtime. The rootfs and original image remain unchanged. The
overlay SHA-256 is
`b91c93e100f3892880665f9b47630d1170dc1fce4ee3cf249ec8f20e583fd764` and its
ELF build ID is `71dd3870bc9d13bc53126c430ae2ae90`. In the default live run,
Vold logged `fscrypt_init_user0`, preparation of the expected user data,
completion of restorecon for `/data/system_ce/0`, `/data/vendor_ce/0`, and
`/data/misc_ce/0`, and ActivityManager advanced user 0 through
`RUNNING_LOCKED` → `RUNNING_UNLOCKING` → `RUNNING_UNLOCKED`. No user-unlock or
boot-completed property was forced. The earlier empty restorecon completion
observation was a downstream symptom of the skipped `vdc` work.

With user 0 unlocked, clicking the Settings search control launched and
displayed `com.android.settings.intelligence/.search.SearchActivity`; Android
InputDispatcher logged focus entering its window. The real search editor showed
a caret and Android IME, and controlled Linux `/dev/uinput` keyboard events
visibly changed its text. Captures show typing, Shift+A, Backspace, Left then
Delete, Enter (the Android no-results screen), and Escape (return to Settings).
This demonstrates a functional Android editor/input connection through the
existing Wayland → XKB → keyboard-v2 → persistent Binder adapter path. The
captured diagnostics do not expose a direct InputConnection object snapshot,
and the keyboard source was synthetic uinput, not physical hardware.

The latest measured Binder injection duration was 20 events, median 0.807 ms,
maximum 1.800 ms. This excludes end-to-end display latency. Images and
session/log checksums are listed in
**`unlock_text_entry_followup.json`** (maintainer archive only).

Default and source-LMKD/cgroup foreground sessions both reached `RUNNING` and
stopped on Ctrl+C. The enhanced run removed its cgroup hierarchy with no
cleanup failures or OOM events. Shutdown now escalates only within the
session's dedicated process group after a bounded TERM wait, so namespace
init cannot remain orphaned. Cgroup cleanup retries only verified transient
process-placement read-back mismatches; other failures remain visible.

Verification after these changes: 125 Python tests, M1A tests, presenter
build/tests, Android input-adapter rebuild, and workspace budget check all
passed. The workspace was mounted from `$AAAS_WORKSPACE_DEVICE` as NTFS3 with 21.41 GB used,
below the 80 GiB ceiling and preserving the 20 GiB reserve.

At this intermediate checkpoint M1D remained **PARTIAL**; later user manual
acceptance and live focus/repeat evidence are recorded in the final closure
section above.

Implementation checkpoint: `c72c41a` (`feat(input): add Wayland keyboard transport and Android KeyEvents`).
The M1D status and evidence are recorded in a separate documentation commit.

## Scope and preserved architecture

This work extends the existing AaaS presenter, private input socket, and
persistent Android Binder input adapter. Pointer protocol v1 remains its
existing 68-byte message. Keyboard messages use a separately versioned fixed
72-byte packet and are sent only after the adapter advertises keyboard-v2
support in the v1 HELLO acknowledgement. No graphics, memory-policy, LMKD, or
launcher architecture was replaced.

## Implemented

- The presenter binds/unbinds `wl_keyboard` as `wl_seat` capabilities change.
- It accepts XKB-v1 keymaps using the host's `libxkbcommon`, validates/maps the
  supplied keymap FD, tracks XKB modifier state, and scopes keyboard focus to
  the AaaS Wayland surface.
- It maps common letters, digits, punctuation, editing/navigation keys, and
  modifiers to Android keycodes. Escape maps to Android Back. Wayland repeat
  information drives bounded host repeat events; focus loss clears repeat and
  sends releases for held keys.
- Keyboard focus/key packets carry session, display, sequence, timestamp, and
  focus-generation information. Pointer v1 semantics remain unchanged, and
  pointer and keyboard packets share sequence ordering when queued.
- The persistent Android adapter negotiates v2, validates keyboard packets,
  rejects unfocused/stale events, injects Android KeyEvents through the
  existing `IInputManager` Binder connection, and attempts release
  reconciliation on focus leave, shutdown, and disconnect.
- The KeyEvent parcel order was checked against Android 16 `KeyEvent` and
  `InputEvent` implementations in the pinned framework source. The adapter
  constructs the typed `InputEvent` parcel and reports Binder-level outcomes.

## Build and automated verification

The host presenter and keyboard-map tests build with `libxkbcommon`; the
Android-native adapter builds against the existing Android 16/Bionic source
and toolchain. The current diagnostic-instrumented artifacts (logging only; no input semantics changed) are:

| Component | SHA-256 | ELF build ID |
|---|---|---|
| Wayland presenter | `df0c3d53591061e88b35e48778a17b8bb5d4c3c9bbe6e6f1c9a5786df239a083` | `59bc5cdd8bfa3b1d4e563cf1da2fed4d1dc3ab04` |
| Android input adapter | `51be2c01219f1e2ff3224648eaeb8d90cdceddd3ca2ff8a7de066aac11ce83db` | `53e1adbb3dcd51270891d3df557e4965ada3924e` |

Verified commands:

```text
make -C experiments/m1a build/wayland-host-presenter test       PASS
make -C experiments/m1c/input_adapter -B all                    PASS
python3 -m unittest discover -s tests -v                         PASS (123 tests)
make -C experiments/m1a test                                    PASS
python3 scripts/android_workspace.py --workspace $AAAS_WORKSPACE check  PASS
```

Focused keyboard tests cover protocol version separation, packet validation,
XKB keymap/state loading, common key mapping, modifier state, Android parcel
field order, and adapter cleanup code paths. They do not prove live Android
text behavior.

## Live runtime evidence

The initial default and enhanced smoke sessions reached `RUNNING`, negotiated
`keyboard_v2`, and shut down cleanly, but **generated zero key packets**. That
was an absence of test input, not evidence of a failed Binder path.

A later controlled probe used a Linux `/dev/uinput` virtual keyboard (not a
physical-keyboard test). In session `m1b84_session_zoezwqyv`, a test `KEY_A`
down/up produced two `wl_keyboard.key` events, two XKB-translated events,
presenter packets 9/10, adapter validation for both packets, and successful
`IInputManager.injectInputEvent` replies (`rc=0`). Binder transaction elapsed
time was 1.240 ms for DOWN and 0.524 ms for UP. This proves event transport and
Binder acceptance only; it does not establish delivery to a focused editor.

In session `m1b84_session_ix6_tqny`, a synthetic five-character lowercase
fixture produced ten Wayland events and packets 14–23. The adapter validated
each and Binder returned `rc=0` for all ten. The test also submitted a
pointer click at Android display `(360, 178)` with a positive Binder result.
The after-capture still shows the Settings homepage's “Search Settings”
placeholder and no typed characters. The search editor's focus was not verified,
so this does not isolate a key-injection defect from a focus/tap problem. The
captured negative result is retained at
**`settings_after_synthetic_key_probe.png`** (maintainer archive only).

## Historical Settings editor focus investigation (before the vdc correction)

On 2026-10-30, a live portrait session reproduced the missing editor focus.
The Settings search control is visible in the 720×1280 Android frame; its
observed bounds are approximately `(43,85)-(677,273)`. A host click at global
Wayland `(960,178)` mapped to Android `(360,178)`. The presenter sent both
button transitions and the Android adapter injected them through Binder; the
release returned `rc=0`. No Settings Intelligence activity transition followed.
The screenshot remains the Settings homepage. An adjacent category click did
navigate to Network & internet, which confirms that the display coordinate
mapping and ordinary Settings click path work.

Android focus diagnostics after the search click report:

- WindowManager and InputDispatcher focus remain on
  `com.android.settings/.Settings`.
- InputMethodManager serves the root `homepage_container` view, not an editor.
- `mServedInputConnection` is null and `mInputShown` is false.
- ActivityTaskManager logs no search activity start after the pointer click.

The immediate boundary is Android user 0, not the keyboard packet path. A live
`dumpsys user` reports `RUNNING_LOCKED`. LockSettings successfully unwraps the
synthetic password for this unsecured user and starts CE-storage preparation.
`dumpsys mount` then lists CE-unlocked users as `[0]`, but the framework user
state does not advance. Vold logs `Starting restorecon of /data/system_ce/0`
and never logs its matching completion. The runtime property
`selinux.restorecon_recursive` remains empty. An additional supported
`am unlock-user 0` command prints `Success: user unlocked`, but after a further
bounded observation the user is still `RUNNING_LOCKED` and the property remains
empty. Thus the unresolved boundary is the init/Vold asynchronous restorecon
completion handoff during user-data preparation. The evidence does not yet
identify why init's worker fails to publish completion.

This path matches the Android 16 source contract: Vold clears and sets
`selinux.restorecon_recursive`, then waits for that property to equal the
requested path; init handles non-init requests on an asynchronous restorecon
worker and writes the completion value afterward ([Vold `Utils.cpp`](https://android.googlesource.com/platform/system/vold/+/refs/heads/android16-release/Utils.cpp), [init `property_service.cpp`](https://android.googlesource.com/platform/system/core/+/refs/heads/android16-release/init/property_service.cpp)). The host-side SELinux shim is mapped in Android init, but current evidence does not establish whether the worker is blocked in the restorecon call or whether completion publication fails.

While the user remains locked, the default activity query for
`android.settings.APP_SEARCH_SETTINGS` returns no activities. A query that
includes both direct-boot-aware and direct-boot-unaware components lists
`com.android.settings.intelligence/.search.SearchActivity`.

The pinned Android 16 Settings search provider installs the search-toolbar
click listener only after `queryIntentActivities()` returns a result; when the
query is empty it returns without adding the listener. This matches the inert
visible toolbar and explains why a successful pointer injection did not open
an editor ([AOSP `SearchFeatureProvider`](https://android.googlesource.com/platform/packages/apps/Settings/+/refs/heads/main/src/com/android/settings/search/SearchFeatureProvider.java)).
The search activity is declared exported in the installed SettingsIntelligence
APK, but the locked-user query and ActivityManager launch both fail in this
runtime. No KeyEvent construction change is justified until the editor can
actually be focused.

A diagnostic-only generated-runner experiment assigned Android system
ownership to `/data/system_ce/0`, `/data/misc_ce/0`, and `/data/misc_de/0`. It
removed the earlier serial-xattr `EACCES` warnings, but user 0 remained locked
and the search activity stayed unresolvable. A second, legitimate
`am unlock-user 0` request and a manual retry of the documented
`selinux.restorecon_recursive` request did not complete the handoff. These
diagnostic operations changed no boot property to claim unlock success. Neither
the ownership change nor a workaround has been applied to repository source.
The raw focus, user-state, and runtime logs remain on the external workspace;
paths and hashes are recorded in **`editor_focus_probe.json`** (maintainer archive only).

Screenshots show the unchanged search homepage after the click and a
successful adjacent category navigation:

- **`settings_search_click_no_transition.png`** (maintainer archive only)
- **`settings_category_click_control.png`** (maintainer archive only)

At the time of this diagnostic, no synthetic keyboard fixture was sent because
no editable Android view or InputConnection was focused. This blocker was later
resolved as documented above.

A subsequent default session contained three key-down and three key-up events
that reached Binder, although the test process did not create a keyboard uinput
device during that run. Wayland `wl_keyboard` does not identify the originating
Linux input device, so these events cannot be confidently attributed to a
physical keyboard. No screenshot tied to those events is available.

Diagnostics record event stage, sequence, state, Binder result, and elapsed
time, but do not log keycodes, Unicode, or typed text. For the ten-event
synthetic fixture, Binder transaction latency had a 0.639 ms median and 1.048
ms maximum. These are adapter Binder timings, not end-to-end Android frame or
visible-text latency. Raw traces and checksums are listed in
`results/m1d/key_delivery_probe.json`.

At that earlier checkpoint, the foreground runner was stopped with Ctrl+C
and reached `STOPPED`; the complete Python suite then passed 123 tests. The
enhanced source-LMKD/cgroup path had one transient cleanup warning at that
checkpoint. The later bounded retry and clean enhanced live rerun are recorded
in the 2026-10-30 follow-up above.

## Current evidence boundary and acceptance

The previous “Binder accepted the event but no editor was focused” boundary is
resolved for the controlled synthetic path: the actual Settings Intelligence
search activity was focused, Android displayed its IME, and the field's visible
text changed under key input. Binder success alone was not treated as proof;
the visible Android screenshots and ActivityTaskManager/InputDispatcher logs
are retained alongside the adapter trace.

The machine-readable gate results are in
**`acceptance.json`** (maintainer archive only). Text entry, editing,
Shift, Enter, Escape, repeat, and controlled focus-loss isolation are verified
with `/dev/uinput`; desktop IME suppression preserves the live editor and full
app bounds. Physical keyboard hardware, Caps Lock/Ctrl/Alt/Tab combinations,
focus restoration after returning to AaaS, and advanced text composition remain
unverified. At that checkpoint M1D remained **PARTIAL**; the later final acceptance above
records the user's physical keyboard and focus-restoration confirmation.

## Commits

- `c72c41a` — keyboard transport, XKB mapping, and persistent Android KeyEvent
  injection implementation with focused tests.
- `c1ddd3f` — initial M1D partial status.
- Live diagnostics and evidence updates are committed separately.
- `5f8591e` — restore Android user initialization with the original `vdc` and
  clean up its private process group.
- `a81e478` — retry transient cgroup process-placement cleanup races.
- `083ea4a` — suppress Android's soft keyboard in desktop mode while retaining
  the editor connection.
- `ace6607` — desktop IME runtime evidence and acceptance.
- `e755349` — cover Tab, Ctrl, Alt, combined modifiers, and Caps Lock states.
- Final user-confirmed keyboard acceptance is recorded in the current
  documentation/evidence commit.

## Reproducibility and security

`results/m1d/preservation_manifest.json` records the baseline Git state,
workspace identity, source revisions, and pre-change hashes. Build receipts,
runtime summaries, and test logs are recorded separately. The Android runtime
continues to use development-only diagnostic SELinux/Keystore compatibility
mechanisms; it is not production-secure. Input remains surface-focused and
uses the private per-session transport. No global keyboard capture or host
input configuration change was made.
