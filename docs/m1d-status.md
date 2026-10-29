# M1D — Native keyboard input and Android text entry

Status: **PARTIAL — implementation built; end-to-end key and text behavior remains unverified**
Baseline: M1C.1 commit `3b2eb73`
Runtime: Android 16 x86_64, rootless container, KWin Wayland, portrait 720×1280

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
python3 scripts/android_workspace.py --workspace /run/media/mrkus/Homework/aaas-workspace check  PASS
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
[`settings_after_synthetic_key_probe.png`](../results/m1d/evidence/settings_after_synthetic_key_probe.png).

## Settings editor focus investigation

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
paths and hashes are recorded in [`editor_focus_probe.json`](../results/m1d/editor_focus_probe.json).

Screenshots show the unchanged search homepage after the click and a
successful adjacent category navigation:

- [`settings_search_click_no_transition.png`](../results/m1d/evidence/settings_search_click_no_transition.png)
- [`settings_category_click_control.png`](../results/m1d/evidence/settings_category_click_control.png)

No synthetic keyboard fixture was sent after this discovery because no
editable Android view or InputConnection was focused. Text entry, editing,
Enter/Escape behavior, modifiers, repeat, and focus isolation remain untested.
M1D remains **PARTIAL**. The next task is to unblock normal user-0 CE storage
unlock in the isolated runtime, then repeat the search click and only then
resume KeyEvent-to-view tracing.

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

The foreground runner was stopped with Ctrl+C and reached `STOPPED`. One
regression-test invocation while it held the single-instance lock failed the
lock test as expected; the complete Python suite was rerun after shutdown and
passed 123 tests. The enhanced source-LMKD/cgroup path remains supported by
prior startup/shutdown smoke evidence, including its recorded cgroup cleanup
warning.

## Evidence boundary

The first disappearing stage from the controlled key probe was **not** the
presenter or Binder: Wayland key events were translated, serialized into the
versioned keyboard packet, validated by the adapter, and accepted by Android's
`IInputManager`. The next required proof is that an Android Settings text
editor actually owns focus and changes visibly from those events. Binder's
positive injection reply does not prove InputDispatcher delivered the event to
the intended view. No fix to the keyboard implementation is justified by the current evidence;
the UI attempt had an unverified editor focus state.

Still unverified live: physical keyboard text entry, Backspace/Delete/caret
editing, Enter/Escape navigation, modifiers, repeat, host focus isolation,
held-key cleanup under focus loss, IME composition, and a controlled screenshot
showing changed text. The latest visual capture remains unchanged Settings
content, and M1D is therefore **PARTIAL**.

## Acceptance gates

The machine-readable gate results are in `results/m1d/acceptance.json`.
Wayland discovery and XKB mapping pass; controlled versioned packets reached
the adapter; and Android's `IInputManager` accepted synthetic KeyEvent DOWN/UP
requests. Those stages do not satisfy the user-facing text-input requirement.
Basic Settings text entry is still partial, while editing, navigation, physical
keyboard attribution, repeat, focus isolation, and visible app response remain
unverified. The milestone is **PARTIAL**, not closed.

## Commits

- `c72c41a` — keyboard transport, XKB mapping, and persistent Android KeyEvent
  injection implementation with focused tests.
- `c1ddd3f` — initial M1D partial status.
- Live diagnostics and evidence updates are committed separately.

## Reproducibility and security

`results/m1d/preservation_manifest.json` records the baseline Git state,
workspace identity, source revisions, and pre-change hashes. Build receipts,
runtime summaries, and test logs are recorded separately. The Android runtime
continues to use development-only diagnostic SELinux/Keystore compatibility
mechanisms; it is not production-secure. Input remains surface-focused and
uses the private per-session transport. No global keyboard capture or host
input configuration change was made.
