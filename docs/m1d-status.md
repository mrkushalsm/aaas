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
and toolchain. The recorded artifacts are:

| Component | SHA-256 | ELF build ID |
|---|---|---|
| Wayland presenter | `c229bc8030c21f1ef339671b1771f94e40021abc8681e54eb801a56f65055a2d` | `9ce42dba8058e94d5904d5ec7700079910b0043b` |
| Android input adapter | `86f25415596326619ff6f2759e1541d50ca82b2204adc54b01a9fe40ee417418` | `1445c6eb2222614d18c27d42c2a590f6a0d84dc6` |

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

Two post-implementation sessions completed the launcher's normal state sequence
through `RUNNING` and exited through `STOPPING` → `STOPPED`:

- Default: `python3 scripts/run_aaas.py`, session `m1b84_session_0_c4yw84`.
- Enhanced: `python3 scripts/run_aaas.py --use-source-lmkd --memory-policy=cgroup`,
  session `m1b84_session_ctvu_yf2`.

Both presenter logs show pointer and keyboard seat capabilities, keyboard bind,
Wayland repeat information, an accepted XKB keymap, and negotiated
`keyboard_v2:true`. Both adapter logs show keyboard focus enter and clean stop.
The presenters streamed Android frames (468 and 472 submissions respectively)
with zero rejected frames and zero dropped input packets. Raw logs remain on
the external workspace at:

```text
/run/media/mrkus/Homework/aaas-workspace/tmp/m1b84_session_0_c4yw84/
/run/media/mrkus/Homework/aaas-workspace/tmp/m1b84_session_ctvu_yf2/
```

The enhanced cgroup run emitted a memory-policy cleanup warning while
restoring one PID's cgroup placement; the session hierarchy was removed and no
launcher, adapter, or presenter process remained afterward. This warning is
recorded in `results/m1d/runtime_smoke.json` and is not treated as evidence of
perfect cgroup cleanup.

### Evidence boundary

These live runs established Wayland keyboard capability/keymap discovery,
protocol negotiation, keyboard focus delivery, and Android runtime stability.
They did **not** exercise a key-down/key-up packet. The adapter logs contain no
`key_injected` event, no physical keystrokes were recorded, and no Settings
search text was verified. No screenshot of typed text was captured. Therefore
we have not established that Android accepts the serialized KeyEvent or that
typing, editing, modifiers, navigation, repeat, and focus isolation work in a
real Settings field.

The packet includes an XKB Unicode scalar for diagnostics/translation context,
but the current Android injection path does not implement a committed-text or
IME composition channel. Dead keys, arbitrary Unicode, and composed text are
not supported or verified. Do not treat host XKB text resolution as Android
text-entry proof.

## Acceptance gates

The machine-readable status is `results/m1d/acceptance.json`. Current outcomes:

- **PASS:** G1 preservation; G2 Wayland keyboard discovery; G3 keymap parsing
  and common mapping; G17 automated builds/tests.
- **PARTIAL:** G4 negotiated keyboard packet transport; G5 Binder injector
  build/parcel inspection; G11 cleanup implementation; G12 repeat path;
  G13 composition boundary; G15 default/enhanced runtime startup and shutdown;
  G18 reproducibility.
- **NOT TESTED:** real Android text entry/editing/navigation, focus isolation
  with another host window, physical key repeat, M1C pointer/scroll live
  regression during these runs, and keyboard latency.

M1D is **not closed**. The next required experiment is a controlled live key
press/release into a focused Settings search field, with adapter injection
result, Android-side text-field state, and before/after Android frame evidence.
Then validate editing, modifiers, navigation, focus loss, held-key cleanup,
and composition limits before marking the milestone complete.

## Commits

- `c72c41a` — keyboard transport, XKB mapping, and persistent Android KeyEvent
  injection implementation with focused tests.
- Documentation/evidence closure is committed separately after this report
  and the machine-readable results are finalized.

## Reproducibility and security

`results/m1d/preservation_manifest.json` records the baseline Git state,
workspace identity, source revisions, and pre-change hashes. Build receipts,
runtime summaries, and test logs are recorded separately. The Android runtime
continues to use development-only diagnostic SELinux/Keystore compatibility
mechanisms; it is not production-secure. Input remains surface-focused and
uses the private per-session transport. No global keyboard capture or host
input configuration change was made.
