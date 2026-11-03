# M4 — Native desktop integration

**Status: PARTIAL/OPEN.** The lifecycle and per-user launcher slice below is implemented and live-tested. Mandatory audio, host file selection and scoped writes, clipboard, and notification forwarding do not yet have host adapters, so M4 is not closed. M4 follows the [canonical roadmap](../roadmap.md); M5 performance and M6 compositor portability remain separate.

## Baseline and scope

The supported baseline is the rootless Android 16 x86_64 runtime under KWin on Wayland. Existing M2 native windows and M3's opt-in Digitalis Native Bridge remain the graphics and ARM64 paths. This implementation adds user-level desktop launchers and uses the existing two-display session controller; it does not alter the Android image or introduce a resident supervisor.

## Implemented lifecycle slice

[`scripts/aaas_desktop.py`](../../scripts/aaas_desktop.py) writes a per-user freedesktop launcher after validating the Android package ID. Its `launch` command serializes cold starts, waits for the runner's explicit `RUNNING` status, launches into an active session when available, and reuses the existing two-slot runner. A cold launch uses one preinstalled system app as a temporary second-slot bootstrap and requests its orderly app stop once the requested application is running. The helper window is released before the launcher command succeeds. `aaasctl stop-app SLOT` requests Android `force-stop` and lets the existing window lifecycle close the associated display/presenter.

This is a bounded launcher proof, not the completed lifecycle product: application discovery/catalog generation, concurrent stress coverage, a documented idle timeout, idle shutdown, and launcher cleanup on Android uninstall remain open. The runtime has explicit start/stop control but no automatic idle policy. A running Android runtime consumes resources; the verified fully stopped state has no runner/presenter processes.

### Live evidence

- KWin `6.7.5`; active host session, Android 16 x86_64 existing image.
- Session `m1b84_session_jkei7jtx`: `aaas_desktop.py launch --package com.android.settings` cold-started AaaS, kept Settings in slot 1, stopped the temporary Contacts bootstrap in slot 2, and returned only after the bootstrap window reached `CLOSED` with no presenter. Session later reached `STOPPED`.
- Session `m1b84_session_ffuknl4k`: Settings and Contacts ran in separate displays/presenters. Contacts was stopped and relaunched into slot 2 while Settings remained active; Contacts was stopped again, then Settings was stopped. Both presenter summaries report imports equal releases, `outstanding: 0`, and clean shutdown. The primary presenter summary reports 245 imports/releases; the second presenter reports 132 and then 32 across its close/reopen lifetimes.
- Final launcher session presenter log SHA-256: `a5a4e26d7960dc4d90a55efcb3082cc74b4b4fc12414c9a0324b3a7ea0bf3954`; bootstrap presenter: `e3bb80efd5aea7d89005a310e5cf5d3f76b94db24df1a3eeb11fd4e7e5b1f65a`.
- Two-slot lifecycle session hashes: commands `fda5fecd4101e98133036667737c5138b5dadae84994b977abdda19c4b72ae6b`; logcat `38317fe39099ee758636cb3e3f39e708c1e167efbc41d39c00074eb59cf6bc85`; presenter 1 `09bce4fa56d032ae021527720b17aa802c63f461c387e62b31b09792d50aea28`; presenter 2 `37de18d643f7652ea36f08fbfb277b2131fd9c2d6b800757ba53b45688f13214`.
- M3 regression session `m1b84_session_kx_r4eqw`: existing ARM64-only diagnostic launched with the pinned overlay; Android log contains Berberis JIT translation and a successful load of `/product/app/AaasLatencyProbe/lib/arm64/libm3probe.so`. The session stopped cleanly and reported removal of the session-local Native Bridge overlay and diagnostic APK libraries. Logcat SHA-256 `4827168befbb38843ecb60811bedac373701c59eb8c77e699950b61defbebb4d`; commands SHA-256 `d78f38cb8800906ae95622d5aea565e3bc6db044d6bc5cfefea1230a0b5a2c0a`; presenter SHA-256 `de62f09b84f1a212a031d25467e6f7b2d6cdc6d5fc8985065ba4a54e60ec3597`.
- User-level Settings and Contacts `.desktop` entries passed `desktop-file-validate`; KDE application cache was refreshed. The repository includes focused tests for package validation, Exec quoting, atomic launcher creation, and stop request generation.

Raw sessions are retained under `/run/media/mrkus/Homework/aaas-workspace/tmp/`; original session logs are not copied into Git.

## Host capability audit and remaining gates

| Capability | Current evidence | M4 status |
|---|---|---|
| On-demand start and reuse | Live cold launcher start and same-session second app launch above | Partial: idle policy, concurrent launch and full failure-recovery gates remain |
| User desktop launcher | Per-user entries and runner invocation exercised | Partial: app discovery/catalog and uninstall cleanup are absent |
| Host audio playback | PipeWire 1.6.9, WirePlumber, and pipewire-pulse are active on host. Android AudioFlinger and Ranchu audio HAL exist, but runner does not connect a host PCM endpoint or transport samples. | Not implemented; no playback proof |
| Microphone | Host audio source exists; Android runner does not expose a scoped host capture stream. | Not implemented; no authorization/revocation proof |
| Host file selection/read/write | KDE XDG portal and document portal are available. Android has its stock storage framework, but AaaS has no DocumentsProvider/SAF-to-host portal adapter. Broad home mounts are not an acceptable substitute. | Not implemented; no scoped byte-exact read/write proof |
| Media selection | No AaaS adapter connecting host selected media to Android SAF/MediaStore. | Not implemented |
| Clipboard | Wayland presenter has no data-device clipboard bridge to Android ClipboardManager. | Not implemented |
| Notifications | Host DBus notification service and Android NotificationManager exist, but no AaaS forwarding listener/adapter exists. | Not implemented |
| Normal APK installation | Existing acceptance used system-app overlays; no normal user PackageInstaller workflow or launcher discovery is included in this change. | Not verified |
| Camera | `/dev/video*` devices exist on host, but are not bound into Android; no Android Camera HAL to authorized host source adapter is present. | Feasibility only; not supported |
| M2/M3 regression | KWin Settings/Contacts presentation and teardown were exercised; M3 diagnostic regression was not rerun because Native Bridge integration was untouched. | Partial regression evidence |

The mandatory M4 acceptance gates for actual host audio playback, scoped file read and write, bidirectional clipboard, and supported Android notification forwarding remain open. Therefore this record intentionally stays `PARTIAL/OPEN`.

## Security and deferred scope

No broad host home mount or host device bind was added. No host microphone or camera stream is exposed. Camera needs a supported Android HAL/provider bridge plus host authorization; the permission dialog alone is not device support. Physical camera, Bluetooth, broad sensor access, M5 performance, and M6 compositor expansion remain outside this accepted slice.

## Verification

Focused command `python3 -m unittest tests.test_run_aaas tests.test_aaas_desktop tests.test_aaasctl -q` passed before the final control-client assertion was added; the final full command `python3 -m unittest discover -s tests -q` passed all 255 tests. Python compilation, `git diff --check`, both generated `desktop-file-validate` checks, and `python3 scripts/android_workspace.py --workspace /run/media/mrkus/Homework/aaas-workspace check` passed. The final guard recorded 57,293,189,120 bytes used against an 80 GiB ceiling, with 313,580,122,112 bytes free against a 20 GiB reserve. No AaaS runner/presenter processes remained after shutdown.
