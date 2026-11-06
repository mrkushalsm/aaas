# AaaS session clipboard bridge

This directory contains the KWin Wayland data-control endpoint and Android
clipboard companion. The host endpoint is session-owned and speaks
`ext-data-control-v1`; it does not use Klipper, X11, or a fake Wayland seat.
The Android companion is an explicitly selected input method, which uses the
Android 16 default-IME clipboard authorization instead of weakening clipboard
access for ordinary apps.

The normal runtime installs the companion but does not enable or select it.
While a two-output session is active, `python3 scripts/aaasctl.py clipboard
setup` opens Android's ordinary Input Method Settings screen. The user must
enable and select **AaaS Clipboard** there. The host Wayland client starts only
while Android reports that component as the default input method; changing the
selection stops the client and drops its session clipboard files. This IME has
no on-screen keyboard view; AaaS delivers desktop key input through its existing
window input route. A user can restore their previous IME through the same
Android settings screen.

The wire file format is deliberately small and bounded:

```
AASCLIP1\nT\n<UTF-8 text bytes>
```

or `AASCLIP1\nC\n` for an empty clipboard. Files are session-local, are not
logged, and are removed when the bridge is disabled or at runtime teardown.
Android-origin frames are unique files created mode 0600 in a sticky,
non-listable directory. The host helper runs in a rootless user namespace,
validates the selected IME's Android UID, and unlinks each consumed frame.
Host-to-Android files are mode 0600 and carry a named read ACL only for the
selected IME UID.
This keeps clipboard payloads out of other Android apps' readable namespace.

Supported content is plain UTF-8 text, up to 64 KiB. Rich text and file URIs
are not part of this bridge.
