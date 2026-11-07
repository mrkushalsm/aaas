# M4 — Native desktop integration

**Status: PARTIAL/OPEN.** M2 lifecycle, M4 storage, installed-app catalog/launcher, bidirectional clipboard, and Android notification forwarding have accepted evidence. **M4 Storage Integration is PASS/CLOSED** in the 2026-11-06 continuation below. **Installed-App Catalog and Launcher Integration is PASS/CLOSED** in the 2026-11-06 launcher continuation. **Bidirectional Clipboard Integration is PASS/CLOSED for bounded UTF-8 text on KWin** in the [clipboard integration record](../m4-clipboard-integration.md). **Android Notification Forwarding is PASS/CLOSED** in the [notification integration record](../m4-notifications.md). BFE's archive actions remain an application-specific compatibility limitation; its ordinary shared-file operations are separately verified. Canonical M4 remains open for host audio and microphone. M4 follows the [canonical roadmap](../roadmap.md); M5 performance and M6 compositor portability remain separate.

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

At the time of this historical baseline, application discovery/catalog generation and launcher cleanup on Android uninstall were open. The dated installed-app catalog continuation below supersedes that status; concurrent-launch stress coverage remains separate.

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
| User desktop launcher | PackageManager discovery, icon/label/version catalog, owned XDG entries, cold launch, runtime reuse, update reconciliation, and uninstall cleanup verified in the 2026-11-06 continuation | **PASS/CLOSED** for installed-app catalog and launcher integration |
| Host audio playback | An opt-in session-local legacy HAL, Android AudioTrack probe, and PipeWire null-sink capture were exercised live. A 440.009 Hz signal crossed the full path. | PARTIAL/OPEN; ordinary media-app playback, controls, concurrency, and host-failure behavior remain unverified |
| Microphone | An ordinary target-SDK 35 app received `RECORD_AUDIO` through Android's UI; AudioRecord samples from a controlled PipeWire source matched a 440 Hz signal after runtime restart. | PARTIAL/OPEN; revocation, physical input, app interaction, and disconnect behavior remain unverified |
| Shared Android storage | Persistent backing is exposed directly to Linux and parent-bound at Android `/data/media`; vold/FUSE presents `/storage/emulated/0`. Ordinary-app SAF, active MediaStore reconciliation, ACL preflight, persistent userdata, app-specific external files, permissions, and security boundary tests pass. NTFS3 quotas/SELinux labels/fscrypt are unsupported profile features; BFE archive actions are application-specific. | **PASS/CLOSED** |
| Android-to-XDG picker bridge | This capability is explicitly deferred; Android continues using its built-in picker and shared-storage APIs. | Deferred; not a storage-slice acceptance gate |
| Clipboard | Historical capability audit before the 2026-11-06 clipboard implementation. | Superseded by the live acceptance below |
| Notifications | Host DBus notification service and Android NotificationManager exist, but no AaaS forwarding listener/adapter exists. | Not implemented |
| Normal APK installation and launcher discovery | The 2026-11-06 launcher continuation installed, updated, discovered, launched, uninstalled, and reconciled a disposable ordinary package through PackageManager and managed XDG entries. | **PASS/CLOSED** for installed-app catalog and launcher |
| Camera | `/dev/video*` devices exist on host, but are not bound into Android; no Android Camera HAL to authorized host source adapter is present. | Feasibility only; not supported |
| M2/M3 regression | KWin Settings/Contacts presentation and teardown were exercised; M3 diagnostic was rerun with the full JNI PASS record in the Android log. | Partial M2 regression evidence |

At the time of this earlier host-capability audit, audio, clipboard, and notifications were still open. The dated launcher, clipboard, notification, and audio continuations below update those findings; canonical M4 remains `PARTIAL/OPEN` for the remaining audio and microphone acceptance gates.

## Android audio and microphone continuation (2026-11-07)

This continuation resolves the earlier HAL error far enough to carry actual
samples in both directions. The original Ranchu HIDL 7.1 factory special-cases
`primary` for its emulator device instead of reaching the legacy
`hw_get_module_by_class` selection path. This rootless runtime has no working
Ranchu audio transport. A session-local bind of the image-matched AOSP legacy
HIDL factory allowed the standard module lookup to select
`audio.primary.aaas.so`. The ordinary module path then loaded the x86_64/Bionic
ELF (`module_api=1`, `hal_api=256`); `adev_open`, `init_check`, and the 48 kHz
stereo PCM16 output stream returned success.

The next blocker was the HIDL legacy FMQ's ashmem allocation: the rootless
guest has no `/dev/ashmem`, and the platform setter rejected a memfd as an
ashmem device. The session-local shim in
[`experiments/m4/audio/ashmem_compat.c`](../../experiments/m4/audio/ashmem_compat.c)
backs the limited ashmem API used by that FMQ with a CLOEXEC, NOEXEC-sealed
memfd and the corresponding size/protection seals. This is preloaded only by
the session's vendor audio service. The successful live run also used
session-only stock-compatible `audioserver` and `libaudiohal.so` overlays to
avoid the development image's incompatible audio-framework modifications;
the base image was not modified. The current workaround remains an opt-in
prototype and is not a reproducible default runtime configuration.

In `m1b84_session_2mbhio2e`, AudioPolicyManager selected the primary speaker
route and output 13. The ordinary Android `org.aaas.audioprobe` wrote 48,000
stereo frames at 48 kHz; the HAL logged a PCM callback and host-socket
connection. The PipeWire null-sink monitor captured the fixture. Its raw
capture SHA-256 is
`eead53103b2d60668afcb4390c571bceee7d3ae1eeb91ef8f59cf8b48a0cdb1c`; analysis
found 47,760 active samples per channel, active RMS 50.15, and 440.009 Hz.
This proves AudioTrack-to-PipeWire PCM, not merely AudioTrack initialization
or an idle PipeWire node.

Microphone permission denial was exercised through the ordinary Android
permission dialog in `m1b84_session_6fxx1kmc`; the app reported
`RECORD_PERMISSION_DENIED`, and no capture connection was opened. Permission
was then granted through PermissionController UI in
`m1b84_session_tgcfzkl7`. After a full runtime restart,
`m1b84_session_7bmrswv1` reported `RECORD_PERMISSION_ALREADY_GRANTED`.
AudioRecord read 144,000 mono frames at 48 kHz from a controlled PipeWire
virtual source. The app computed RMS 3535.08, 2,640 zero crossings, dominant
frequency 440 Hz, and SHA-256
`c17e0171a907e9c8db395333ff6f20e05c657062efdd06d129eab65079303d50`. The
host adapter independently recorded 145,920 frames, RMS 3535.16, peak 5000,
and 145,676 nonzero samples. The virtual source was kept active during the
successful capture; an earlier silent attempt was caused by PipeWire
suspending the source while it had no active reader.

| Gate | Result |
|---|---|
| Primary HAL selection/open and AudioFlinger output stream | PASS in opt-in overlay session |
| Deterministic Android AudioTrack to PipeWire signal | PASS, `m1b84_session_2mbhio2e` |
| Android microphone denial without `RECORD_AUDIO` | PASS, `m1b84_session_6fxx1kmc` |
| Normal UI grant and grant persistence across runtime restart | PASS, `m1b84_session_tgcfzkl7` → `m1b84_session_7bmrswv1` |
| AudioRecord capture from controlled PipeWire virtual source | PASS, 440 Hz signal, `m1b84_session_7bmrswv1` |
| Permission revocation and post-revocation denial | OPEN |
| Ordinary VLC/mpv playback, controls, concurrency, disconnect/recovery | OPEN |
| Physical microphone | Not tested; no physical-device claim |

The full Python suite passed 357 tests, with zero failures, errors, or skips;
the focused audio and runner suite passed 86 tests. The HAL and ashmem shim
built with `-Wall -Wextra -Werror`. Fresh M2 Settings/Contacts smoke passed:
presenter import/release counts were 54/54 and 36/36, outstanding buffers
were zero, and closing Contacts left Settings running. M3 returned
`PASS mask=255` in `m1b84_session_cuspcn5l`, with a clean overlay removal. A
bounded normal-session MediaStore/ACL regression passed in
`m1b84_session_0ee286he`. The workspace guard passed on NTFS3 UUID
`A2ACEDF2ACEDC0C1`: 73,241,320,448 bytes allocated (below the 80 GiB ceiling)
and 297,532,612,608 bytes available (above the 20 GiB reserve). Sessions
reached `STOPPED`; temporary PipeWire source/sink modules, FIFO, audio bridge,
session sockets, and test captures were cleaned from their active locations.

These results advance the audio vertical slices but do not close audio or
canonical M4. The detailed raw session logs and captures remain outside Git
under the workspace temporary directory. The dated machine-readable record is
`audio_microphone_continuation_2026_11_07` in
[`results/m4/acceptance.json`](../../results/m4/acceptance.json).

## External-workspace integrity pause (2026-11-07)

Final host-kernel inspection found four NTFS3 `mi_enum_attr` warnings on
`/dev/sda2` for `install_sessions.xml.new`, most recently at 2026-11-07
03:12:11 +05:30 (inode `cb85d`). Linux 7.2's NTFS3 implementation marks the
inode bad when its MFT attribute enumeration detects invalid structure. The
logs do not establish the underlying cause, and the warnings predate the
audio sessions; they are not attributed to the audio changes. No further
Android sessions or workspace-backed test writes will run until independent
filesystem-health assessment. No repair or userdata mutation was attempted.
The capacity/workspace guard passed, but it does not check MFT integrity.
Storage integration retains its historical acceptance record while the
current backing-health revalidation remains open. See
`filesystem_integrity_stop_2026_11_07` in
[`results/m4/acceptance.json`](../../results/m4/acceptance.json).

The follow-up read-only assessment found same-device UAS resets and block
read I/O errors, while passive SMART data was inaccessible without elevated
device access. A tracked UUID-scoped safety policy now makes the ordinary
workspace guard reject this volume as `DEVICE_FAILURE_SUSPECTED` before
recursive capacity accounting. Android execution remains blocked pending
offline consistency, device-health, and post-recovery evidence; details are in
the [NTFS3 health assessment](../storage/ntfs3-health-assessment-2026-11-07.md).

The post-CHKDSK Linux check found the expected UUID on the same USB-attached
SSD, but the partition was not mounted. No CHKDSK result or passive SMART data
was available; the short unmounted journal interval had no new storage errors
but cannot validate the volume. The quarantine remains active and audio
acceptance must not resume yet. See `post_chkdsk_assessment_2026_11_07` in the
M4 acceptance JSON.

### Installed application catalog and Linux launcher (2026-11-06)

**Installed-App Catalog and Launcher Integration: PASS/CLOSED.** The tested source revision is recorded in the matching `installed_app_catalog_launcher_2026_11_06` object in [`results/m4/acceptance.json`](../../results/m4/acceptance.json). This closes the launcher workstream only; canonical M4 remains `PARTIAL/OPEN` for host audio/microphone, bidirectional clipboard, and Android notification forwarding.

The runner's existing session-owned storage helper now performs a one-shot PackageManager query for `ACTION_MAIN` plus `CATEGORY_LAUNCHER`. Its manifest declares only that launcher intent under `<queries>`, fixing Android package-visibility filtering without requesting `QUERY_ALL_PACKAGES`. The helper returns package ID, resolved launch activity, application label, version code/name, enabled state, and a 96×96 PNG icon rendered through Android resources. The AaaS host refreshes this snapshot through the active session control socket or creates a temporary Settings session when stopped, then shuts that temporary runtime down cleanly.

The host stores a persistent cache at `${XDG_DATA_HOME:-~/.local/share}/aaas/catalog.json`, with a separate ownership manifest and per-package icons. It creates XDG desktop entries under `${XDG_DATA_HOME:-~/.local/share}/applications/aaas-catalog-<package>.desktop`. Entries use a validated package ID and fixed AaaS launch command; labels and icon paths never become shell arguments. Updates reconcile on app launch and through `aaas-desktop catalog refresh`; stale entries are removed only when named by the AaaS ownership manifest. A failed stale-package launch also triggers reconciliation. Existing files with collisions are preserved. If Android has no icon, the entry uses the explicit `application-x-executable` fallback. The desktop catalog remains available with Android stopped; no permanent supervisor was added.

Live acceptance discovered 19 launchable Android applications, including Files (`com.android.documentsui`), Messaging (`com.android.messaging`), and Settings (`com.android.settings`). All 19 generated entries passed `desktop-file-validate`, Android rendered icons for the applications in the accepted snapshot, and KService's cache was refreshed. `gio launch` invoked the generated Files entry from a stopped runtime, and a generated Settings entry reused the same running session in slot 2. The session exposed separate presenter processes/displays. Closing Files left Settings running. The catalog remained on disk after runtime shutdown.

A controlled signed probe `org.aaas.catalogprobe` verified catalog lifecycle without touching accepted diagnostic packages: version 1 installed normally in session `m1b84_session_31e280ht`; same-signed version 2 updated in session `m1b84_session_52ewajda`; the refreshed catalog and desktop entry reported version code `2`; ordinary PackageManager uninstall succeeded in `m1b84_session_fz0miswi`; refresh removed only its AaaS-owned entry; and session `m1b84_session_itpiy1yj` verified the package remained absent after a complete runtime restart. The disposable package was left uninstalled. Test APKs and raw logs remain outside Git.

M2 window regression session `m1b84_session_itpiy1yj` showed Settings and Contacts in separate slots. Stopping Contacts left Settings `RUNNING`; presenter summaries were 123/123 and 79/79 imports/releases, with zero outstanding buffers. The same session verified the package remained absent after restart. M4 shared-storage regression session `m1b84_session_0ee286he` passed ACL preflight and a normal-session scan of the existing synthetic image into `external_primary`; host storage status remained accessible. The full Python suite passed 301 tests with no skips. Workspace guard remained within the 80 GiB ceiling and 20 GiB reserve. No AaaS runner or presenter remained after cleanup. M3 source and implementation were unchanged; prior M3 `PASS mask=255` evidence remains authoritative.

The launcher-specific verification initially passed 304 Python tests. A final least-privilege refinement scopes the PackageManager launcher visibility declaration to the storage helper only; unrelated diagnostic APKs do not receive a `<queries>` rule. The focused launcher/builder tests passed 21 tests and the complete suite passed 305 tests with zero skips. A cold catalog refresh against the revised helper again returned 19 installed launchable applications and the runtime reached `STOPPED`; the catalog persisted. Source revision: `ea27e5e`.

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

### External storage and runtime permission follow-up (2026-11-06)

The historical `getExternalFilesDir(null) == null` result was not reproduced
in the fresh ordinary target-SDK 35 external-files package or the existing
storage and permission probes. They received the mounted primary emulated
volume, created and read app-specific external files immediately and at
bounded 3/15-second checkpoints, and the fresh package's file/hash survived a
full runtime restart. The earlier null remains unexplained but is not a
current reproducible defect.

An ordinary target-SDK 35 app requested `READ_MEDIA_IMAGES` through Android's
PermissionController. A user-facing “Allow all” grant persisted across a full
runtime restart and enabled an ordinary ContentResolver query to return the
indexed public PNG (`rows=1`). Revocation in Settings denied both
`READ_MEDIA_IMAGES` and `READ_MEDIA_VISUAL_USER_SELECTED`, changed AppOps to
`ignore`, and remained denied after a same-signed update and full runtime
restart; the still-existing image query returned `rows=0`. Two other test
packages remained denied. The source probe and builder now include focused
permission callback/query coverage; the full Python suite passed 290 tests
with no skips after those changes.

Android `StatFs` and host `df` reported matching 500,090,007,552-byte total
capacity; available-space measurements differed by less than 1 MB at adjacent
checks. `StorageStatsManager` returned app=65,536, data=61,440, cache=40,960
bytes for the permission package. Project-quota xattrs remain unsupported, so
this is bounded accounting characterization, not proof of quota enforcement
or exact package accounting. BFE's original APK contains `lib7zz.so` as an
AArch64 ELF DYN/PIE with `/system/bin/linker64` interpreter and a Termux-style
RUNPATH. No runtime linker trace was obtained; this metadata raises a
packaging/loading hypothesis but does not prove the failure cause. BFE archive
create/extract and the Android-facing symlink matrix remain open. Therefore
M4 storage integration remains `PARTIAL/OPEN`; canonical M4 remains
`PARTIAL/OPEN`.

### Final storage integration closure (2026-11-06)

**M4 Storage Integration: PASS/CLOSED.** The tested source revision is
`d9d259fe563da9f00613495afacf5dec3f0ef92a`; repository HEAD at the start of
this continuation was `eb375300d196dcdf5e83a83187c2961f0ef71fb1`. The target-SDK
35 ordinary probe ran in session `m1b84_session_hwwubv1c` with package
`org.aaas.symlinkprobe20261106`, UID 10157, after PermissionController granted
`READ_MEDIA_IMAGES`; a complete runtime restart preserved the grant. Its
regular 68-byte public PNG read via app file APIs with SHA-256
`fd112a85af94a5db985cf734e40d9eb8d3049c334fcb4b8dec60caaf17f60661`. Relative,
absolute, dangling, cyclic, host-only, same-app-private, and other-app-private
links all failed direct application opens with FUSE `ENOSYS`; four MediaStore
rows for links were returned, but ContentResolver opens failed with `ELOOP`
and returned no bytes. The probe package was removed via PackageManager after
testing, which also cleared its runtime permission. Exact log hash and each
row/result are in the latest JSON continuation.

BFE's original APK remains unchanged (SHA-256
`0ec271c371a4747760b264b8beef6bce2c4cbf331b6a6386e785cbbd5ec770bd`). A
controlled ordinary-app probe first reproduced the missing guest
`libc++_shared.so` loader dependency, then ran the APK's exact ARM64 `lib7zz.so`
through Berberis after a hash-recorded, session-local dependency overlay;
`7zz --help` exited 0. BFE's own Compress and Unpack Archive screens both
failed before producing output because their child invocation of `printf`
resolved AArch64 `libz.so` while launching an x86_64 executable. The Android
linker reported `EM_AARCH64 (183) instead of EM_X86_64 (62)`. Existing BFE
ordinary file operations remain accepted; its archive path is recorded as
`PARTIAL/OPEN` application compatibility and is not evidence of a shared
storage failure.

Android `StatFs` and the prior adjacent host `df` sample reported total
capacity `500090007552` bytes, with free-space observations differing by less
than 1 MiB. `StorageStatsManager` returned nonzero package/data/cache values;
exact per-package quotas are not claimed because NTFS3 rejects project-quota
xattrs. NTFS3 also rejects `security.selinux`; this development profile makes
no stock SELinux-label or fscrypt/FBE claim. The tested Android UID/DAC,
mount-namespace, FUSE, framework-permission, and URI-grant boundaries showed no
unauthorized host or cross-app data read. This is bounded development-profile
acceptance, not production Android security equivalence.

Fresh regressions: M2 Settings/Contacts separate displays and independent
close passed; presenters reported 86/86 and 60/60 imports/releases with zero
outstanding buffers. M3 emitted `PASS mask=255`; its session overlay and
diagnostic libraries were removed at shutdown. The full Python suite passed
294 tests, zero skips. Workspace UUID `A2ACEDF2ACEDC0C1` remained mounted
read/write; the final guard observed 61,176,305,152 bytes used against 80 GiB,
with 309,597,638,656 bytes free against the 20 GiB reserve. No AaaS session
socket or runner/presenter/Native Bridge processes remained after cleanup.

Canonical M4 remained `PARTIAL/OPEN` at the time of this storage closure for
audio and microphone, bidirectional clipboard, notification forwarding, and
the installed-app launcher/catalog workstream.

### Bidirectional clipboard integration (2026-11-06)

**M4 Bidirectional Clipboard Integration: PASS/CLOSED** for bounded plain
UTF-8 text on the accepted KWin host. Actual byte-identical Android-to-Linux
and Linux-to-Android application transfers, protocol selection, cleanup, and
regression evidence are in [`docs/m4-clipboard-integration.md`](../m4-clipboard-integration.md)
and `clipboard_live_acceptance_2026_11_06` in
[`results/m4/acceptance.json`](../../results/m4/acceptance.json). Rich clipboard
formats and untested compositor backends remain outside this bounded support
claim.

Canonical M4 remains `PARTIAL/OPEN` for host audio and microphone integration
and Android notification forwarding.

### Android notification forwarding (2026-11-06)

**M4 Android Notification Forwarding: PASS/CLOSED** for ordinary Android app
notifications routed through the user-authorized listener and the active Linux
session notification service. The architecture, privacy controls, Plasma
service details, session IDs, package identities, update/cancel evidence, and
cleanup are recorded in the [notification integration record](../m4-notifications.md)
and `android_notification_forwarding_2026_11_06` in
[`results/m4/acceptance.json`](../../results/m4/acceptance.json).

The final two-package run used Android packages
`org.aaas.notificationprobe` (UID 10161) and
`org.aaas.notificationprobe2` (UID 10162). Android enqueued notifications for
both packages, updates reused their respective Plasma notification IDs, and
cancellation closed each mapping independently. The listener was separately
authorized through Android Notification Listener Settings; each probe received
its own normal `POST_NOTIFICATIONS` grant. No privileged permission grant or
framework policy bypass was used. The 339-test Python suite passed with zero
failures, errors, or skips. The final session stopped and left no AaaS runner,
notification adapter, clipboard helper, session socket, or notification event
frame. Canonical M4 remains `PARTIAL/OPEN` for Android audio playback and
microphone capture; this notification continuation did not re-run M2/M3 live
smokes.

## 2026-11-06 audio and microphone integration attempt

An opt-in session-local legacy HAL prototype was added for the image's HIDL
Audio HAL 7.1 adapter. It builds for x86_64/Bionic and uses a UID-checked,
bounded Unix PCM socket to a session-owned `libpulse-simple` host process over
`pipewire-pulse`. A host-only null-sink loopback received a paced 440 Hz test
signal, confirming that host transport independently. This is not Android
playback evidence.

Live Android session `m1b84_session_ckxzb6mf` confirmed `ro.hardware=ranchu`,
set the session property `ro.hardware.audio.primary=aaas`, exposed the matching
HAL module, and waited for HIDL `IDevicesFactory/default` registration before
starting audioserver. Despite those conditions, AudioPolicyManager could not
load `primary`, and the ordinary AudioTrack probe failed with `-19`. The host
bridge accepted no PCM client. The current evidence does not identify the
specific HIDL `openDevice` failure, so the Audio HAL root cause remains
unresolved and playback is not accepted. The HAL's AudioRecord callback has
not been exercised; microphone capture and Android permission lifecycle remain
unverified. The prototype is opt-in and the default runtime path is unchanged.

The full Python suite passed 348 tests with no skips after adding the
session-only overlay and host transport tests. Focused tests passed 77 tests.
A fresh M2 Settings/Contacts smoke passed with independent closure and balanced
presenter buffers. M3 was not rerun in this continuation; its prior accepted
`PASS mask=255` evidence remains the latest M3 result. The workspace guard
passed on NTFS3 UUID `A2ACEDF2ACEDC0C1` at 62,052,111,872 bytes allocated
against the 80 GiB ceiling, with 308,721,827,840 bytes free against the 20 GiB
reserve. The experimental Android session reached `STOPPED`; its host bridge
was terminated. These results do not close the canonical milestone, which
remains **PARTIAL/OPEN** for playback and microphone.

## 2026-11-08 audio and ext4 workspace continuation

The workspace has moved from the affected NTFS volume to the ext4 partition
mounted at `/run/media/mrkus/Aaas` (UUID
`094120c3-e1f8-4a61-a95a-c347ecb711d1`). The workspace guard reports
`HEALTHY_FOR_CONTROLLED_TESTING` based on the ext4 recovery evidence and the
UUID-scoped policy transition. Earlier USB/UAS and JBD2 errors remain in the
incident record and are not represented as erased. The current post-test
journal query since 2026-11-08 03:45 IST showed no new matching device, ext4,
USB, or block-I/O event. Passive SMART was unavailable to the guard due device
permissions; the user-supplied prior SMART report was `PASSED` with zero
reallocated/pending/uncorrectable sectors and elevated interface counters.
This is controlled-test clearance, not a lifetime hardware-health claim.

The `--audio` runtime configuration now reproducibly builds or verifies the
session-local primary HAL, ashmem/memfd shim, factory compatibility layer, and
stock-compatible `audioserver`/`libaudiohal.so` overlays. Artifacts are bound
into the session namespace before Android audio services start; the base image
is unchanged. The runner's ordinary Music path indexes a shared WAV using
MediaStore and supplies only a temporary read-URI grant. No broad storage
permission was added.

Live runs verified ordinary Music playback (480,000 frames at 48 kHz stereo),
the AudioTrack probe's 48 kHz stereo pause/resume/mute sequence, and 44.1 kHz
mono PCM mixed to the host's 48 kHz stereo stream. PipeWire monitor analysis
measured the expected 440 Hz/660 Hz content. Two-app sessions placed Music and
the probe on separate virtual displays; monitor samples showed simultaneous
440 Hz and 660 Hz components. In the lifecycle run, slot 2 reached `CLOSED`
while Music's AudioTrack continued for about 2.7 seconds before reporting its
480,000-frame stop. The temporary monitor recording was deleted.

The established virtual-source AudioRecord run captured 144,000 mono frames at
48 kHz with 440 Hz content and matching host/Android RMS. A separate short,
authorized built-in-microphone capture produced low-level host and Android PCM
and the PipeWire source returned to `SUSPENDED`; no raw microphone recording
was retained. Android permission denial and UI grant are supported by prior
session evidence. Active permission revocation and post-revocation denial have
not been verified.

Removing the selected PipeWire test sink during a bounded playback run did not
deadlock Android: AudioTrack completed its probe, mono playback completed, the
host bridge closed, and the runtime stopped cleanly. PipeWire may have moved
the stream, so no claim is made that sink disappearance silenced output. New
unit tests cover partial PCM frame rejection, host write failure cleanup, and
capture peer disconnect. Focused audio/runner/overlay tests passed 100; the
full Python suite passed 389 tests. `git diff --check` and Python compilation
passed. Final M2/M3/M4 cross-feature regression and the remaining audio
permission/failure matrix are still required; canonical M4 remains
**PARTIAL/OPEN**.

### Audio failure and worker-bound follow-up (2026-11-08)

In `m1b84_session_0y_a97b6`, the selected virtual PipeWire capture source was
removed while an authorized AudioRecord was active. AudioFlinger reported
`read failed: framesRead=-61`; the Android probe completed its bounded read
with zero-valued samples (144,000 requested frames, bridge summary 146,880
frames, RMS 0, peak 0, no nonzero samples). The app did not hang, the runtime
reached `STOPPED`, and the host bridge exited. This is source-loss fail-safe
silence evidence; it does not establish permission-revocation behavior.

In `m1b84_session_f655x46_`, the host bridge was terminated during Android
startup. The runner detected the missing bridge, marked the session `FAILED`,
and stopped it; this is fail-closed session detection, not successful
in-flight playback recovery. A fresh session, `m1b84_session_9b2hx39k`, then
completed 48 kHz stereo (192,000 frames) and 44.1 kHz mono (44,100 frames)
AudioTrack probes, closed its host stream after 2,231,040 bytes, and reached
`STOPPED`. This verifies a fresh-session restart after bridge failure, not
automatic same-session bridge restart.

The host bridge now bounds all accepted worker threads to `MAX_CLIENTS` (4),
including unauthenticated connections that have not sent a protocol header.
The synthetic regression test holds four header-less local clients, confirms
the next connection is closed, then confirms capacity returns after client
disconnect. The full Python suite passed 390 tests after this change.

Session log hashes and the exact remaining gates are recorded in
`audio_failure_followup_2026_11_08` in
[`results/m4/acceptance.json`](../../results/m4/acceptance.json). Canonical
M4 remains **PARTIAL/OPEN**: active Android microphone-permission revocation
and post-revocation denial are untested, PipeWire daemon failure and precise
sink-fallback behavior are not established, and the final integrated
cross-feature cleanup matrix remains outstanding.

The integrated audio configuration also completed two cross-workstream
regressions. In `m1b84_session_1vcgru8n`, Settings and Contacts ran on separate
virtual displays with `--audio` enabled; Contacts was closed independently
while Settings remained active, both presenter logs balanced imports/releases
(103/103 and 79/79, with zero outstanding buffers), and the runtime stopped.
In `m1b84_session_qjbac5e7`, the M3 ARM64 probe ran with the same audio startup
configuration and emitted the required `M3 ARM64 Native Bridge PASS mask=255`
signature. Shutdown removed the Native Bridge overlay and diagnostic libraries.
The session audio bridge started and stopped in both cases.

These runs revalidate M2 independent windows and M3 Native Bridge under the
audio-enabled startup composition. They do not rerun the entire M4 storage,
launcher, clipboard, and notification acceptance matrix together. Canonical M4
remains **PARTIAL/OPEN**.
