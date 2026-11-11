# Local candidate readiness — 2026-11-11

This record describes one local diagnostic bundle and one isolated installation. It is not public-release approval.

## Candidate identity

- Source commit: `830eef735bfa41685a8def7a754d24a5740e8d30` (`fix(bundle): include presenter build toolchain`).
- Bundle: `engineering-830eef7`; ID `d3d7278094324b93be4f3ad57ae5883d`.
- Path: `~/.local/share/aaas-release-artifacts/engineering-830eef7`.
- Manifest SHA-256: `5cf6e4cab68c907d5496930390497f9c563c8f6254b7c0efbb9a2d85420f80e2`.
- Manifest entries: 8,789; bundle integrity: **PASS**.
- Runtime closure: **PASS**, 25 checked inputs, zero missing inputs.
- Android: 16 / API 36 / build `BE2A.250530.026.D1`, x86_64.
- The Android base is a historical modified M4 diagnostic rootfs, not a reproducible AOSP build. The manifest marks the source tree dirty at capture because the two protected untracked build directories were present; tracked source was at the listed commit, but this is not a clean-worktree reproducibility proof. The bundle is unsigned and publisher authenticity is not established.

The corrected bundle includes `workspace/toolchain/libc++` and the installer stages it into a fresh workspace. This fixes the reproduced fresh-install failure where a required presenter rebuild stopped because libc++ headers were absent. Exact regression evidence: [fresh-install toolchain failure evidence](../results/release/fresh-install-toolchain-gap-2026-11-11.json).

## Live candidate evidence

Fresh install root: `~/.local/share/aaas-clean-install-830eef7`; service: `aaas-m5-clean-830eef7.service`. The installation manifest records fresh installation-local userdata and bundle ID `d3d7278094324b93be4f3ad57ae5883d`. Android reached `RUNNING` on the first boot, and again across five tested service cycles. Settings produced real presenter frames; five cycles each reported zero outstanding presenter ownership and clean service shutdown. The per-cycle record is [per-cycle record](../results/release/five-lifecycle-cycles-2026-11-11.json).

Settings, Contacts, Apotris, and VLC were launched. Presenter logs show submitted/released/presented frames and no rejected frames for the recorded Settings run. VLC launched from an ARM64 APK, but this run did not capture direct Berberis native-execution logs; treat ARM execution on this exact installation as **not independently proven**. Prior Berberis observations belong to earlier test evidence. Dynamic resize source fix is included in this candidate, but exact-bundle interactive resize was not repeated.

AudioProbe playback from installed Android was captured from the active PipeWire headphone sink monitor: 7,077,888 bytes of s32 stereo at 48 kHz, 144,704 nonzero samples, peak 17,498,112, RMS 4,977,405.59, zero clipped samples. This proves signal reached the host monitor, not fresh human audibility. Earlier human listening confirmation is separately recorded in [`human-listening-2026-11-10.json`](../results/audio/human-listening-2026-11-10.json). The bridge outage/recovery probe also passed twice under a private D-Bus session.

The Android Network Probe on this candidate displayed `PASS`: ConnectivityManager network ID 100, INTERNET and VALIDATED, `eth0`, DNS `10.0.2.3`, default route via `10.0.2.2`, DNS resolution, and TLS-verified HTTPS status 204. The actual application window is captured at [network probe screenshot](../results/release/network-probe-engineering-830eef7.png). Host network configuration was not changed. Restart/recovery networking was not separately asserted.

Update and rollback were not exercised against this exact candidate. Supported uninstall and reinstall passed: the disposable profile unit was removed with userdata preserved, then the same bundle was reinstalled and Android returned to RUNNING with previously installed probe packages still present. Five runtime cycles passed, but they do not replace update/uninstall testing. An earlier installation B SurfaceFlinger first-boot crash remains an unresolved intermittent reliability incident; this candidate's one pristine install does not establish first-boot reliability across installations.

Machine-readable exact-candidate evidence: [candidate acceptance record](../results/release/candidate-acceptance-engineering-830eef7-2026-11-11.json). File-level inventory: [file-level inventory](../results/release/sbom-engineering-d3d72780.json).

## Storage and host state

AaaS-only cleanup removed verified obsolete bundles, old installations and disposable test workspaces. Root filesystem free space at the latest measurement was 24,381,992,960 bytes; the external workspace filesystem reported 37,149,773,824 bytes free. The external ext4 volume has a recorded suspected device/I/O fault; further writes to it are suspended. Protected untracked build directories remain untouched. Cleanup details and preserved evidence archives are in [cleanup inventory](../results/release/host-cleanup-bundle-inventory-2026-11-11.json).

The fresh isolated candidate service is active. The old original installation was removed as part of the authorized cleanup; it is not claimed to be running. Do not reuse writable userdata across installations.

## Security and distribution

- Integrity: **PASS**. Runtime input closure: **PASS**.
- Runtime security: **NOT APPROVED**; this diagnostic profile contains SELinux compatibility shims and is not suitable for untrusted APKs or hostile multi-tenant workloads.
- Publisher authenticity: **NOT ESTABLISHED**; manifest hashing is not a signed trust chain.
- Source license: absent; owner must select and authorize a project license before source publication.
- Binary redistribution: **NOT CLEARED**. The Android rootfs has incomplete file-level source/license provenance; this inventory is not a legal clearance.
- External workspace health: device failure suspected; no further writes should be made until separately checked.

**Decision: AAAS NOT YET READY TO PUBLISH.** The exact candidate has demonstrated first boot, app window rendering, audio transport, and five service cycles, but application networking evidence, ARM execution proof, update/rollback/uninstall, reliability closure, runtime security approval, and source/binary publication rights remain open.
