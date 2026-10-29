# M1D — Native keyboard input and Android text entry

Status: **IN PROGRESS**
Baseline: M1C.1 `3b2eb73`
Runtime: Android 16 x86_64, rootless container, KWin Wayland, portrait 720×1280

## Objective

Extend the existing surface-local Wayland input path so a physical keyboard can
type, edit, and navigate in real Android applications. Preserve the M1C pointer
protocol and the existing graphics, synchronization, LMKD, cgroup, and launcher
behavior.

## Phases

1. **M1D.0 transport and KeyEvent delivery:** bind `wl_keyboard`; consume its
   XKB keymap, key, modifiers, and repeat information; transport validated key
   transitions over the existing private input connection; inject Android
   `KeyEvent`s through the existing persistent Binder adapter; release held
   keys on focus loss and shutdown.
2. **M1D.1 text and editing:** translate physical key identity and active XKB
   symbols to Android keycodes/meta state; validate text entry, editing,
   navigation, and the host's active layout in Settings.
3. **M1D.2 focus and composition:** validate focus isolation, key repeat,
   adapter reconnection, IME behavior, and safe shutdown; investigate Unicode
   and composed text separately from ordinary key events.

The phase labels organize implementation and evidence; they do not authorize a
protocol rewrite or a replacement input service. The current v1 input packet
is 68 bytes and carries pointer semantics. Any keyboard extension must be
explicitly versioned and negotiated while preserving v1 pointer handling.

## Implementation constraints

- Use host `libxkbcommon` for keymap and state processing when available.
- Preserve physical evdev identity, XKB symbol, Android keycode, meta state,
  repeat, and committed text as distinct concepts.
- Reuse the current presenter, private socket/session identity, adapter, and
  Binder service connection.
- Do not spawn `cmd input` once per key.
- Never log typed text or capture keys while the AaaS window lacks keyboard
  focus.
- Reconcile pressed keys and stop repeats on focus loss, disconnect, and exit.
- Validate Android parcel/AIDL semantics against the Android 16 runtime or
  matching source, not guessed transaction layouts.

## Verification order

1. Preserve and run the M1C.1 baseline.
2. Validate protocol, XKB, key mapping, and Android event serialization in
   focused tests.
3. Demonstrate Down/Up events reaching Android before adding text composition.
4. Type and edit in the actual Settings search field.
5. Test focus isolation, key repeat, modifiers, navigation, and held-key
   cleanup.
6. Repeat portrait, pointer, scrolling, graphics, and shutdown regressions.
7. Record manual evidence separately from automated and runtime evidence in
   `results/m1d/acceptance.json`.

## Acceptance policy

M1D is not complete based on host event receipt or successful Binder calls
alone. Basic text entry, editing, navigation, focus isolation, and key cleanup
must be observed in Android. Complex Unicode/IME composition may be separately
bounded only after ordinary physical-key text entry works and the supported
behavior is documented honestly.
