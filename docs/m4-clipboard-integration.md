# M4 clipboard integration

**Status: PASS/CLOSED for bounded plain-text clipboard integration on the
accepted KWin host.** The initial 2026-11-06 continuation below correctly
recorded that bridge startup alone was not acceptance. The later live
continuation proves byte-identical text in both directions through Android
`EditText` and Linux Qt text widgets.

## Architecture implemented

The Android endpoint is `org.aaas.clipboard/.ClipboardImeService`, an explicitly
selected default input method. Android authorizes the selected IME to observe
primary-clip changes; ordinary applications retain Android's normal clipboard
privacy rules. The IME publishes bounded plain-text frames to a session-scoped
Linux-visible directory. A payload-free, DUMP-protected broadcast asks the
companion receiver to consume host-originated frames through `ClipboardManager`.

The Linux endpoint is `experiments/m4/clipboard/wayland_clipboard.c`. It is
started only for an active runtime session while AaaS Clipboard is the selected
IME. It uses KWin's `ext_data_control_manager_v1` protocol, binds the session
seat, and offers/receives `text/plain;charset=utf-8`, `text/plain`, and
`UTF8_STRING`. The bridge is launched in a rootless user namespace with the
runtime's existing UID/GID mappings. IPC is bounded to 64 KiB, validates UTF-8,
uses a sticky non-listable directory, validates the Android IME UID, and grants
read access to the host-to-Android frame only for that package UID. Frames are
not logged and are removed at session teardown.

The user's previous IME was recorded before the temporary test selection and
restored through Android's `ime` command before runtime shutdown. No Android
clipboard security policy was changed and no permanent clipboard service was
installed.

## Verification

- Focused Python tests: 85 passed across clipboard framing, runner and control
  tests.
- Native Wayland client: `make -C experiments/m4/clipboard clean all` passed
  with `-Wall -Wextra -Werror`.
- Full Python suite: 320 passed, zero failures, zero skips.
- Live session `m1b84_session_hm8w8zeh`: selected IME state was observed;
  session bridge logged `AaaS clipboard bridge ready`; changing away from the
  IME stopped the bridge; the runtime then reached `STOPPED` cleanly.
- Workspace guard passed on NTFS3 UUID `$AAAS_NTFS_WORKSPACE_UUID`, with 61,689,398,784
  bytes accounted against an 85,899,345,920-byte ceiling and 309,084,545,024
  bytes free against the 21,474,836,480-byte reserve.
- No AaaS runner or clipboard bridge process remained after shutdown. The
  previous Android keyboard was restored.

The clipboard bridge supports plain UTF-8 text up to 64 KiB only. Rich text,
images, and file URIs are unsupported and are not claimed.

## Live bidirectional acceptance (2026-11-06)

**M4 Bidirectional Clipboard Integration: PASS/CLOSED** for plain UTF-8 text on
the current KWin Wayland session. Reproducible details are in
`clipboard_live_acceptance_2026_11_06` in
**`results/m4/acceptance.json`** (maintainer archive only). The tested code
revision is `11e1fd656d5ffc6b6cf2700528d2cd23ad1dc011`, based on starting HEAD
`c1b08b75b28b301f007e9f6a33b0c20c1fd61bdf`.

The host was KDE/KWin 6.7.5 on Wayland (`wayland-0`, seat `seat0`). Registry
enumeration reported `wl_data_device_manager` v3, `ext_data_control_manager_v1`
v1, `zwp_primary_selection_device_manager_v1` v1, `zwp_text_input_manager_v2`
v1, and `zwp_text_input_manager_v3` v2. No `zwlr_data_control_manager_v1` was
advertised. The bridge selected `ext_data_control_manager_v1` v1, which
supports compositor-authorized clipboard ownership without inventing a client
input serial. Primary selection was not used as ordinary clipboard evidence.
The generic focused-client `wl_data_device_manager` path and the wlroots
data-control fallback are not implemented or claimed; the accepted M2/M4 host
is KWin and broader compositor support belongs to M6.

The bridge uses the selected Android default IME and its `ClipboardManager`
listener. For Android-to-host it reads the selected IME's bounded UTF-8 frame,
publishes a Wayland data-control source, and offers
`text/plain;charset=utf-8`, `text/plain`, and `UTF8_STRING`. For host-to-Android
it receives one of those MIME types, validates UTF-8 and size, writes a
session-scoped frame, and signals the package-UID-protected
`HostClipboardReceiver`, which updates Android `ClipboardManager`. The IME's
host-origin label suppresses echoes. No content is logged; diagnostics contain
only byte counts, state, and SHA-256 digests. IME selection remains explicit,
Android's normal clipboard policy is unchanged, frames are removed at teardown,
and stock LatinIME was selected before runtime shutdown.

Live session `m1b84_session_pwam6976` used package `org.aaas.clipboard`'s
ordinary non-privileged Android `EditText` and a real Qt text widget on the
host. Android copied the Unicode/multiline fixture through the standard
`EditText` copy context action. The Android-side digest was
`3955a7bf163c96523fbf737689822192874b00a5d7bf844db8aa11f46de98a4a` (67 UTF-8
bytes); the host Wayland Qt `QLineEdit::paste()` produced the same digest and
reported PASS. In the reverse direction, a Qt text widget copied a 58-byte
Unicode/multiline fixture through the desktop clipboard; Android received it
through `ClipboardManager`, and the `EditText` paste action produced digest
`474e09cb40847d7b9a9ca5815f523bf8fab4693f90b2a067d8e08d5fadf78433`, matching
the host source. The fixture contents are intentionally omitted from logs and
acceptance metadata.

The live bridge log showed Android frame publication, Wayland source offer,
owner-acknowledgement handling, and duplicate echo suppression. The initial
bridge deadlocked when its own compositor selection callback tried to read
from a source serviced by the same event loop; it now recognizes its own
selection and skips that synchronous read. An event-triggered bounded inotify
rescan handles coalesced Android frame moves. The receiver path was corrected
to the actual `/dev/aaas/clipboard/clipboard_host_to_android` mount. These
changes were exercised by the two transfers. A teardown defect was also fixed:
the session creates an empty placeholder for saved IME state, so checking only
file existence incorrectly made a normal M2 shutdown fail. Cleanup now uses a
no-follow regular file descriptor and restores only when a non-empty prior-IME
record exists. Focused regression tests cover empty placeholders, saved state,
and symlinks.

The current workspace guard passed on NTFS3 UUID `$AAAS_NTFS_WORKSPACE_UUID`; the final
post-session sample recorded 61,822,830,080 bytes used against an 80 GiB
ceiling and 308,951,113,728 bytes free against a 20 GiB reserve. Fresh M2
Settings/Contacts session `m1b84_session_9nut5798` verified separate windows,
closing Contacts while Settings remained RUNNING, balanced presenter buffers
(108/108 and 72/72 imports/releases), and zero outstanding buffers. After the
IME cleanup correction it ended `STOPPED`. The full suite passed 325 tests,
zero failures and zero skips; focused clipboard/runner/control tests passed 90.
The native build passed with warnings as errors. No runner, clipboard bridge,
test client, or stale session mount remained.

### Scope and limitations

This closure covers bounded plain UTF-8 text only (up to 64 KiB). Rich text,
HTML, image and file-URI clipboard transfer are unsupported. Only KWin's
advertised `ext_data_control_manager_v1` backend was live-tested; no fallback
or cross-compositor claim is made. Android and host clipboard ownership follow
their normal platform lifetimes; AaaS does not keep a process alive to retain
clipboard ownership after shutdown. The earlier `apps=[]` report was an
automation inventory limitation and did not affect the independent registry,
Wayland-client, Android API, or presenter evidence.
