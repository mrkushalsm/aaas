# Android shared storage on Linux

**M4 storage slice: PARTIAL/OPEN.** The persistent Linux directory and Android
emulated-storage mount are connected. Host-created files are visible through
Android's `/storage/emulated/0` FUSE view, and that data survives Android
shutdown and restart. Android app writes, SAF document creation, and MediaStore
indexing are currently blocked by the runtime's storage-volume lifecycle state;
this document does not claim bidirectional application-level acceptance.

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

## Android boundary and current limitation

Android exposes the directory through its normal emulated storage path, not by
replacing Android's file picker. Android apps must continue to use their usual
filesystem, SAF, DocumentsUI, and MediaStore APIs with Android's ordinary
permissions.

The live runtime showed `VolumeInfo{emulated;0}` in `MOUNTED` state and the
FUSE mount was present, but `dumpsys mount` reported `CE unlocked users: [0]`
and `System unlocked users: []`. Android's MediaProvider consequently had only
its `internal` database volume and logged `Volume external_primary not found`.
A normally installed, controlled app's public-storage write failed with
`EPERM`; the Android DocumentsUI `ACTION_CREATE_DOCUMENT` flow displayed “Failed
to save document.” A supported `MEDIA_MOUNTED` broadcast did not repair the
missing MediaProvider volume. The Android user manager reported user 0 as
`RUNNING_UNLOCKED`, so a later integration must resolve the discrepancy between
that state and StorageManagerService's system-unlocked user list before claiming
normal Android-side read/write or MediaStore coherence.

The corresponding Android 16 implementation is in
[StorageManagerService](https://android.googlesource.com/platform/frameworks/base/+/android16-release/services/core/java/com/android/server/StorageManagerService.java): user-unlock completion updates the system-unlocked-user state and drives volume state propagation. The observed mismatch is therefore recorded as a runtime lifecycle defect inferred from the live service state and that implementation, not as proof that the direct host backing is inaccessible.

This blocker is independent of the host directory's ACL and of Linux-to-Android
visibility. No broad storage permission, Android permission bypass, direct
MediaProvider database edit, or custom picker/provider was added. The SAF-to-XDG
picker bridge remains explicitly deferred.

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

Not accepted:

- Android application direct file reads or writes through its normal storage
  APIs; direct app write was denied with `EPERM`.
- Android SAF `CREATE_DOCUMENT`; DocumentsUI failed to create the file.
- MediaStore discovery/update after host create, modify, rename, or delete; the
  `external_primary` volume was absent.
- Android-originated file creation and byte-exact Linux readback.
- User-created symlink resolution as a cross-OS security guarantee.
- VLC, mpv, or BFE follow-up. Their earlier storage-blocked observations remain
  historical and were not rewritten by this incomplete integration.
- Interactive human validation in Dolphin, Nautilus, or Thunar. The directory
  is an ordinary local filesystem path; no GUI usability claim is made.

## Evidence and next work

Structured observations, session IDs, checksums, and raw-log hashes are in
[`results/m4/acceptance.json`](../../results/m4/acceptance.json). Raw runtime
logs and controlled fixtures remain under the external AaaS workspace, not in
Git. The storage slice stays `PARTIAL/OPEN` until Android app-level reads and
writes, SAF access, and storage-index consistency pass. Canonical M4 also
remains `PARTIAL/OPEN`; audio, clipboard, notifications, and launcher catalog
work are independent outstanding M4 gates.
