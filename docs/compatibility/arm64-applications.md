# Post-M3 ARM64 application compatibility study

**Study status: `PASS/CLOSED` for the supplied APK inventory.** Individual app results below remain partial where their meaningful native workflow could not complete. This study does not claim universal Android or ARM64 application compatibility.

The test scope was the supplied collection on Android 16/API 36 x86_64 with the pinned Digitalis/Berberis Native Bridge, using the existing rootless KWin AaaS window path. KWin was 6.7.5. Digitalis bundle revision was `ddef6e6ae7de37dd3e400d6a07d3f18cb21a0ebc` from Refract. The session used Native Bridge callback interface v8. For multi-ABI tests, an explicit session-local option ordered `arm64-v8a` ahead of `x86_64`; the APKs were not changed.

## Inventory summary

Five APK files representing four package IDs were found recursively under `/run/media/mrkus/Homework/aaas-workspace/apks/post-m3/`. All five ZIPs passed integrity checks, all contained ARM64 libraries, and no split sets, byte-identical duplicates, or unsupported input formats were found. Every original SHA-256 was rechecked after testing and matched the initial inventory. Package versions, signatures, permissions, activities, ELF machines, native libraries and hashes are in [`compatibility.json`](../../results/post-m3/compatibility.json); the full metadata inventory and alias/split analysis remain in the external workspace at `/run/media/mrkus/Homework/aaas-workspace/results/post-m3-app-compat/inventory.json`.

The APKs were exposed to Android as session-local preinstalled diagnostic system apps, matching the existing AaaS app-overlay mechanism. PackageManager scanned them and their activities ran; this was not a `PackageInstaller` user-install test. Compressed native libraries were extracted to a temporary validated library directory and bound read-only at the Android app library path. Source APKs remained unchanged.

## Compatibility matrix

| Application | Version | Package | Native ABIs | Install/launch | ARM64 Native Bridge | Functionality | Result |
|---|---|---|---|---|---|---|---|
| Banners File Explorer | 1.4.0 | `com.the412banner.bfe` | arm64-v8a | PackageManager scan and launcher passed | Not verified for an app-owned library | Home, Apps, Internal navigation worked; file creation failed before archive testing | `PARTIAL` |
| Apotris (ARM64) | 4.1.1b | `com.apotris.android` | arm64-v8a | Passed | `libmain.so` loaded; SDL main ran; Berberis JIT activity observed | Reached game menu after pointer input; repeatable guest SIGSEGV and activity restart prevented sustained gameplay | `PARTIAL` |
| Apotris (universal) | 4.1.1b-universal | `com.apotris.android` | arm64-v8a, armeabi-v7a, x86, x86_64 | Passed with ARM64-first session | ARM64 `libmain.so` loaded; x86_64 fallback not selected | Same guest SIGSEGV pattern as ARM64 build | `PARTIAL` |
| VLC | 3.7.2 | `org.videolan.vlc` | arm64-v8a | Passed | `libvlc.so` and `libvlcjni.so` loaded from ARM64 path | Onboarding, Videos and Browse screens worked; playback not exercised because no readable sample media was available | `PARTIAL` |
| mpv | 2026-09-17-release | `is.xyz.mpv` | arm64-v8a, armeabi-v7a, x86_64 | Passed with ARM64-first session | ARM64 `libmpv.so` loaded; x86_64 fallback not selected | Chooser and picker worked; attempted sample open was denied by Android storage policy before decode | `PARTIAL` |

## Findings and limitations

- **Harness correction:** APK native libraries in these system-app overlays are not extracted by PackageManager. The runner now safely extracts valid `lib/<abi>/*.so` entries into a session-local directory, checks ELF class and machine, records hashes and provenance, and binds the directory read-only. The original APK remains the source of truth. This enabled actual ARM64 `libmain.so`, `libvlc.so`, `libvlcjni.so`, and `libmpv.so` loads in the recorded sessions.
- **Multi-ABI selection:** the opt-in diagnostic ABI order enabled the universal Apotris and mpv tests to select ARM64 while keeping x86_64 available second. The default runtime ABI ordering is unchanged.
- **Apotris:** both APK variants presented real Android frames and accepted a Wayland pointer click. The app then repeatedly received a Berberis guest signal 11 with null fault address and restarted. No app tombstone was emitted, and the fault PC was not symbolized; the exact defect is therefore unresolved and is not attributed to a particular instruction or component.
- **VLC/mpv:** the tested shared libraries loaded through the ARM64 path, but the supplied session did not have a readable media file. A generated synthetic clip was attempted for mpv; Android denied access to the session-local `/data/media/0/Movies` path before decoding. No decoder success is claimed.
- **BFE:** the interface rendered and navigation input worked, but creating a disposable file failed. Its archive/native 7-Zip path was not exercised, so the presence of ARM64 archive libraries is not counted as Native Bridge execution.
- These results characterize the supplied APK builds and the diagnostic system-app overlay only. They do not establish normal user installation, arbitrary app-private storage, video/audio playback, or universal application compatibility. Audio integration remains M4; graphics throughput remains M5; broader compositor and distribution coverage remains M6.

## Human usability follow-up

No human usability session was performed (`human_usability_status: NOT_TESTED`). For later manual checks, use only disposable data:

- **Apotris:** launch, enter a game from the menu, play briefly, then check whether the process remains stable beyond the automated run’s crash window.
- **VLC:** open a known local sample, verify video decoding, pause/seek, and separately assess audio once the host audio path is available.
- **mpv:** open a local video through the document picker, confirm playback and seek behavior.
- **BFE:** grant only the Android storage access needed for a disposable archive test, create/extract a small archive, and verify its contents.

## Reproducibility and evidence

Structured results include per-APK original SHA-256, ABI/ELF inventory, classification, Android-side loader evidence, presenter accounting, resource snapshots, and raw log hashes. Raw session logs and screenshots are outside Git under `/run/media/mrkus/Homework/aaas-workspace/tmp/` and `/run/media/mrkus/Homework/aaas-workspace/results/post-m3-app-compat/`. Representative sessions include Apotris `m1b84_session_b51pfe26` and `m1b84_session_kuwckco2`, BFE `m1b84_session_9mdgu69m`, VLC `m1b84_session_a37dyv02`, and mpv `m1b84_session_elyku7tf`. All tested sessions stopped cleanly and the captured presenter summaries reported zero outstanding buffers.

The runner’s native-library extraction, ABI-order option, and opt-in private tombstone export are covered by focused tests in `tests/test_run_aaas.py`. The targeted runner suite passed 49 tests; the full Python suite passed 249 tests. The Android workspace guard passed at 57.21 GB used with 313.66 GB free (80 GiB ceiling, 20 GiB reserve). All 10 test sessions stopped with zero outstanding presenter buffers. No native component tests were needed because native graphics/runtime sources were unchanged.

The canonical M3 ARM64 Native Bridge milestone remains `PASS/CLOSED`. **M4 — Native Desktop Integration** remains the next product milestone; this study does not start M4.

### BFE archive native execution follow-up (2026-11-06)

The original BFE 1.4.0 APK hash is
`0ec271c371a4747760b264b8beef6bce2c4cbf331b6a6386e785cbbd5ec770bd`. Its
ARM64 `lib7zz.so` and `libc++_shared.so` were extracted by Android PackageManager
into BFE's ordinary app native-library directory. A controlled target-SDK 35
probe executed the original ELF through the opt-in Berberis executable path.
Without a guest-visible libc++ runtime, bionic reported
`library "libc++_shared.so" not found`; with that exact library copied into a
session-local, hash-recorded guest overlay, `lib7zz.so --help` exited 0 and
printed 7-Zip 24.08 help. This establishes that the ELF and Berberis execution
are usable with the dependency available; the immutable Android base image and
third-party APK were not changed.

The original BFE Compress and Unpack Archive UI flows still failed before
producing a ZIP. In both cases BFE launched x86_64 `printf` while its child
library search path selected the bundled AArch64 `libz.so`. Android's linker
reported `EM_AARCH64 (183)` instead of `EM_X86_64 (62)`. The archive failure is
classified as BFE's cross-ABI child-process environment/launcher issue;
archive compatibility remains `PARTIAL/OPEN`. Ordinary BFE shared-file
operations and the platform storage integration are tracked separately. Raw
session log hashes and the exact linker line are in
[`results/m4/acceptance.json`](../../results/m4/acceptance.json).

### BFE archive UI follow-up (2026-11-05)

The original BFE 1.4.0 APK was opened in a visible AaaS Wayland window. Android
and KWin confirmed the BFE activity/toplevel even though the external CUA
inventory returned `apps=[]`; that inventory does not enumerate AaaS presenter
windows. With BFE's package-specific all-files access enabled through Android
Settings, the Compress action returned to the file list without producing an
archive. Opening a valid synthetic ZIP in BFE's Unpack Archive workflow
reported the APK's bundled ARM64 `lib7zz.so` path as inaccessible or not found.
The source APK contains `lib/arm64-v8a/lib7zz.so`; the host verified the ZIP
structure and payload hashes independently. This narrows the failure to BFE's
archive/native-library path under the ARM64 compatibility runtime, but does
not identify the exact loader cause. BFE's special access was revoked after
the attempt. Archive functionality remains `PARTIAL`; ordinary shared-file
operations remain separately evidenced in M4 storage records.

### Real media/file app install persistence (2026-11-06)

The supplied VLC (`org.videolan.vlc`), mpv (`is.xyz.mpv`), and Banners File
Explorer (`com.the412banner.bfe`) APKs were each installed by Android
PackageManager as ordinary user applications with the supported opt-in
session-local Digitalis/Berberis Native Bridge. Each app launched on Android
display 2, survived a complete AaaS runtime stop/restart without reinstall,
and launched again from the persistent PackageManager state. The observed UIDs
were VLC 10157, mpv 10158, and BFE 10152. Their APK hashes, session IDs, and
log hashes are recorded in the M4 acceptance JSON. A no-bridge VLC attempt
failed with `INSTALL_FAILED_NO_MATCHING_ABIS`; this is expected for its ARM64
native payload under the normal x86_64-only session. The test verifies
installation and relaunch persistence, not deliberately modified app settings
or playback history.
