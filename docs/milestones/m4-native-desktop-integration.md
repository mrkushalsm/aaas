# M4 — Native desktop integration

**Status: PARTIAL/OPEN.** The lifecycle and per-user launcher slice below is implemented and live-tested. Shared-storage core acceptance remains PASS. Later storage continuations added ordinary-session MediaStore reconciliation, deterministic ACL initialization, and persistent Android userdata. The SDK 35 probe's app-data paths resolve to the same live package inode, Android SQLite/WAL state and package identity survive restart, PackageManager update/uninstall/reinstall passed, two controlled packages showed the tested private-path isolation, and a persisted SAF grant was released with denial preserved after runtime restart. Storage integration remains PARTIAL/OPEN because dangerous runtime-permission grant/revocation, app-specific external storage, BFE archive output, comprehensive symlink behavior, and NTFS3 quota/accounting remain open. Canonical M4 also retains its separate audio, clipboard, notifications, and launcher-catalog gates. M4 follows the [canonical roadmap](../roadmap.md); M5 performance and M6 compositor portability remain separate.

## Baseline and scope

The supported baseline is the rootless Android 16 x86_64 runtime under KWin on Wayland. Existing M2 native windows and M3's opt-in Digitalis Native Bridge remain the graphics and ARM64 paths. This implementation adds user-level desktop launchers and uses the existing two-display session controller; it does not alter the Android image or introduce a resident supervisor.

## Implemented lifecycle slice

[`scripts/aaas_desktop.py`](../../scripts/aaas_desktop.py) writes a per-user freedesktop launcher after validating the Android package ID. Its `launch` command serializes cold starts, waits for the runner's explicit `RUNNING` status, launches into an active session when available, and reuses the existing two-slot runner. A cold launch uses one preinstalled system app as a temporary second-slot bootstrap and requests its orderly app stop once the requested application is running. The helper window is released before the launcher command succeeds. `aaasctl stop-app SLOT` requests Android `force-stop` and lets the existing window lifecycle close the associated display/presenter.

## Shared-storage core and hardening status

[`docs/storage/android-shared-storage.md`](../storage/android-shared-storage.md)
documents the selected direct-directory architecture and live tests. The stable
host path is
`/run/media/mrkus/Homework/aaas-workspace/shared-storage/android-media/0`,
reported by `python3 scripts/aaasctl.py storage path`. The rootless session
binds its parent to Android `/data/media`; vold mounts the Android emulated
storage FUSE view at `/storage/emulated`. Host-created text and binary fixtures
were read through that FUSE view with exact hashes. A binary file and Linux
rename remained visible after a clean Android shutdown and a fresh runtime
start. Host access through `Android/data` and `Android/obb` was denied.

The first storage-app runs established two related blockers. Android user 0 was
`RUNNING_UNLOCKED` and CE-unlocked, while StorageManagerService still showed
`System unlocked users: []`; MediaProvider consequently had no
`external_primary`. The system-server storage handler was blocked in optional
HEVC support discovery (`MediaCodecList`) while user-unlock completion was
queued to the same handler. The session-local `services.jar` overlay now uses
a conservative `false` transcoding default and retains explicit property and
DeviceConfig overrides. The handler can then complete user unlock and attach
the external emulated volume. A second NTFS3 ACL correction grants the mapped
`media_rw` group write/search and xattr access only on the shared root/public
directories; `Android/data` and `Android/obb` remain private.

The repaired runtime was validated with an ordinary `/data/app` storage probe.
Android `ACTION_CREATE_DOCUMENT` wrote a file that Linux read back
byte-exactly; `ACTION_OPEN_DOCUMENT` returned a Downloads content URI and
ContentResolver read the host-created file byte-exactly. MediaProvider attached
and scanned `external_primary`, and the external MediaStore query returned the
fixture. The external folder tree persists and is available to Linux while
Android is stopped. See [storage design and evidence](../storage/android-shared-storage.md)
and `results/m4/acceptance.json`. The Android-to-XDG file-picker bridge remains
deferred; Android continues using its native picker and URI permissions.

The earlier target-SDK 35 picker-only attempt, unverified VLC/mpv/BFE runs, and
mount-only MediaStore evidence are preserved in the historical
`storage_hardening_follow_up` record. The latest results are appended as a
separate run in `results/m4/acceptance.json`; they do not rewrite those earlier
observations. `aaasctl storage sync` still repairs ACLs only. The new
`aaasctl storage scan RELATIVE_PATH` operation is verified in diagnostic-probe
sessions, but needs a normal-session integration before it is a general
product feature. The NTFS3 quota-xattr limitation and incomplete symlink
matrix remain open.

The current run's target-SDK 35 APK used v3 signing and completed a byte-checked
SAF open and create. Its persistable document grant survived an app process
force-stop/relaunch, not yet an Android runtime restart. During active session
`m1b84_session_r50c_zzw`, `MediaScannerConnection` reconciled a host PNG create,
update, rename, and delete with actual MediaStore queries. VLC opened and read
the selected MP4 samples through its document flow; mpv opened the SAF tree URI
and initialized its H.264 decoder/surface. Neither run established a visible
video frame. BFE created a file after its package-specific all-files permission
was explicitly enabled, but a startup `newuidmap` ACL-repair failure left its
first app-created directory inaccessible to the host until `storage sync`.
At that time, this ACL edge and diagnostic-only scan availability kept
shared-storage integration PARTIAL/OPEN. The historical run record is retained
under `latest_storage_continuation` in the acceptance JSON.

### Normal-session scan and ACL completion (2026-11-04)

Commit `81a6899` adds a generated, ordinary `/data/app` scan receiver to every
session, protected by the platform `DUMP` permission and without a UI or
presenter slot. `aaasctl storage scan RELATIVE_PATH` now waits for the Android
`MediaScannerConnection` completion callback and a MediaStore query; the
existing `storage sync` command remains host ACL repair. In normal session
`m1b84_session_298kqwff`, external-primary indexed a PNG create/update/rename/
delete sequence plus one synthetic WAV and MP4 without runtime restart. The
scanner APK SHA-256 is
`89b9a7261e5550988b5fee39afd6b1e2e2d7b42b14a14001fe1e9ae593708c41`.

The startup ACL helper no longer forks a child before `newuidmap`/`newgidmap`
targets are written. It maps the unshare process that is actually waiting for
the mapping, then the runner blocks application startup until ACL preflight
returns ready. BFE session `m1b84_session_vp7oizek` recorded the ready marker
and newly-created public directories inherited host access. BFE performed
directory/file creation, rename, copy, and move in its UI; an earlier
package-authorized BFE text operation produced a host-visible 40-byte file
with SHA-256
`4e0d7df02f4e803b72d093a938c69631201783fbc603cb8d1672ea0fb48796ab`.
The archive action did not yield a verified archive and remains open.

At the time of this historical run, the Android target-SDK 35 app's
persistable URI grant was verified across app-process restart, not full runtime
restart. `/data` was then session-ephemeral. The later persistent-userdata
continuation below supersedes that limitation for the tested package and URI.
The scanner and ACL fix passed 274 Python tests, including fresh backing-root
ACL setup. NTFS3 quota accounting and broad Android-facing symlink behavior
remain uncharacterized; the core shared-storage architecture is unchanged.

The two-output runner now keeps Android warm for a bounded idle grace period after the last managed app closes. The product default is 60 seconds and the test override is bounded to 1–3600 seconds. Any app becoming active resets the timer; the existing launch control can reuse the runtime during the grace period. This policy applies to the existing two-output session; a running Android runtime consumes resources during that interval. Fully stopped means no AaaS runner/presenter processes.

Application discovery/catalog generation, launcher cleanup on Android uninstall, and concurrent-launch race stress coverage remain open.

### Live evidence

- KWin `6.7.5`; active host session, Android 16 x86_64 existing image.
- Session `m1b84_session_jkei7jtx`: `aaas_desktop.py launch --package com.android.settings` cold-started AaaS, kept Settings in slot 1, stopped the temporary Contacts bootstrap in slot 2, and returned only after the bootstrap window reached `CLOSED` with no presenter. Session later reached `STOPPED`.
- Session `m1b84_session_ffuknl4k`: Settings and Contacts ran in separate displays/presenters. Contacts was stopped and relaunched into slot 2 while Settings remained active; Contacts was stopped again, then Settings was stopped. Both presenter summaries report imports equal releases, `outstanding: 0`, and clean shutdown. The primary presenter summary reports 245 imports/releases; the second presenter reports 132 and then 32 across its close/reopen lifetimes.
- Session `m1b84_session_62lz6xyy`: with a 3-second test timeout, closing both applications caused the runtime to log `AAAS_IDLE_STARTED`, reach `AAAS_IDLE_TIMEOUT_REACHED`, release the broker and reach `STOPPED`.
- Session `m1b84_session_of2kfbcm`: with a 5-second test timeout, both apps were stopped, Contacts was relaunched during the idle period into the same runtime, and after it was stopped the timer restarted and the runtime shut down. Both presenter streams report balanced imports/releases and zero outstanding buffers. Commands SHA-256 `a73411dc50729df3e88e0f32e6172b93f7626b74bdd97107137daf3e7d1135ef`; logcat `98e97a93e15e7266756fbeebbe13ff60f7148d8dbfc1952e720d38302223c4a7`; presenters `e7ad81f55d56eb3303e9075f77d82d008e1fb7648f0a84dbae106bbf7d5b4e6a` and `55707ad8bcd6b0558193e5c67869d58e41222baec2502c1516b9079e1a79ed11`.
- Session `m1b84_session_ueok_b7l`: two independent concurrent launcher invocations serialized; Settings cold-started one session and Contacts reused slot 2. Both presenters shut down with balanced buffers (`221/221` and `137/137`, then `34/34` on close/reopen), `outstanding: 0`. Runtime was stopped explicitly and reached `STOPPED`. Commands SHA-256 `784d288d435b3651f8175dfdb0c1bd805dc79bd9af7d44022bf0c703de8ac79a`; logcat `a38bcbad5f413d0a8ef945c16decc737b9680d5ed33f20d5f4321a25dc98b6a1`; presenters `d91810d2cee4e0672d6c229141aa0627a271f7eb2de414c40426b22923cda049` and `b08e8672814815ad519b027795ad0e29f786d53a050598e5340e792e3968fc3e`.
- Final launcher session presenter log SHA-256: `a5a4e26d7960dc4d90a55efcb3082cc74b4b4fc12414c9a0324b3a7ea0bf3954`; bootstrap presenter: `e3bb80efd5aea7d89005a310e5cf5d3f76b94db24df1a3eeb11fd4e7e5b1f65a`.
- Two-slot lifecycle session hashes: commands `fda5fecd4101e98133036667737c5138b5dadae84994b977abdda19c4b72ae6b`; logcat `38317fe39099ee758636cb3e3f39e708c1e167efbc41d39c00074eb59cf6bc85`; presenter 1 `09bce4fa56d032ae021527720b17aa802c63f461c387e62b31b09792d50aea28`; presenter 2 `37de18d643f7652ea36f08fbfb277b2131fd9c2d6b800757ba53b45688f13214`.
- M3 regression session `m1b84_session_kx_r4eqw`: existing ARM64-only diagnostic launched with the pinned overlay; Android log contains Berberis JIT translation and a successful load of `/product/app/AaasLatencyProbe/lib/arm64/libm3probe.so`. The session stopped cleanly and reported removal of the session-local Native Bridge overlay and diagnostic APK libraries. Logcat SHA-256 `4827168befbb38843ecb60811bedac373701c59eb8c77e699950b61defbebb4d`; commands SHA-256 `d78f38cb8800906ae95622d5aea565e3bc6db044d6bc5cfefea1230a0b5a2c0a`; presenter SHA-256 `de62f09b84f1a212a031d25467e6f7b2d6cdc6d5fc8985065ba4a54e60ec3597`.
- User-level Settings and Contacts `.desktop` entries passed `desktop-file-validate`; KDE application cache was refreshed. The repository includes focused tests for package validation, Exec quoting, atomic launcher creation, and stop request generation.

Raw sessions are retained under `/run/media/mrkus/Homework/aaas-workspace/tmp/`; original session logs are not copied into Git.

## Host capability audit and remaining gates

| Capability | Current evidence | M4 status |
|---|---|---|
| On-demand start and reuse | Live cold launcher start, same-session app reuse, two concurrent launcher calls, cancellable idle period and automatic idle shutdown | Partial: broader failure-recovery gates remain |
| User desktop launcher | Per-user entries and runner invocation exercised | Partial: app discovery/catalog and uninstall cleanup are absent |
| Host audio playback | PipeWire 1.6.9, WirePlumber, and pipewire-pulse are active on host. Android AudioFlinger and Ranchu audio HAL exist, but runner does not connect a host PCM endpoint or transport samples. | Not implemented; no playback proof |
| Microphone | Host audio source exists; Android runner does not expose a scoped host capture stream. | Not implemented; no authorization/revocation proof |
| Shared Android storage | Persistent backing is exposed directly to Linux and parent-bound at Android `/data/media`; vold/FUSE presents `/storage/emulated/0`. Controlled ordinary-app SAF and mount-time MediaStore tests passed. Live host mutation sync, current-target app read/write, and real-app workflows remain incomplete. | **Core PASS; hardening PARTIAL/OPEN** |
| Android-to-XDG picker bridge | This capability is explicitly deferred; Android continues using its built-in picker and shared-storage APIs. | Deferred; not a storage-slice acceptance gate |
| Clipboard | Wayland presenter has no data-device clipboard bridge to Android ClipboardManager. | Not implemented |
| Notifications | Host DBus notification service and Android NotificationManager exist, but no AaaS forwarding listener/adapter exists. | Not implemented |
| Normal APK installation | Existing acceptance used system-app overlays; no normal user PackageInstaller workflow or launcher discovery is included in this change. | Not verified |
| Camera | `/dev/video*` devices exist on host, but are not bound into Android; no Android Camera HAL to authorized host source adapter is present. | Feasibility only; not supported |
| M2/M3 regression | KWin Settings/Contacts presentation and teardown were exercised; M3 diagnostic was rerun with the full JNI PASS record in the Android log. | Partial M2 regression evidence |

The mandatory M4 acceptance gates for actual host audio playback, scoped file read and write, bidirectional clipboard, and supported Android notification forwarding remain open. Therefore this record intentionally stays `PARTIAL/OPEN`.

## Security and deferred scope

No broad host home mount or host device bind was added. No host microphone or camera stream is exposed. Camera needs a supported Android HAL/provider bridge plus host authorization; the permission dialog alone is not device support. Physical camera, Bluetooth, broad sensor access, M5 performance, and M6 compositor expansion remain outside this accepted slice.

## Verification

The historical lifecycle run passed 256 tests. On 2026-11-04, the full Python suite passed 268 tests after adding ordinary APK installation and clarifying ACL-only `storage sync` behavior. A fresh M3 Native Bridge run returned `M3 ARM64 Native Bridge PASS mask=255` with JNI values and clean shutdown. A fresh M2 smoke run placed Settings and Contacts on separate displays, stopped Contacts independently while Settings remained RUNNING, then shut down cleanly. These are smoke/regression checks, not a rerun of the full M2 acceptance. Python compilation, JSON validation, `git diff --check`, and the workspace guard passed. The final guard observed 58,693,074,944 bytes used against an 80 GiB ceiling, with 312,180,211,712 bytes free against a 20 GiB reserve. No AaaS runner/presenter processes remained after the live sessions.

### Persistent Android userdata continuation (2026-11-04)

Commit `48d05d9` replaces session-ephemeral `/data` with a persistent,
workspace-backed host directory. The old AaaS `/data` was tmpfs; no existing
userdata image or tree was migrated. The backing is dynamically allocated at
`android-userdata/data`; an atomic schema marker prevents silently adopting or
replacing unknown data. The existing shared-media bind is still mounted at
`/data/media` and remains the single canonical public-media tree. Private
userdata is not returned by `aaasctl storage path` and receives no host-user
ACL. Directory capacity is not preallocated.

Commit `4302e4f` improves the target-SDK 35 probe so the app restores its
persisted document URI from its own preferences. The exact signed ordinary
`/data/app` APK SHA-256 is
`cfa73b5518fd243b9675466ffa535192a2214b5344db6e62467618e4a3dfaa95`. It
selected and byte-read the host file in `m1b84_session__xj23_fw`; after complete
runtime shutdown, it launched without reinstall in sessions
`m1b84_session_s4y4nm2a` and `m1b84_session_8zb_k85d`, logging
`ANDROID_PERSISTED_URI_READ_OK` in both. Package Manager retained UID 10150.
The app preference fixture hash is
`42318407f9c3522c2eb608d5b254195a50201925f7ae91c4ea1c5070d4218422`; the
host document hash is
`4a077084728a18f2627f1f67d48820de9a0aea0e8b14179d1f704b5707b89213`.
The final active session also used the normal-session scan command and verified
the MediaStore row. Session log hashes and the userdata manifest hash are
appended in `results/m4/acceptance.json`.

The userdata directory had 15,368,192 allocated bytes at measurement time and
no fixed logical image limit. Workspace usage was 59,411,469,824 bytes with
311,461,781,504 bytes available; the 80 GiB ceiling and 20 GiB reserve passed.
The complete Python suite passed 280 tests. This continuation did not rerun a
full M2/M3 campaign; earlier M2 smoke and M3 JNI `PASS mask=255` evidence
remain historical and unchanged. Runtime sessions were stopped and no AaaS
process remained.

The persistent directory-backed `/data` is verified for the tested PackageManager
record, stable package UID, app preference, and SAF persisted-URI read across
runtime restart. Reliability acceptance remains open: Android-app SQLite,
runtime permissions, package update/uninstall, app-specific external data, and
URI revocation were not exercised. NTFS3 does not provide the tested
SELinux-label or project-quota xattrs; the runtime profile does not claim stock
Android userdata encryption. BFE archive output and the complete symlink/
security matrix remain open.

Commit `9447113` fixes a readiness race in the private-userdata accounting
helper. Previously it treated any nonempty UID map as proof that the helper had
entered its new user namespace. It now waits for the user-namespace inode to
change and verifies process start time and namespace identity before and after
UID/GID mapping. The prior single `newuidmap EPERM` did not recur in 21
post-fix checks (10 sequential + 4 concurrent, then 3 sequential + 4 traced
concurrent); all 28 helper calls in the traced sample succeeded. The failure
was not reproduced, so the code retains a bounded, fail-closed path without
retrying permission errors. Trace hash and sample details are in
`results/m4/acceptance.json`.

A Linux-host SQLite probe on NTFS3 passed WAL commit, checkpoint, bounded
uncommitted-WAL interruption/recovery, and integrity checks. At that time this
was not validation of Android app SQLite; the 2026-11-05 follow-up below adds
that live evidence. The earlier stopped-tree observation that
`packages.list` names `/data/user/0` while the preference physically resides
under `/data/data` is resolved by the live bind/path evidence recorded below.
The 2026-11-04 full Python suite now passes 281 tests. No fresh M2/M3 campaign
was run during this continuation; prior regression records remain historical.
Shared-storage integration and canonical M4 remain `PARTIAL/OPEN`.

### Android userdata reliability follow-up (2026-11-05)

An ordinary target-SDK 35 app logged the live `/data/data` and `/data/user/0`
relationships. Both package paths had device 2050/inode 273322 and resolved to
`/data/data/org.aaas.storagetest`; mountinfo shows the expected `/data/user/0`
and package-private binds from persistent userdata. The probe created an
Android-native SQLite database using the Android API, enabled WAL, and checked
`integrity_check`. Version 1 retained 101 deterministic rows across a complete
runtime restart; PackageManager updated the same-signed app to version 2 at
the same UID (10150), preserving its app files and adding the expected version
row; the 102-row database and digest survived another complete runtime
restart. Internal, cache, device-protected, and app-specific external files
were also read and matched after restart. This advances persistent userdata
correctness but does not test interrupted Android transactions, permissions,
SAF grant revocation, or package uninstall/reinstall.

The follow-up built commits `1fb6668` and `eb8cfec`, which add the controlled
Android private-data/SQLite probe and skip the single-instance lock unit test
when its external workspace mount is absent. The full Python suite then ran
281 tests successfully with 7 skips; no fresh full M2/M3 campaigns were run.
The workspace volume disappeared during the subsequent BFE archive attempt.
Its session returned `EIO`, so the archive attempt is excluded and the
workspace guard could not be rerun. The session's AaaS-owned container and
presenter processes were terminated; only a bounded follow-up after the
workspace is available can complete the remaining filesystem, security, and
archive acceptance. Canonical M4 remains `PARTIAL/OPEN`.

### External-volume remount follow-up (2026-11-05)

After the volume was mounted again, `storage sync` initially failed because the
mapped media owner could not resolve the shared-media path through host-private
ancestors. The ACL repair now bind-mounts only the target directory into its
temporary rootless mount namespace. A mapped-owner fixture and the live
`storage sync` pass; `storage status` reports host ACL/access ready, and
`Android/data`/`Android/obb` remain unreadable and unwritable to the host user.

The live NTFS3 volume is marked dirty and the kernel reports MFT sequence
mismatches; cause was not independently established and no filesystem repair
was attempted. Exact disposable PNG/ZIP fixtures from the interrupted run return
`EINVAL` on metadata access and cannot be removed. The workspace guard fails
closed while accounting them, so Android was not restarted and BFE/SAF live
tests were not attempted. Storage integration remains `PARTIAL/OPEN`; repair
the filesystem and rerun the workspace guard before resuming live acceptance.

The mapped-owner ACL recovery was committed as `868bbe8` and verified by the
focused storage tests and live ACL/status commands. The complete Python suite
then ran 282 tests successfully with one skip: its workspace-dependent lock
test skips when the real workspace guard is unhealthy. The guard itself still
fails on the NTFS3 `EINVAL` entry, and this skip does not certify workspace or
runtime health. No AaaS runtime, presenter, session-control, bwrap, or ACL
helper process remained after verification.

### Post-Windows-CHKDSK recovery validation (2026-11-05)

The workspace owner reports repairing the Homework volume with Windows
`chkdsk`. AaaS did not run or modify the filesystem repair. Following that
repair, the expected NTFS3 UUID was mounted read/write, prior corrupt test
fixtures were absent, five consecutive full workspace checks passed, and no
new MFT/NTFS3/block-I/O errors appeared in the kernel log after remount. The
current workspace is classified `HEALTHY_FOR_CONTROLLED_TESTING`; this does
not independently certify the Windows repair beyond the observed Linux
checks.

The existing SDK 35 app remained installed at UID 10150 after the incident.
Its private files retained their expected digests, and Android SQLite again
reported 102 rows, the expected logical digest, WAL enabled, and
`integrity=ok` both before and after a complete AaaS restart. Normal-session
MediaStore scanning returned actual `external_primary` rows for a host-created
PNG before and after restart; update of the first PNG was also reflected by a
successful scan/query. Invalid absolute, traversal, and symlink paths were
rejected.

Fresh regression checks passed: Settings and Contacts occupied independent
displays, Contacts closed without stopping Settings, and presenter counts
balanced (124/124 and 88/88 releases, zero outstanding). The M3 JNI diagnostic
returned `PASS mask=255`; its session overlay was cleaned. The full Python
suite passed 284 tests with no skips. BFE launched as an ordinary package but
its archive UI flow was not completed. A second BFE session again launched
its Activity and stopped cleanly, but the active CUA inventory exposed no
Android app windows, preventing the required archive UI actions. Package
uninstall/reinstall,
permission and SAF-grant revocation, cross-app private-data isolation,
StorageStatsManager accounting, and the full Android-facing symlink matrix
remain open. The new bounded active-session workspace identity check is in
commit `1250f46`; it was exercised through healthy sessions and unit-tested for
mount/sentinel loss, but an actual unmount was not injected. Overall storage
integration and canonical M4 remain `PARTIAL/OPEN`.

### BFE window and archive follow-up (2026-11-05)

The BFE `apps=[]` observation came from the CUA app inventory: Android showed
the package activity as visible/focused and KWin showed its active presenter
Wayland window. No Android activity or presenter-discovery defect was found in
AaaS. The original BFE APK was exercised through its visible UI with its
package-specific all-files access temporarily enabled and then revoked. BFE's
Compress action produced no file; its Unpack Archive screen reported the
bundled ARM64 `lib7zz.so` as inaccessible/unavailable while opening a valid
host-verified ZIP. This is an application archive/native-library compatibility
limitation, not evidence of a shared-storage read failure. Archive
creation/extraction therefore remains unaccepted. App uninstall and reinstall,
permission/grant revocation beyond the BFE special access, app isolation,
accounting, and Android-facing symlink tests also remain open. See the distinct
continuation record in [`results/m4/acceptance.json`](../../results/m4/acceptance.json).

### Android package lifecycle and private-data boundary (2026-11-05)

The target-SDK 35 lifecycle package completed a normal v1-to-v2 update, clean
PackageManager uninstall, absence check after a full runtime restart, and
reinstall. UID `10153` was retained across the update; reinstall created a new
private-data inode and fresh 101-row v1 SQLite state rather than restoring the
old v2 state. App B at UID `10154` could not resolve App A's internal,
database, or device-protected paths (`ENOENT`) in its own Android mount
namespace. Relaunching A later matched its internal/device-protected hashes
and database digest. These are bounded positive results for package lifecycle
and the tested cross-app path boundary.

The SDK 35 probe still reports `getExternalFilesDir(null) == null`; runtime
permission grant/revocation, comprehensive symlink behavior, and precise
storage accounting remain open. The original BFE archive
library is confirmed present as ELF64 AArch64 in the unchanged APK, but no
runtime loader trace exists yet; compression/extraction remain unverified.
Shared-storage integration therefore remains `PARTIAL/OPEN`, and canonical M4
remains `PARTIAL/OPEN`.

### Fresh M2/M3 smoke after session-command logging fix (2026-11-05)

M3 session `m1b84_session_zk8m89a7` ran the pinned Digitalis/Berberis overlay
and emitted `M3 ARM64 Native Bridge PASS mask=255` with the expected JNI values;
the session stopped cleanly. M2 session `m1b84_session_020f0vqp` opened Settings
and Contacts in separate native windows. Closing slot 2 left Settings running.
At shutdown, the Settings presenter reported 92 imports/92 releases and zero
outstanding buffers; the Contacts presenter reported 64/64 and zero
outstanding. These are focused smoke regressions, not a full M2 acceptance
campaign. The Python suite passed 287 tests with no skips.

### Persisted SAF permission release (2026-11-05)

In session `m1b84_session_wpjfuelb`, the SDK 35 package released its persisted
read/write grant for the existing host fixture through Android's
`ContentResolver.releasePersistableUriPermission`; an immediate read failed
with `SecurityException`. After a full AaaS runtime restart,
`m1b84_session_gepio2q7` observed no remaining persisted grants and another
read of the same existing URI failed with `SecurityException`. The storage
fixture still existed throughout. Runtime dangerous-permission grant and
revocation, Android-facing symlinks, app-specific external storage, and exact
NTFS3 per-package accounting remain open; storage integration remains
`PARTIAL/OPEN`.

The final focused run after adding the persisted-grant revocation regression
passed 288 Python tests with no skips.
