# M2 — Independent desktop windows

**Status: PASS/CLOSED — KWin-supported product contract.** M2 means two
distinct Android apps as independent native Wayland windows with real Android
rendering, resize, focus, keyboard/pointer input, independent close/reopen,
and clean shutdown. Its scope is KWin on Linux Wayland; it does not include
ARM64 translation, 60 FPS, zero-copy, or other compositors. The authoritative
roadmap is [Plan A](../roadmap.md); M1E is its supporting technical experiment.

## Acceptance evidence

The current-head live run is `m1b84_session_7n1k5nlw` (2026-11-03), KWin
6.7.5, default rootless Android 16 runtime. Settings task 8 used Android display
2 and Contacts task 9 display 3. Separate KWin Wayland windows were
`AaaS: com.android.settings` (`org.aaas.com-android-settings`) and
`AaaS: com.android.contacts` (`org.aaas.com-android-contacts`). Both initially
rendered source buffers at 720×1280.

Settings was resized through KWin's window geometry/configure path from
420×740 to 500×800 and back. Android display 2 was resized at generations 2
and 3; matching Android source frames 115 (500×800) and 143 (420×740) were
both presented. Contacts independently reached a matching 500×800 source
frame 130; it was committed but discarded when superseded. The next frame,
131, was presented at generation 2 while Settings continued presenting. A
temporary mismatched old-size source frame was rejected during transition;
validation remained enabled. This confirms actual producer convergence, not
viewport scaling.

Contacts was closed while Settings remained `RUNNING`, then reopened in the
same Android runtime on new display 4; new Contacts frames were presented.
Final session state was `STOPPED`. Settings accounting was 238 imports,
submissions and releases, zero outstanding. The original Contacts presenter
balanced 182 imports/submissions/releases; the reopened presenter balanced 34;
both had zero outstanding buffers and zero teardown invalidations.

Visible input and focus isolation are supported by recent real KWin sessions:

- [`desktop_input_probe_20261031.json`](../../results/m1e/live/desktop_input_probe_20261031.json): focus switched between Settings Search and Contacts First name; host keyboard edits appeared in the selected app, while the other app's text remained unchanged.
- [`postresize_visible_input_20261101.json`](../../results/m1e/live/postresize_visible_input_20261101.json): after both Android displays reached matching 950×1100 source buffers, pointer navigation/editing produced visible responses on Settings and Contacts.
- [`contacts_menu_final_live_20261102.json`](../../results/m1e/live/contacts_menu_final_live_20261102.json): real KWin Wayland pointer events opened Contacts menus in default and enhanced modes. Both sessions stopped cleanly; enhanced cgroup was removed.
- [`dynamic_reopen_enhanced_lmkd_20261030.json`](../../results/m1e/live/dynamic_reopen_enhanced_lmkd_20261030.json): Settings closed and reopened on a new display while DeskClock remained alive; the enhanced cgroup was removed at shutdown.

These records are combined only for the M2 behaviors each directly demonstrates.
No result is inferred from cross-compositor testing. The low-level origin of
older Binder-only touch misses remains separate from the accepted platform
touchscreen path.

## Current-head provenance and raw evidence

- Repository HEAD at audit: `11f91ec514249f3c22fea318eb7e4edb23316466`.
- Android base image fingerprint, unchanged: `Android/sdk_phone64_x86_64/emu64x:16/BE2A.250530.026.D1/13818094:userdebug/test-keys` (preservation manifest).
- SwiftShader runtime overlay: SHA-256 `e42a0bd8dfe3e0eea6c3d6753f9f9fa254d348366847241ca3c7e4b9ac9affee`.
- Current Composer diagnostic overlay: SHA-256 `668bfd8198d5457d50a17b53c0ee37d5693b7ea34133e90441c2903c61a55f3d`.
- Current presenter log: `$AAAS_WORKSPACE/tmp/m1b84_session_7n1k5nlw/virtual-presenter.log`, SHA-256 `1d47b97105ef0fc6b40926162a09954d42362155c3e447ce9296d9f991f764c2`.
- Current second presenter log: `$AAAS_WORKSPACE/tmp/m1b84_session_7n1k5nlw/virtual-presenter2.log`, SHA-256 `0a7a4bf14593b70e9ceb68772cf7fc8d8bd9ad55b7e22f695e7377a7f4cde244`.
- Current display-broker log: `$AAAS_WORKSPACE/tmp/m1b84_session_7n1k5nlw/ipc/display_broker.log`, SHA-256 `7b617d279c4a9a3ea392869baef6073bb0b2d62279d338877f2201692f9f3ec0`.
- Current session state: `$AAAS_WORKSPACE/tmp/m1b84_session_7n1k5nlw/state.jsonl`, SHA-256 `0f8cd0f30e6cf93ca35bfb83e321526a3d5fda795d69da0b41cee4db9825ed1a`.
- Current runtime graphics provenance: `$AAAS_WORKSPACE/tmp/m1b84_session_7n1k5nlw/runtime-graphics-provenance.json`, SHA-256 `ff36cbfb7ebdd6697480fcc4ff61e23aa43cc8ccf47050e7c8f33105349ad863`.
- KWin native window listing: `$AAAS_WORKSPACE/tmp/m1b84_session_7n1k5nlw/kwin-window-identities.txt`, SHA-256 `d1de15cb28d4e18050148283edeb5b3218bdf8aee84140e4dec088194e3b78fa`.

The full 243-test Python suite, M1A tests, Composer tests in an isolated `/tmp`
build directory, and workspace guard passed during this audit. Full gate
mapping and raw-log references are machine-readable in
[`results/m2/acceptance.json`](../../results/m2/acceptance.json). The preceding
2026-11-02 M1E regression record reports 222 Python tests and applicable native
checks passing. M2 does not close the separate M5 graphics-performance or M6
cross-compositor workstreams.
