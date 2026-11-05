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

That path question was resolved by the live app-namespace inspection recorded
below; the earlier statement is retained as a historical observation.

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

## Android app-data and SQLite follow-up (2026-11-05)

The target-SDK 35 probe was extended to log Android `Context` paths and
mountinfo, create private files, and exercise Android's `SQLiteDatabase` API.
The exact v1 APK SHA-256 was
`df4d9b87d0cd0360d56ff66c604faa3ad8df018f0920c8b294ebc0be9725d9d6`; the
same-signed v2 update APK SHA-256 was
`2bd267c4ccbd1b546f4bc4051540e927f703d9acd325c19d8a6db8852747dcc9`. Both
were target SDK 35 and passed `jarsigner -verify`; v2 used versionCode 2 and
versionName 2.0. The probe was an ordinary installed `/data/app` package.

In Android app process `org.aaas.storagetest` (UID 10150), `Context.getDataDir()`
reported `/data/user/0/org.aaas.storagetest`, while canonical resolution
reported `/data/data/org.aaas.storagetest`. `Os.stat()` on both paths returned
device 2050 and inode 273322, with UID/GID 10150. This confirms the same live
package directory, not merely matching path strings. The paths are not a
symlink alias: process mountinfo showed Android's NTFS3 bind at
`/data/user/0`, a tmpfs mount at `/data/data`, and a package-specific bind from
the persistent backing's `data/data/org.aaas.storagetest` to
`/data/data/org.aaas.storagetest`. The app-facing files, cache, database and
device-protected paths resolved to their expected package locations. Android
also returned
`/storage/emulated/0/Android/data/org.aaas.storagetest/files` for
`getExternalFilesDir(null)` after the volume became available.

The probe wrote an internal file, cache file, device-protected file, and
app-specific external file. On later full runtime starts, the app read and
matched the deterministic contents. Their SHA-256 digests (Base64-encoded by
the app logger) were respectively `9Y8q8BC3p/a7orqAL0d8BekkY3u8ZxFLWxUViAUeKMI=`,
`oSYP9jfrev0rp+LBfr8/7Be3qIDsnFUvvXvMkLZ8jCc=`,
`2UDptPpGd8MVvkytr593IaIOyMfYbtTXsz/iAKOUpTc=`, and
`Y+xXB2bqZTQbnVnRQn7v2pNSnHBYoTcNWQJswC/2hko=`. This records clean-restart
retention in this profile; it does not claim Android will retain cache after
legitimate eviction.

Android SQLite created `aaas-lifecycle.db`, schema version 1, inserted 100
deterministic records and one package-version record in a transaction, enabled
WAL, checked `PRAGMA integrity_check`, checkpointed, and closed. For v1 the
app logged 101 rows, `integrity=ok`, WAL enabled, and logical row digest
`FSl2HiBhF6/e7o1gV1Gnnfx4OptSYiCj3j0C0moycx4=`. That state matched after a
complete runtime restart. PackageManager then updated the app to v2 using the
same signing identity. Android logged installation completion, retained UID
10150, and the app's existing files and database survived; v2 added its
version-specific row, giving 102 rows and digest
`oeofMLVU0pFdinj0k8M4glVbWD8KCC+/hOd6AAZGYRI=`. After another complete
runtime restart, v2 again reported 102 rows, the same digest, and
`integrity=ok`. WAL was enabled and passive checkpoint returned busy=0. This
validates Android SQLite committed-data durability for this controlled app and
filesystem profile. An Android app process killed during an uncommitted
transaction was not tested; the earlier host-SQLite interruption test remains
separate evidence.

The active-run Android logs were held on the external workspace. That volume
became unavailable during the later BFE attempt; therefore the logs could not
be copied or hashed after the event. The observations above were captured from
the live log output during the sessions, and raw log hashes are unavailable
for this continuation. BFE's session-control files returned `EIO`; its
AaaS-owned runtime and presenter were terminated, but the archive workflow
could not complete. A small host-created ZIP fixture was left on the
unavailable workspace for safe cleanup after the volume is restored.

Package update across v1 to v2 is verified. Package uninstall/reinstall,
runtime permission grant and revocation, SAF grant revocation, app-to-app
private-data denial, Android StorageStatsManager accuracy, full symlink matrix,
and BFE archive creation/extraction remain unverified. The external workspace
was unmounted at the end of this continuation, so the workspace guard and
additional live Android tests could not be rerun. The storage integration
classification remains `PARTIAL/OPEN`.

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

### Post-Windows-CHKDSK recovery validation (2026-11-05)

The workspace owner reports that Windows `chkdsk` repaired the Homework NTFS
volume. AaaS did not run a filesystem repair utility. After the reported
repair, Linux observed the expected NTFS3 filesystem UUID
`A2ACEDF2ACEDC0C1`, mounted read/write at `/run/media/mrkus/Homework`; the
previous two test-fixture paths that had returned `EINVAL` were absent, the
full workspace guard passed repeatedly, and no new NTFS3 MFT/I/O error was
observed in the kernel log after the remount. This is sufficient to resume
bounded controlled testing, but is not an independent audit of the Windows
repair operation.

The previously installed ordinary target-SDK 35 package was not reinstalled.
It remained `org.aaas.storagetest` version 2 at UID 10150. In session
`m1b84_session_0ain8kfy`, the probe matched the existing internal-file,
cache-file, app-specific external-file, and device-protected-file digests and
reported Android SQLite `rows=102`, schema 1, WAL enabled, `integrity=ok`, and
the expected logical digest
`oeofMLVU0pFdinj0k8M4glVbWD8KCC+/hOd6AAZGYRI=`. After a complete clean
shutdown and restart using the same userdata, session
`m1b84_session_9qhmfq7v` reported the same package identity, all four file
digests, and the same database integrity and digest. This directly confirms
that the previously accepted Android state survived the external-volume
incident and post-repair runtime restart.

This continuation did not uninstall/reinstall packages, revoke runtime or
SAF permissions, or test cross-package private-data access. Those acceptance
gates remain open; the recovery run does not upgrade the overall userdata
reliability classification.

### Package lifecycle and app-private isolation follow-up (2026-11-05)

The controlled target-SDK 35 package `org.aaas.m4acceptance20261105.lifecycle`
was updated from v1 to v2 through PackageManager in prior sessions at the same
UID (`10153`); its Android SQLite database retained 102 rows, WAL mode, and
`integrity=ok`. This continuation uninstalled it through
`pm uninstall --user 0`; the host-bound session command log recorded
`AAAS_USER_APK_UNINSTALL_OK ... output=Success`. On a full runtime restart,
`AAAS_USER_APK_ABSENCE_OK` confirmed PackageManager no longer listed it and
`/data/user/0/<package>` was absent. Reinstalling the same signed v1 APK
created a new package data directory (new inode `1338801`; the previous live
directory used inode `1174451`) and the probe created a fresh 101-row v1
database with digest
`FSl2HiBhF6/e7o1gV1Gnnfx4OptSYiCj3j0C0moycx4=`. It did not restore the old
102-row state. The package was then uninstalled again and remained absent
after a complete restart. Both disposable packages used for the isolation
check were also removed through PackageManager after evidence collection.

App A (UID `10153`) wrote internal, database, and device-protected state. A
second ordinary package, App B (UID `10154`), attempted to open App A's files
through `/data/user/0`, `/data/data`, and `/data/user_de`; all attempts returned
`ENOENT`, and no private bytes were read. The paths are hidden in B's Android
mount namespace. Relaunching A in a later runtime matched the original
internal and device-protected file hashes and SQLite digest, demonstrating
that the denial did not result from loss of A's data. This verifies the tested
DAC/UID and mount-namespace boundary; the NTFS3 profile still does not provide
stock SELinux labels or Android fscrypt/FBE.

Live mount evidence from the SDK 35 app showed `/data` backed by NTFS3, Android
tmpfs mount roots at `/data/data`, `/data/user`, and `/data/user_de`, and
per-package bind mounts from persistent userdata. For the same package,
`Context.getDataDir()` returned `/data/user/0/<package>` while its canonical
path was `/data/data/<package>`; both reported device `2050` and inode
`1174451` in the pre-uninstall session. The application Context path and
canonical backing therefore agreed; no duplicate per-package tree was
observed. In the fresh reinstall, the new inode confirmed PackageManager
created new app data.

The probe's `getExternalFilesDir(null)` returned `null` in these sessions even
though `StatFs` worked on `/storage/emulated/0` and vold/FUSE was mounted. This
app-specific external-storage result remains unresolved and is not counted as
a pass. StorageStatsManager returned package totals (`app=53248`, `data=16384`,
`cache=0`) that did not precisely track the tiny private cache fixture; treat
these as approximate accounting on NTFS3, not quota enforcement or exact
allocation. Runtime permission and persisted SAF-grant revocation were not
exercised in this continuation.

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

### External-volume remount follow-up (2026-11-05)

The Homework volume became mounted again as NTFS3, but the kernel reported the
volume dirty, recommended `chkdsk`, and logged MFT sequence mismatches; the
cause was not independently established. Two
exact test-created entries from the interrupted session return `EINVAL` on
`lstat`, read and unlink. Workspace accounting therefore fails closed, and no
Android runtime was started against the volume. The shared-media ACL repair
was hardened to use an exact-directory bind in a temporary rootless mount
namespace; its isolated mapped-owner test and live `aaasctl storage sync`
passed, without changing ownership or granting host read/write/list access to
`Android/data` or `Android/obb`. This repairs shared-media reachability but
does not repair the NTFS volume or validate persistent userdata after the
remount. No repair, forced remount, or mount-option change was attempted.
Filesystem repair is required before runtime acceptance can resume.
