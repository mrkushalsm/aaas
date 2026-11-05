# Android shared storage on Linux

**M4 shared-storage core: PASS; integration: PARTIAL/OPEN.** The persistent Linux directory,
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
Git. The shared-storage core is `PASS`; the wider storage integration is
`PARTIAL/OPEN`. The latest explicit scan is live-verified in the diagnostic
session only. Canonical M4 remains `PARTIAL/OPEN`; audio, clipboard,
notifications, launcher catalog work, and other lifecycle gates are separate.

## Hardening and real-application follow-up (2026-11-04)

### Latest continuation

This hardening run started from `4423fd2ee2363d5558c8b0f93f2990478261e919`.
The controlled target-SDK 35 probe was corrected to start DocumentsUI at the
shared-storage Documents provider. The exact v3-signed APK installed as an
ordinary `/data/app` package. `ACTION_OPEN_DOCUMENT` returned a URI and
ContentResolver read the host fixture byte-exactly (SHA-256
`4a077084728a18f2627f1f67d48820de9a0aea0e8b14179d1f704b5707b89213`).
`ACTION_CREATE_DOCUMENT` wrote through ContentResolver and Linux read back
SHA-256 `72ca9c361c0e9ae87d818cb60ac61817154973a3a86ae91f27c454218fe72238`.
A persistable URI grant survived force-stop and relaunch of the app. Android
runtime restart persistence of that grant was not tested.

An explicit `aaasctl storage scan RELATIVE_PATH` path now asks a running
session's ordinary Android probe to invoke public `MediaScannerConnection`
and waits for its scan callback. In one uninterrupted Android session, host
create, update, rename and delete were each reconciled and checked through
actual MediaStore queries. Rename reconciliation scanned the new path and the
missing old path; the stale old MediaStore row disappeared. The helper is
currently enabled only in sessions launched with `--diagnostic-storage-apk`;
ordinary sessions report that the helper is unavailable. This is a verified
diagnostic integration path, not yet a general user-session MediaStore sync
feature. `storage sync` continues to repair ACLs only.

Real application follow-up:

- **VLC:** ordinary APK, selected the synthetic MP4 through its native
  DocumentsUI flow. ARM64 libVLC opened the content descriptor, parsed MP4 and
  H.264 metadata, and read video samples. VLC disabled video stream selection;
  decoder execution and visible frames were not verified. Storage read: PASS;
  playback: PARTIAL.
- **mpv:** ordinary APK, selected the file using its SAF tree flow and granted
  access through DocumentsUI. mpv opened the content URI, loaded ARM64
  `libmpv.so` through Berberis, selected Android's H.264 MediaCodec decoder,
  and initialized a surface. A visible frame, seek, and pause/resume were not
  verified. Storage open: PASS; presentation: PARTIAL.
- **Banners File Explorer:** ordinary APK; its declared all-files permission
  was enabled through Android's package-specific Settings screen for this
  test. It created a directory and file. The initial app-created directory
  lacked the host UID default ACL because session startup logged
  `newuidmap ... Operation not permitted` while repairing storage ACLs. A
  subsequent explicit `storage sync` repaired the shared root defaults, and a
  later app-created directory inherited host access. This startup ACL failure
  means the real-app integration is still PARTIAL; no archive operation was
  verified.

The active scan helper and app results are detailed in the latest run record
in `results/m4/acceptance.json`. Scan log hashes are `8b295a03f36d689b1e30e0e56c9d8c83bf752d8e75509903b860648036c54fed` (logcat) and
`652e5bee2dd890a29148fce5f7071c8dd426a51ceb22f90ed40151deb151a8b6` (commands).
VLC log hash: `f7dd77f839ddd8cd016f0e0af3c3e0835fdcba38b0c8935a8f1bf6506905b743`;
mpv: `b65b0a7753f895cad553b6473288e5c0e9282e9a33663e56a0741d70bc6074bd`;
BFE: `7a7826267e9d3519d67fc581eb00647ef81f2bfe781ad5b4b5d65768c3d637d6`.

### Previous follow-up observations

The controlled shared-storage core remains accepted based on the historical
ordinary-app SAF read/create, `external_primary` attachment, mount-time scan,
byte checks, and restart evidence above. This follow-up does **not** close the
broader storage integration: live host changes are still not reconciled into
MediaStore while Android remains active, and current real-app/modern-target
workflows have not completed end to end.

### MediaStore consistency boundary

The verified contract remains mount/startup reconciliation. `python3
scripts/aaasctl.py storage sync` repairs host ACL access; it does not initiate a
MediaProvider scan. No AaaS live-session scan request was implemented or
verified in this follow-up. Do not infer MediaStore indexing from Linux or
Android shell directory listing. A follow-up must issue a supported Android
MediaProvider scan request while the session is active and query the actual
MediaStore rows after host create, update, rename, and delete operations. It
must avoid editing the MediaProvider database and avoid periodic recursive
scanning.

### Transcoding behavior

The existing session-local `services.jar` correction retains a conservative
`false` default for optional HEVC transcoding discovery while preserving
explicit property and DeviceConfig overrides. Existing acceptance attributes
the startup hang to synchronous `MediaCodecList` capability discovery on the
ordered StorageManagerService handler waiting for media service initialization,
which blocked user-unlock completion; NTFS3 `media_rw` ACL repair was a second,
independent requirement for SAF writes. The exact source commit matching the
installed Android image is not available, so analysis is against the
`android16-release` source branch. This follow-up did not establish HEVC
capability enumeration or override behavior. VLC's ARM64 libraries loaded, but
it requested `MANAGE_APP_ALL_FILES_ACCESS_PERMISSION`; no permission was
granted and no video decode was claimed. The default workaround's media
compatibility therefore remains only partially characterized.

### Modern API and third-party results

A target SDK 35 diagnostic APK installed as an ordinary package and launched
`ACTION_OPEN_DOCUMENT`; DocumentsUI opened, but its initial Downloads-provider
view did not expose the intended fixture and no byte-checked ContentResolver
read completed. This is picker-launch evidence, not modern SAF acceptance.

- **VLC:** ordinary app launched; Berberis loaded `libvlc.so` and
  `libvlcjni.so`. A direct file URI caused VLC to request the broad all-files
  setting. It was not granted; file read, decode, seek, pause/resume, and frame
  presentation remain unverified.
- **mpv:** ordinary app launched and the synthetic video was present during
  the session's mount scan, but file read/decode/frame presentation was not
  verified.
- **BFE:** ordinary `/data/app` installation and MainActivity launch passed.
  The APK declares `MANAGE_EXTERNAL_STORAGE`; it was not granted. File mutation
  and archive operations were not performed.

The original APKs were not modified. These results do not replace or rewrite
historical Post-M3 observations. New session logs and hashes are recorded in
`results/m4/acceptance.json` under `storage_hardening_follow_up`.

### Filesystem and security limits

MediaProvider again logged an NTFS3 project-quota xattr error for synthetic
media. Core reads, SAF writes, and mount-time MediaStore indexing passed in the
previous acceptance, but quota tagging/accounting and StorageStatsManager
behavior remain uncharacterized. The previous single synthetic host-only
symlink test only established that one target was not visible through the
Android rootfs bind namespace. It did not prove general symlink safety through
DocumentsUI or arbitrary Android app APIs. The earlier follow-up introduced
no broad permission or all-files grant. In the latest isolated BFE test, its
declared package-specific all-files access was explicitly enabled in Android
Settings and the test session was then stopped; no unrelated package was
granted that access. No host-home bind or additional filesystem mount was
introduced.

The target SDK option added to the probe builder requires an APK Signature
Scheme v2-or-newer signature for modern target installation; legacy v1-only
signing is rejected by this Android 16 image. The generic runner APK install
option uses a read-only bind and ordinary `pm install`, and does not confer
system privileges.

### Status at the 4423 continuation

- Shared-storage core: **PASS** (previous controlled acceptance).
- Hardening and real-application compatibility: **PARTIAL/OPEN**.
- Overall shared-storage integration: **PARTIAL/OPEN**.
- Canonical M4: **PARTIAL/OPEN**.

Open storage gates include exposing MediaStore scan control in ordinary
sessions, resolving the observed startup ACL failure before app-created
directories are relied on from Linux, BFE archive validation, full frame and
decoder behavior for the real media apps, and fuller NTFS3 quota and symlink
characterization. The target-SDK 35 SAF read/write and app-process grant
checks, active-session diagnostic scan, and VLC/mpv document reads described
above are now verified. Canonical M4 also separately retains audio, clipboard,
notifications, and launcher-catalog work.

## Normal-session storage continuation (2026-11-04)

The implementation tested from source HEAD `f85620479bd9aefa89eb120ef67d85a822b89aa6`
extends the explicit MediaStore scan path to every ordinary AaaS runtime
session. Startup builds and installs the small ordinary package
`org.aaas.storagescan` from a pinned source/build receipt. It has no launcher
activity or UI, is installed in `/data/app`, and exposes only a receiver
protected by Android's `DUMP` permission. AaaS shell requests one validated
shared-storage file at a time; the helper calls public
`MediaScannerConnection.scanFile`, and the host control path waits for the
scan callback and verifies the returned media URI through a MediaStore query.
`storage sync` remains ACL repair; `storage scan RELATIVE_PATH` is indexing.
The helper is session-owned and is not a resident watcher.

Ordinary session `m1b84_session_298kqwff` showed user 0 system-unlocked and
`external_primary` attached. In that uninterrupted runtime, the scan command
and actual MediaStore query verified PNG create and update, rename (new row
present and stale old row absent), and delete (row absent). Synthetic WAV and
MP4 files also received external-primary audio/video URIs. The helper APK
SHA-256 is `89b9a7261e5550988b5fee39afd6b1e2e2d7b42b14a14001fe1e9ae593708c41`;
the session logcat SHA-256 is
`44e8b220f4db72b87d471508f36a1962ea581a7cd896d868709ae00a1c27e7c5`.
Traversal, absolute, and symlink-containing requests are rejected by host-side
validation. A stopped-runtime request fails with an explicit missing-session
error. No Android restart or continuous polling was used.

The previous ACL setup used `unshare -U -m -f` but attempted to write UID/GID
maps for the parent PID, which is outside the newly-created namespace; the
host rejected that `newuidmap` operation with `EPERM`. The storage ACL helpers
now keep the unshare process itself in the namespace (`-f` removed), wait for
its UID map to remain uninitialized, and then apply the existing narrow map.
Storage preparation remains before Android application launch and the runner
fails startup if its ACL preflight does not return ready. A fresh isolated
backing-root preparation passed with host-user named/default ACLs, mapped
`media_rw` group/default-group write/search permissions, and mode-0700
`Android/data` and `Android/obb`. In ordinary BFE session
`m1b84_session_vp7oizek`, the command log contains
`AAAS_STORAGE_ACL_PREFLIGHT_READY`; no manual `storage sync` was needed. BFE's
new public directory inherited the host ACL. The session logcat SHA-256 is
`94936f11d3235a3613e9cabbdd07a633fa586089ce39b06e8a35bf46bab70316` and the
command log SHA-256 is
`7a01fbd619365910189f440ebb23f3c56d8a5ff2ca46ccf39a3ff4a270d01e0e`.

With BFE's declared all-files setting explicitly enabled only for that test
package, its real UI created a directory and files, renamed, copied, and moved
disposable entries; Linux observed the directory operations and ACLs. A
separate BFE text-editor operation wrote
`AaaS_BFE_20261104/bfe-renamed.txt`; Linux read 40 bytes with SHA-256
`4e0d7df02f4e803b72d093a938c69631201783fbc603cb8d1672ea0fb48796ab`.
Current-session create/copy/move file entries were empty, so they establish
entry operations, not non-empty copy/move data integrity. The Compress action
was attempted but no archive output was verified. BFE's full archive gate
remains open.

At the time of this historical run, the SDK 35 SAF grant was proven across app
force-stop/relaunch only and `/data` was session-ephemeral. The
persistent-userdata continuation below supersedes that limitation for the
tested package and URI.

The NTFS3 project-quota xattr warning remains nonfatal in MediaProvider logs.
A fresh isolated backing on NTFS3 successfully initialized the ACLs, accepted a
write as mapped `media_rw` UID/GID `101022:101022`, and allowed a byte-exact
Linux read without `storage sync` (SHA-256
`c8890468d92938d191adf87325f1f318211ce5ad605197c484013d23e324ef9d`). The
test root was removed. This validates ACL inheritance on NTFS3, not Android
StorageStatsManager accuracy, project-quota enforcement, app-specific
accounting, or low-space behavior.
The expanded Android app/SAF symlink matrix and BFE archive output are also
unverified. The previously recorded VLC and mpv storage reads remain valid;
visible frame presentation is not required for storage and was not established
here. These limits keep **M4 shared-storage integration PARTIAL/OPEN** even
though its core remains **PASS**. Canonical M4 remains `PARTIAL/OPEN`.

### Remount and ACL recovery follow-up (2026-11-05)

After the external NTFS3 volume was remounted, `android-media` retained its
mapped `media_rw` owner but no longer had an effective host-user ACL. The
normal `storage sync` helper could not reach the child path because it tried
to resolve it through host-private ancestors as the mapped identity. The
repair now bind-mounts only the exact shared-media directory into a disposable
rootless mount namespace, applies the ACL as its mapped owner, and tears the
namespace down. It does not add access to sibling userdata. A new rootless
fixture test and a live `storage sync` both pass; live `storage status` reports
`host_acl_ready=true` and `host_accessible=true`. Host list/read/write checks
for `Android/data` and `Android/obb` remain denied.

The remounted volume is not safe for Android runtime testing: the kernel marks
NTFS3 volume `/dev/sda2` dirty, recommends `chkdsk`, and logs MFT sequence
mismatches (the cause is not independently established). Two disposable files
from the interrupted test session return `EINVAL` even on `lstat` and cannot
be unlinked. No filesystem repair or mount-option change was attempted.
Consequently the workspace
guard fails while accounting those entries. Android remains stopped; no
runtime restart, BFE archive operation, or live persistence test was attempted
against the damaged volume. The current code can repair the ACL, but overall
storage acceptance remains `PARTIAL/OPEN` pending filesystem repair and a
fresh workspace-guard pass.

### Android private-data path and SQLite validation (2026-11-05)

The ordinary target-SDK 35 probe observed that its `/data/user/0` and
`/data/data` package paths resolve to the same device/inode in the application
namespace. Mountinfo shows Android's per-user and per-package binds from the
persistent userdata tree; neither app data duplication nor an AaaS-created
symlink was found. The probe's private files, cache, device-protected file,
app-specific external file, and Android SQLite WAL database survived clean
runtime restarts. A same-signed PackageManager update from version 1 to 2
retained UID 10150 and its committed database rows. Exact details and digests
are in [persistent-userdata documentation](android-persistent-userdata.md).

This follow-up does not close app-to-app isolation, Android runtime permission
revocation, SAF URI grant revocation, StorageStatsManager accounting, full
symlink behavior, or BFE archive testing. The external workspace volume
became unavailable during a BFE run; that run is excluded from archive
acceptance and the broader shared-storage classification remains
`PARTIAL/OPEN`.

## Persistent-userdata reliability continuation (2026-11-04)

The workspace accounting helper was corrected to wait for the target user
namespace to be created and to verify PID start time and namespace identity
around UID/GID map writes. A post-fix sample passed 10 sequential and 4
concurrent checks, followed by 3 sequential and 4 concurrently traced checks;
all 28 mapping-helper calls succeeded. The isolated prior `newuidmap EPERM`
was not reproduced. See the [userdata reliability record](android-persistent-userdata.md)
and the new `userdata_reliability_continuation` evidence in
[`acceptance.json`](../../results/m4/acceptance.json).

A separate bounded Linux SQLite probe on NTFS3 exercised committed WAL data,
checkpointing, a killed writer with spilled uncommitted WAL frames, integrity
checks, and a subsequent committed transaction. It passed for the host SQLite
VFS; it does not stand in for SQLite running inside an Android application.
Actual Android database/WAL persistence, runtime permissions, package update
and uninstall, app-specific storage, URI revocation, BFE archives, and the
expanded symlink matrix remain open. The stopped userdata tree also reveals a
path question: PackageManager records `/data/user/0` for the probe, while the
persisted preference is physically present under `/data/data` and the stopped
`data/user/0` is empty. A live Android mount/alias inspection is still needed.

## Persistent Android userdata continuation (2026-11-04)

The runtime previously mounted a fresh tmpfs at `/data`; the host shared-media
directory was the only persistent Android storage. AaaS now binds the
workspace-backed private userdata directory at `/data` and continues to bind
the existing `shared-storage/android-media` parent at `/data/media`. No shared
media is copied or duplicated. The architecture, initialization rules,
filesystem constraints, and restart evidence are documented in
[`android-persistent-userdata.md`](android-persistent-userdata.md).

The target-SDK 35 ordinary `/data/app` probe selected
`Download/000-host-read.txt` through DocumentsUI, acquired a persistable URI
grant, read it through ContentResolver, and restored/read the same URI after
two complete Android runtime restarts without reinstalling the app. Package
Manager continued to report the probe at UID 10150. Its app-private preference
file persisted with SHA-256
`42318407f9c3522c2eb608d5b254195a50201925f7ae91c4ea1c5070d4218422`. The
shared fixture SHA-256 was
`4a077084728a18f2627f1f67d48820de9a0aea0e8b14179d1f704b5707b89213`.

This accepts persistence for the package, UID, probe preference, and the tested
SAF grant/read path. It does not yet characterize app database, package update
and uninstall, runtime-permission persistence, cache handling, or
app-specific external storage. NTFS3 still rejects SELinux-label and
project-quota xattrs; quota/statistics accuracy is open. The expanded symlink
matrix and BFE archive operation are also open. Therefore the persistent
userdata slice is accepted, while the broader shared-storage integration and
canonical M4 remain `PARTIAL/OPEN`.

## Post-Windows-CHKDSK recovery validation (2026-11-05)

The workspace owner reports running Windows `chkdsk` and cleaning the volume.
Afterward, the mounted filesystem was NTFS3 UUID `A2ACEDF2ACEDC0C1`, read/write
with the expected ACL options. The two known disposable interrupted-run
entries that previously returned `EINVAL` were absent. Five consecutive full
workspace checks passed; the latest check measured 60,027,287,040 bytes used
and 310,746,660,864 bytes available against the 80 GiB ceiling and 20 GiB
reserve. No new NTFS3 MFT or block-I/O errors were observed after remount.
This validates the current workspace for bounded testing; it does not claim
that AaaS independently performed or audited Windows repair.

In normal sessions, `storage scan RELATIVE_PATH` completed after a host PNG
create and an in-place image update, and MediaStore returned the expected
`external_primary` row and `/storage/emulated/0/Pictures/...` path. The scan
also succeeded after a complete runtime restart. Absolute, traversal, and
symlink-containing scan paths were rejected. The synthetic files were removed
after their sessions stopped. Host ACL status remained ready and accessible.

After repair, the existing Android userdata probe survived a full runtime
restart with its prior PackageManager UID, internal/cache/external/device-
protected file digests, and 102-row Android SQLite database intact. A fresh
Settings/Contacts regression used independent displays; Contacts closed while
Settings remained running, and both presenters finished with balanced
imports/releases and zero outstanding buffers. A fresh M3 diagnostic returned
`PASS mask=255`; the diagnostic overlay was removed at session teardown.

The original BFE package launched in a recovered runtime, but this execution
did not perform its archive UI workflow. A second attempt in session
`m1b84_session_4k_hci4f` again launched `com.the412banner.bfe/.icon.M5` and
stopped cleanly, but the active CUA inventory returned no Android app windows,
so archive creation/extraction could not be driven or verified. Its logcat
SHA-256 is recorded in the new acceptance run. Package uninstall/reinstall,
runtime-permission revocation, SAF-grant revocation, cross-app private-data
isolation, Android StorageStatsManager accounting, and the full Android-facing
symlink matrix remain unverified. The storage workstream therefore remains
`PARTIAL/OPEN`. See the post-CHKDSK record in
[`results/m4/acceptance.json`](../../results/m4/acceptance.json).

## BFE window and archive follow-up (2026-11-05)

The earlier `apps=[]` result was an automation-inventory limitation, not proof
that BFE lacked a window. In live session `m1b84_session_uubpwbys`, the AaaS
control endpoint listed BFE in slot 1; Android task/window state showed
`com.the412banner.bfe/.icon.M5` on display 2 as visible and focused. KWin
reported an active, non-minimized Wayland toplevel titled
`AaaS: com.the412banner.bfe` (`resourceClass=org.aaas.com-the412banner-bfe`,
presenter PID 40253), and a host screenshot showed BFE's rendered home page.
The CUA inventory exposed no `apps` entries because it did not enumerate these
presenter-backed Wayland windows. No AaaS Android-window lifecycle change was
needed to reach BFE.

The original BFE 1.4.0 APK (SHA-256
`0ec271c371a4747760b264b8beef6bce2c4cbf331b6a6386e785cbbd5ec770bd`) was
used unchanged. In session `m1b84_session_ew677222`, BFE was visible beside
Android Settings. Its package-specific `MANAGE_EXTERNAL_STORAGE` special
access was confirmed Allowed, then revoked through Settings after testing.
The BFE UI displayed the disposable host-created `known-good.zip` and source
files. Its Compress action returned to the file view with a “Compressing to
source.zip...” toast, but no archive output appeared. The Unpack Archive UI
reported its bundled `lib7zz.so` under the package's ARM64 library path as
“inaccessible or not found”; no extraction occurred. The host independently
validated the fixture ZIP (`testzip() == None`) and its member hashes before
the UI attempt. This attributes the observed extraction failure to BFE's
archive/native-library path in this runtime; the precise loader boundary
remains unisolated, so archive compatibility is `PARTIAL`, not PASS. No
traversal payload was extracted. The exact disposable fixture tree was removed
after Android stopped.

The Settings session `m1b84_session_lkcrtzq5` confirmed BFE's all-files access
toggle was off before clean runtime shutdown. Logcat hashes and session
references are recorded in the 2026-11-05 continuation in
[`acceptance.json`](../../results/m4/acceptance.json). At the time of this BFE
archive attempt, package uninstall/reinstall, runtime-permission lifecycle,
SAF grant revocation, and cross-app private-data isolation had not yet been
tested. Later continuations verified the package lifecycle, SAF grant release,
and a bounded cross-app path boundary; runtime permissions and the complete
Android-facing symlink matrix remain open. Shared-storage integration remains
`PARTIAL/OPEN`.

### Package isolation, lifecycle, and loader follow-up (2026-11-05)

The controlled package lifecycle was completed with normal PackageManager
operations: v1-to-v2 update retained UID `10153` and the accepted 102-row
database; uninstall returned `Success`; a full restart confirmed the package
and its data path absent; reinstall created a fresh 101-row v1 database at a
new inode. The package was uninstalled again after the private-data isolation
test. App B (UID `10154`) could not resolve App A's internal, database, or
device-protected paths in its own Android mount namespace (`ENOENT` for each);
subsequent launch of A matched its private-file and SQLite digests. This is
positive evidence for the tested package boundary, while the NTFS3 development
profile still lacks stock SELinux labeling and fscrypt/FBE.

The SDK 35 probe reported `getExternalFilesDir(null) == null` despite a mounted
emulated volume and successful `StatFs` queries. StorageStatsManager returned
`app=53248`, `data=16384`, `cache=0` around tiny test files, so exact per-package
accounting and app-specific external-storage behavior remain open. Android
quota-xattr errors remain an accounting/feature limitation unless a concrete
write or isolation failure is demonstrated.

The BFE APK's `lib/arm64-v8a/lib7zz.so` is present in the unchanged original
APK (2,552,840 bytes), and `readelf` identifies it as ELF64 AArch64. Its dynamic
section needs `liblog.so`, `libc.so`, `libdl.so`, `libc++_shared.so`, and
`libm.so`; the same APK includes ARM64 `libc++_shared.so`. It also declares a
Termux-style RUNPATH (`/data/data/com.termux/files/usr/bin/../../usr/lib`). No
runtime linker trace for this library was captured, so the prior BFE message
that it is inaccessible/unavailable does not yet prove a Berberis or AaaS
loader failure. Archive create/extract remains unverified and BFE-specific.

Normal sessions previously had an evidence-channel defect: generated Android
shell commands wrote to `/aaas_session_commands`, but the host session's
`commands.log` was bound only for experimental virtual-display sessions. The
runner now binds the command log in every session and always supplies its path
to the generated runner. A normal-session uninstall recorded its success in
`commands.log`, and a following full restart recorded
`AAAS_USER_APK_ABSENCE_OK`. This repairs observability and makes lifecycle
failure checks auditable; it does not itself change Android storage behavior.

Runtime permission request/revocation, a complete Android FUSE/DocumentsUI
symlink matrix, and exact NTFS3 package accounting remain unverified. The
previously persisted SDK 35 SAF grant was explicitly released, a read of the
still-existing host fixture was denied with `SecurityException`, and the
denial plus empty persisted-grant list survived a complete runtime restart.
See the distinct live test sessions and hashes in
[`acceptance.json`](../../results/m4/acceptance.json); overall storage
integration remains `PARTIAL/OPEN`.
