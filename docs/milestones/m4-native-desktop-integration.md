# M4 — Native desktop integration

**Status: PARTIAL/OPEN.** The lifecycle and per-user launcher slice below is implemented and live-tested. Shared-storage core acceptance remains PASS. A subsequent storage continuation enabled MediaStore reconciliation in ordinary sessions and repaired startup ACL mapping; its BFE and scan evidence is recorded below and in `results/m4/acceptance.json`. Storage integration remains PARTIAL/OPEN because runtime-restart persistence for SAF grants is unsupported by the session-ephemeral `/data`, BFE archive output is unverified, and NTFS3 quota/symlink characterization remains bounded. Canonical M4 also retains its separate audio, clipboard, notifications, and launcher-catalog gates. M4 follows the [canonical roadmap](../roadmap.md); M5 performance and M6 compositor portability remain separate.

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

The Android target-SDK 35 app's persistable URI grant was verified across
app-process restart, not full runtime restart. The current runner uses
session-ephemeral `/data`, so the PackageManager URI-grant record cannot survive
a complete runtime teardown. No userdata persistence architecture was changed.
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
