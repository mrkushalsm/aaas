# Android notification forwarding

**Workstream status: PASS/CLOSED (2026-11-06).** Canonical M4 remains
`PARTIAL/OPEN` for audio playback and microphone capture.

## Data path

Each AaaS session installs `org.aaas.notifications` as an ordinary Android
package. Its `ForwardingListener` is a standard
`NotificationListenerService`, protected by Android's
`BIND_NOTIFICATION_LISTENER_SERVICE`. It observes posts, updates, and removals
only after the user enables it through Android Notification Listener Settings.
The runtime does not grant notification-listener access or `POST_NOTIFICATIONS`
on the user's behalf. Ordinary apps continue to request their own Android 13+
notification permission.

For non-secret notifications, the listener forwards only the package name,
Android user ID, notification key, app label, title, and text. It drops
`VISIBILITY_SECRET`, bounds UTF-8 fields, rejects NUL and oversized frames, and
does not log payloads. Frames use a versioned, base64url UTF-8 encoding and
unique temporary files in a session-private IPC mount. The directory is
non-listable and sticky; inherited ACL grants the host session user read access
to event files. The host adapter checks the mapped Android listener UID,
requires regular bounded files, refuses symlinks, and deletes consumed frames.
Only the authorized listener's frames are forwarded. This IPC is session-local
and is not exposed on a network interface.

The host adapter runs as the regular desktop user, connects to the existing
session D-Bus, and calls the standard
`org.freedesktop.Notifications.Notify` and `CloseNotification` methods. It maps
the Android user/package/key tuple to a host notification ID, passes that ID as
`replaces_id` on updates, and closes the mapping on Android removal or runtime
shutdown. The mapping is memory-only and capped at 256 active notifications.
No notification body is written to logs or persistent storage. D-Bus failure
disables forwarding for the session without changing Android notification
permissions.

The accepted host advertised Plasma/KDE 6.7.5, notification spec 1.2, with
`body`, `body-markup`, `body-images`, `icon-static`, `actions`, `persistence`,
and other KDE capabilities. The bridge sends app label, title, and HTML-escaped
body. It does not forward Android icons, actions, or PendingIntents in this
version; host icon/action capabilities do not imply those Android fields are
currently supported.

## Live acceptance

The final exact-source two-app session was
`m1b84_session_7p0fnax9`. The Android listener package was UID 10160 and its
listener authorization was explicitly enabled in Settings. Two separately
installed, ordinary target-SDK 35 probes had distinct UIDs:

| Android package | UID | Host notification ID | Update | Cancel |
|---|---:|---:|---|---|
| `org.aaas.notificationprobe` | 10161 | 109 | Reused 109 | Closed 109 |
| `org.aaas.notificationprobe2` | 10162 | 108 | Reused 108 | Closed 108 |

Both probes created a channel, requested `POST_NOTIFICATIONS` through the
ordinary Android runtime-permission flow, and posted through
`NotificationManager`. Android logcat recorded separate `notification_enqueue`
and `notification_canceled` events with the corresponding package-specific
keys. The host adapter log records post, update, and close for each package.
Thus duplicate numeric notification IDs from different packages remained
independent. A separate real Android update was visually observed as a Plasma
desktop notification with the app label, title, and body. During a separate
shutdown check, a D-Bus monitor observed `CloseNotification` for the active
host ID when AaaS stopped.

Evidence hashes for the final two-package run are:

- Host adapter event log: `a5849a14b141b97ec9c9f52563b5807ea640bb9cc5ae0493e00808ae4d365768`
- Android logcat: `eb933bc66025800dc8d9d6e2f994672ccbcb745cb53cca60de71b25dd6534230`
- Session command log: `c9344b09bd0204dba9ad19eee95933954f3d43d5fca06bef1905404f078f85a8`
- Built listener APK (kept in workspace, not Git): `04fcc5491e633ee177995618e7d90d0fbaf3ac166ff4e703983c5e56e79241fb`

The test body was synthetic and deterministic. Raw logs and APKs remain in the
workspace and are not committed. The full host suite passed 339 tests with no
failures, errors, or skips. The final session stopped cleanly; no AaaS runner,
notification adapter, clipboard bridge, IPC socket, or notification event
frame remained. The accepted workspace UUID was still mounted read/write and
the workspace guard passed. M2/M3 live smokes were not repeated in this
notification-only continuation; the accepted M2/M3 source was unchanged.

## Build and operations

The session builds the listener from
[`experiments/m4/notifications`](../experiments/m4/notifications), installs it
through PackageManager, and polls Android's actual enabled-listener setting.
`aaasctl notifications setup` opens the standard Android listener settings
screen. The host bridge is started only for an authorized listener and only
inside the active AaaS session. Shutdown closes active host IDs and removes
session event frames. No Android system image or host notification daemon was
modified.

The structured run record is
`android_notification_forwarding_2026_11_06` in
[`results/m4/acceptance.json`](../results/m4/acceptance.json).
