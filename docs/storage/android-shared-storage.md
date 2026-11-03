# Android shared storage on Linux

**M4 shared-storage integration: PASS.** The persistent Linux directory,
Android's emulated-storage FUSE mount, ordinary application SAF access, and
MediaStore external volume have been verified end to end. Canonical M4 remains
`PARTIAL/OPEN` because its separate audio, clipboard, notifications, and
launcher-catalog requirements remain incomplete.

## Current topology

The persistent backing directory is:

```text
/run/media/mrkus/Homework/aaas-workspace/shared-storage/android-media/0
```

`aaasctl storage path` prints the configured user-0 directory. `aaasctl storage
status` reports its direct-directory mode, backing root, host ACL state, and
accessibility. No FUSE alias is created on Linux: the selected Linux interface
is the ordinary directory itself. This avoids a second userspace filesystem,
mount permissions, and a helper process on a host whose workspace filesystem
already supports the required directory and ACL operations.

At session start, the rootless runner bind-mounts the parent
`shared-storage/android-media` at Android `/data/media`. This parent mapping is
intentional: Android vold creates its emulated-user pass-through view from
`/data/media`, then mounts Android's own FUSE filesystem at
`/storage/emulated`. Binding only user `0` directly at `/data/media/0` did not
provide the parent mount topology vold expects. The live runtime reported
`emulated;0` mounted, `/dev/fuse` mounted at `/storage/emulated`, and
`/storage/emulated/0` backed by the host directory.

The host workspace is on NTFS3. The backing and Android public folders retain
the mapped Android `media_rw` identity (host UID 101022 in this user namespace)
and have a named ACL for the host UID. AaaS repairs only those ACL entries; it
does not recursively `chown` or `chmod` user data. `Android/data` and
`Android/obb` are created mode 0700 without the host-user ACL. Live host access
checks denied reads through both paths. Android's app-specific FUSE/pass-through
rules remain in place.

### Alternatives considered

- **Direct persistent backing directory with an Android parent bind (selected):**
  gives Linux ordinary file operations without another mount daemon, while
  Android continues using vold and its existing emulated-storage FUSE layer.
  It is persistent and usable offline by Linux.
- **Linux-side bindfs/FUSE alias:** not selected because the existing host path
  is already an ordinary directory on the workspace filesystem. An alias would
  add a helper, mount lifecycle, and failure modes without improving Linux
  access or Android visibility.
- **Custom AaaS FUSE filesystem:** rejected because no required operation
  justified reimplementing a filesystem; Android already owns the Android-side
  FUSE interface.
- **Waydroid whole-container sharing conventions:** not copied wholesale. AaaS
  uses its own rootless bind setup and UID map; its tested Android media root is
  `/data/media`, and its host ACLs are managed without adopting Waydroid's
  container manager or privilege model.
- **Android SAF-to-host portal/picker bridge:** explicitly deferred by this
  capability decision. It would be a separate adapter and would not repair the
  current missing Android `external_primary` storage volume.

The container sees only the selected Android media parent at `/data/media`; it
does not receive the host home directory or unrelated host files. The Android
image, `/data/user/0`, `/data/system`, `/system`, `/vendor`, and Keystore data
are not part of this sharing path. A Linux user who owns the shared directory
can use ordinary filesystem features there, including creating a symlink; the
host path is not a broker that filters user-created links. Android-side link
resolution remains subject to Android's FUSE/storage implementation and has not
been accepted as a separate guarantee.

## Commands

Run from the repository root:

```bash
python3 scripts/aaasctl.py storage path
python3 scripts/aaasctl.py storage status
STORAGE="$(python3 scripts/aaasctl.py storage path)"
ls -la "$STORAGE"
ls -la "$STORAGE/Documents"
cp -- "$HOME/Videos/sample.mp4" "$STORAGE/Movies/"
cp -- "$STORAGE/DCIM/photo.jpg" "$HOME/Pictures/"
python3 scripts/aaasctl.py storage sync
```

The file paths in the `cp` examples refer to files the user already has; they
are examples of normal `cp` operands, not fixtures used in the acceptance run.
The backing directory can also be opened directly in any local-file-aware
desktop file manager. The path/status/sync controls are directory operations;
there is no Linux mount or unmount command and therefore no stale FUSE mount to
clean up. If `status` fails because the workspace is not available, remount the
workspace using the host's normal removable-storage process, then re-run
`storage status` or `storage sync`. Never unmount a host filesystem on behalf of
AaaS.

When Android is stopped, this backing directory remains available to Linux.
Android's FUSE mount is session-owned and disappears with the Android session;
the host files persist. A subsequent AaaS session rebinds the same parent.

## Android lifecycle repair and application boundary

Android exposes the directory through its normal emulated storage path, not by
replacing Android's file picker. Android apps must continue to use their usual
filesystem, SAF, DocumentsUI, and MediaStore APIs with Android's ordinary
permissions.

Before repair, user 0 was `RUNNING_UNLOCKED` and CE-unlocked and `emulated;0`
was mounted, but StorageManagerService reported `System unlocked users: []`;
MediaProvider only exposed `internal`. The cause was a system-server handler
ordering deadlock in the AaaS profile: `StorageManagerService.handleSystemReady()`
synchronously performed optional HEVC codec discovery on its ordered storage
handler. Here `MediaCodecList` waited for media service startup. UserManager's
unlock completion was queued to that same handler, so storage completion and
external volume attach could not run. Android 16 source confirms that
`handleSystemReady()` calls `configureTranscoding()`, which calls
`isHevcDecoderSupported()` ([StorageManagerService](https://android.googlesource.com/platform/frameworks/base/+/android16-release/services/core/java/com/android/server/StorageManagerService.java)).

The reversible session overlay now uses `false` as the optional transcoding
default, retaining explicit system-property and DeviceConfig overrides. This
avoids codec discovery on the ordered handler. Live snapshots now show
`System unlocked users: [0]`; vold reports `emulated;0 MOUNTED`; MediaProvider
attaches `external_primary` and scans it. No fixed sleep, fabricated lifecycle
callback, base-image mutation, scoped-storage bypass, or MediaProvider database
edit was used.

A second, independent NTFS3 ACL issue surfaced after the volume attached.
MediaProvider needed group write/search access to set its `user.*` xattrs and
maintain external-volume state. The shared root and public folders now receive
the mapped `media_rw` group permissions plus the existing host-user ACL. The
change is limited to those shared paths. `Android/data` and `Android/obb`
remain mode 0700 with no host-user ACL.

The live test app is an ordinary `/data/app` package (`org.aaas.storagetest`,
target SDK 28), not a system app. It completed both `ACTION_CREATE_DOCUMENT` and
`ACTION_OPEN_DOCUMENT`; ContentResolver wrote and read exact bytes through
DownloadsProvider URIs. A MediaStore query on
`content://media/external_primary/file` returned the Linux-created fixture.
Normal app permissions and URI grants remain in force. App-private directories
were not exposed. The SAF-to-XDG picker bridge remains explicitly deferred.

## Verified and unverified behavior

Verified in live sessions:

- `aaasctl storage path/status` exposes the persistent path as a normal host
  directory and reports host ACL/access readiness.
- Linux-created text, binary, nested, Unicode, and space-containing files were
  listed and read through Android `/storage/emulated/0` FUSE with matching
  SHA-256 values.
- Host random-access edit, file truncation, atomic same-directory rename, and
  directory listing operations succeeded. Android's FUSE view saw the edited
  bytes and new filename.
- A 1 MiB binary fixture retained SHA-256
  `075d38b5035791f97e1a261e8c9c04345e6426c5e9be7c83f0a401908501e7b8` across
  Android shutdown and a new runtime session.
- Linux host access through `Android/data` and `Android/obb` was denied.
- The user-level Linux path remains accessible while Android is stopped.

Verified after repair:

- Ordinary app `ACTION_CREATE_DOCUMENT` completed and wrote
  `Download/aaas-storage-android-to-host.txt`; host readback matched SHA-256
  `72ca9c361c0e9ae87d818cb60ac61817154973a3a86ae91f27c454218fe72238`.
- Ordinary app `ACTION_OPEN_DOCUMENT` returned a Downloads content URI.
  ContentResolver read the host-created fixture and logged
  `ANDROID_SAF_READ_OK` after exact byte comparison.
- MediaStore `external_primary` attached and indexed shared-storage entries,
  including the host fixture (`_id=1000009001` in the recorded query).
- A host edit from fixture v1 to v2 was read by the app in a later session; the
  v2 host SHA-256 was
  `4a077084728a18f2627f1f67d48820de9a0aea0e8b14179d1f704b5707b89213`.
- MediaProvider scanned the shared volume on mount. Host edits and a rename were
  indexed on the next clean session; deleting the renamed test fixture caused
  the next mount scan to report one deletion and the MediaStore query no longer
  returned its row. Immediate indexing for host edits during an active Android
  session is not claimed. Restart the Android session to trigger the verified
  mount scan; `aaasctl storage sync` repairs ACLs only and does not request a
  MediaStore scan.
- Android logs a nonfatal warning when it cannot assign a project-quota xattr
  on NTFS3 (`Invalid argument`). SAF reads/writes, MediaStore indexing, and
  persistence still pass. Project quota tagging is not supported by this
  backing filesystem and remains a known limitation.
- Host access to `Android/data` and `Android/obb` remains denied. The test app
  uses picker URI grants; no broad Android permission was granted.
- A synthetic symlink in shared storage targeting a host-only sentinel was
  inaccessible from the same Android-rootfs bind namespace (`ENOENT`); the
  sentinel and symlink were removed. This establishes the mount-namespace
  boundary, but does not claim application-specific symlink behavior through
  DocumentsUI.
- Human testing in Dolphin/Nautilus/Thunar remains untested; the host path is
  an ordinary local directory.

## Evidence and next work

Structured observations, session IDs, checksums, and raw-log hashes are in
[`results/m4/acceptance.json`](../../results/m4/acceptance.json). Raw runtime
logs and controlled fixtures remain under the external AaaS workspace, not in
Git. The shared-storage slice is `PASS`. Canonical M4 remains `PARTIAL/OPEN`;
audio, clipboard, notifications, launcher catalog work, and other lifecycle
gates are independent outstanding requirements. Immediate MediaStore updates
for host edits made while Android remains active are not verified; mount-time
scan/reconciliation is verified.
