# Persistent Android userdata

## Status

The persistent-userdata capability is implemented and passed a bounded live
restart test on 2026-11-04. The overall M4 shared-storage integration remains
`PARTIAL/OPEN`: the controlled app's installed package, UID, app-held SAF URI
grant, and persisted URI read survived full AaaS shutdown and restart. This
does not establish persistence for every Android data class or replace the
remaining BFE archive, quota, and symlink acceptance work.

## Previous and selected topology

Before this change, `run_aaas.py` mounted a fresh tmpfs at Android `/data` for
each session. `/data` was therefore session-ephemeral. There was no existing
AaaS userdata image or persistent Android userdata tree to migrate. The
separate shared-media directory was already persistent and remains the
canonical source of Android shared media.

The runtime now uses:

```text
NTFS3 workspace
  android-userdata/data/                 -> Android /data (rootless bind)
  shared-storage/android-media/           -> Android /data/media (nested bind)
                                               /data/media/0 remains the
                                               existing canonical shared tree
```

The userdata backing is an ordinary dynamically allocated directory at
`/run/media/mrkus/Homework/aaas-workspace/android-userdata/data`. It is not a
fixed-size image and contains Android-managed package, user, system, and app
private state. The user-0 media tree is not copied into it. A schema manifest
identifies the workspace and backing. Startup refuses symlinked, separately
mounted, malformed, or unrecognized nonempty backing paths; it never adopts or
deletes unknown data. The prior `/data` was ephemeral, so first initialization
did not require a destructive migration.

The directory backing was chosen for this AaaS runtime because its existing
rootless runner can bind it without a privileged loop device or daemon, and the
runtime already uses an SELinux compatibility shim. The workspace is NTFS3:
the live runtime records nonfatal failures to set `security.selinux` labels and
project-quota metadata. This backing therefore does not claim stock Android
file-based encryption, SELinux labeling, or project-quota enforcement. The
session profile is not using the vendor ext4/fscrypt userdata mount. Replacing
it with a loop-mounted ext4 image would require mount privileges unavailable to
the current rootless design; adding a userspace ext4 mount stack has not been
justified. This is a known platform limitation, not an Android permission
bypass.

The control directory is host-user-only. Android ownership remains represented
through the existing user namespace mapping; app-private directories retain
their Android UID and restrictive modes. No host-user ACL is added to private
userdata. `aaasctl storage path` continues to return only the shared-media
directory. The workspace accounting code excludes private userdata from its
ordinary host walk and uses a short-lived, read-only mapped namespace to sum
allocated blocks without changing permissions. It exits before Android starts.

## Runtime lifecycle

First start creates an empty `data/` backing and atomically writes
`.aaas-userdata.json`. Later starts validate that marker and bind the same
directory at `/data`. The existing `/data/media` bind is applied after the
parent `/data` bind, so Android sees the already accepted shared-media tree,
not a duplicate copy. Normal vold/FUSE setup still exports
`/storage/emulated/0`; MediaProvider and the normal-session scan helper remain
unchanged.

Normal teardown stops the runtime and removes only session-owned mounts and
processes. It does not delete userdata or shared media. A later session reuses
PackageManager and app state. If startup encounters invalid backing metadata,
it fails closed and points to the preserved path for inspection.

## Live validation

The target-SDK 35 `org.aaas.storagetest` APK was built from the committed probe
source, signed with the existing apksig 8.9.1 path, and installed as an ordinary
`/data/app` package. APK SHA-256:
`cfa73b5518fd243b9675466ffa535192a2214b5344db6e62467618e4a3dfaa95`.

In session `m1b84_session__xj23_fw`, the app selected the host fixture through
DocumentsUI, acquired a persistable URI grant, and read it via ContentResolver.
The URI was
`content://com.android.externalstorage.documents/document/primary%3ADownload%2F000-host-read.txt`.
The fixture SHA-256 was
`4a077084728a18f2627f1f67d48820de9a0aea0e8b14179d1f704b5707b89213`.
The session log contains `ANDROID_PERSISTED_GRANT_OK` and
`ANDROID_SAF_READ_OK`.

Two later sessions (`m1b84_session_s4y4nm2a` and
`m1b84_session_8zb_k85d`) started without reinstalling the probe APK. Both
logged `ANDROID_PERSISTED_URI_READ_OK` after the app restored the URI from its
own persisted preferences and reopened it through ContentResolver. Package
Manager's persisted `packages.list` records
`org.aaas.storagetest 10150 ... /data/user/0/org.aaas.storagetest` in both
runtime logs; the final persistent record assigns UID 10150. The app-private
preference file is present in persistent userdata (SHA-256
`42318407f9c3522c2eb608d5b254195a50201925f7ae91c4ea1c5070d4218422`). The
stopped backing contains it at
`data/data/org.aaas.storagetest/shared_prefs/aaas-storage.xml`, owned by UID/GID
10150 with mode 0660; the package directory is owned by 10150 with mode 0700.
PackageManager's `packages.list` records `/data/user/0/org.aaas.storagetest`,
but the stopped backing's `data/user/0` directory was empty. The app's actual
Android path alias or mount relationship between those locations needs a live
namespace inspection. This discrepancy does not negate the observed
ContentResolver read after restart, but it limits the on-disk topology claim.

The package, UID, preference, and probe's persisted URI read survived full
runtime restarts. This does not yet test Android-app SQLite, package
update/uninstall, runtime-permission persistence, cache semantics, or
app-specific external storage.

The persistent directory had 15,368,192 allocated bytes at measurement time,
with no logical image limit. The workspace guard reported 59,411,469,824 bytes
used, 311,461,781,504 bytes available, an 80 GiB workspace ceiling, and a 20
GiB reserve. These are observed values, not fixed capacity promises. The
manifest SHA-256 is
`daf5c164d028b49ceedce692589a942034e207bd3ba89083264b6ebad6440ccd`.

The app URI grant was not separately revoked in the live session; revocation
semantics remain unverified. The persisted preference is test data only.

## Known limitations and recovery

### Rootless namespace accounting follow-up (2026-11-04)

The previous workspace-accounting helper treated any nonempty
`/proc/<pid>/uid_map` as readiness. That can be the inherited parent mapping
while `unshare` is still transitioning. The helper could therefore invoke
`newuidmap` before the target had entered its new user namespace, consistent
with the observed isolated `EPERM`. It now waits for the target user-namespace
inode to differ from the caller, verifies target PID start time and namespace
identity before and after each mapping write, and validates the resulting
UID/GID maps. It fails closed and adds no retry loop.

After the correction, 10 sequential and 4 concurrent workspace checks passed;
all 28 mapping-helper invocations succeeded. A further traced sample passed 3
sequential and 4 concurrent checks and recorded target PID, start ticks, user
and mount namespace inodes, maps before/after, helper status, and duration in
`/run/media/mrkus/Homework/aaas-workspace/tmp/userns-accounting-postfix-20261104.jsonl`
(SHA-256 `7a9fce4fcfc1e2c2eab801a3b3c13a1f5acc15a4e1642c53ab46cf4b822e8d80`).
The isolated `EPERM` has not recurred since the readiness fix; this bounded
sample does not prove the host helper can never fail.

### NTFS3 SQLite compatibility probe

A bounded Linux-host SQLite VFS probe on NTFS3 committed 100 deterministic
records in WAL mode, observed a 12,392-byte WAL, checkpointed it, then ran a
separate transaction that spilled 4,614,432 bytes of uncommitted WAL frames
before terminating only that disposable writer process. Reopening the test
database returned `integrity_check=ok`, retained the committed row, and
discarded the uncommitted rows. A subsequent transaction committed and
reopened with 101 rows and `integrity_check=ok`; row digest
`cd4cc2cb2ac15d48759c0ef4d3aa651224f5a1f29615cf551c48c620afb6fd42`.
Temporary database files were removed. This tests host SQLite filesystem
semantics, not Android's SQLite implementation or actual app database
persistence. Android database/WAL restart validation remains open.

The SQLite JSON evidence SHA-256 is
`65f266df7a26a5220209278496e76ec8dc46241dc4222424013ba17d6ddb9f9d`.

- NTFS3 rejects Android project-quota xattrs and SELinux label xattrs. Ordinary
  package operation and SAF passed, but quota/statistics correctness is not
  fully characterized.
- The runtime profile does not provide stock userdata encryption or SELinux
  labels. Do not place sensitive production data in this development profile
  without a separate security design.
- A bounded symlink test established only the previously documented namespace
  case; a full Android app/SAF symlink matrix remains open.
- The BFE archive operation remains unverified.
- Workspace accounting must continue to use the bounded mapped helper because
  the host walker cannot enter app-private directories. One final-check
  invocation failed closed when `newuidmap` returned `EPERM`; five immediate
  repeated checks then passed with identical workspace accounting. The
  underlying intermittent mapping failure was not isolated, so startup remains
  fail-closed if this prerequisite cannot complete.
- There is no automatic userdata migration. Unknown nonempty unmarked data is
  preserved and rejected. Back up the workspace using the host's normal
  process before any manual migration or repair.

Raw logs remain outside Git under
`/run/media/mrkus/Homework/aaas-workspace/tmp/`; hashes and session references
are in [`results/m4/acceptance.json`](../../results/m4/acceptance.json).
