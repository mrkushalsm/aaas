# M4 clipboard integration

**Status: PARTIAL/OPEN.** This continuation implements an opt-in, session-owned
clipboard transport, but the required ordinary-application cross-boundary
copy/paste acceptance has not yet been demonstrated. Do not treat this
implementation or the bridge-ready log as PASS/CLOSED evidence.

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
- Workspace guard passed on NTFS3 UUID `A2ACEDF2ACEDC0C1`, with 61,689,398,784
  bytes accounted against an 85,899,345,920-byte ceiling and 309,084,545,024
  bytes free against the 21,474,836,480-byte reserve.
- No AaaS runner or clipboard bridge process remained after shutdown. The
  previous Android keyboard was restored.

## Unaccepted requirements

The available computer-use surface returned an empty application inventory
(`apps=[]`) and its native application methods were unavailable. Therefore this
run could not interact with a normal Android editable field and a normal Linux
editable field to verify paste in both directions. It also did not establish
clipboard replacement, clear, rapid updates, empty values, Unicode preservation
through both actual application UIs, or focus-transition behavior. Internal
frame tests and bridge connection are not substitutes for those acceptance
gates. The clipboard workstream remains **PARTIAL/OPEN** until both directions
are verified by ordinary application copy/paste and these live results are
recorded.

The clipboard bridge supports plain UTF-8 text up to 64 KiB only. Rich text,
images, and file URIs are unsupported and are not claimed.
