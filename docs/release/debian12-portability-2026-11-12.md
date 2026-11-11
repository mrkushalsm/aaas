# Debian 12 portability acceptance — 2026-11-12

**Result: NOT PASSED.** The cross-filesystem Native Bridge overlay defect is fixed and covered, but the exact corrected candidate was not installed in either target environment. The host's workspace health gate prevented a fresh install. The existing Debian VM reached Android framework startup but did not reach `RUNNING`.

## Candidate identity

- Bundle: `engineering-3668fcd`
- Bundle ID: `385a08cf0cef4b6fbef8c62df57c8a76`
- Runtime source revision: `3668fcd7999c8794cd109eb084162e0bb54a758b`
- Manifest SHA-256: `0b272a111fabbadd60012765bb33a899a7c826e91f413bd3baf96805a3f11e89`
- Integrity: PASS, 8,790 artifacts
- Runtime dependency closure: PASS, 25 inputs

The recorded manifest and verification details are in [the machine-readable result](../../results/release/debian12-portability-20261112.json). The bundle was not changed during this VM work.

## Change and regression evidence

`prepare_native_bridge_overlay()` retains hard links when source and destination share a filesystem. It falls back to metadata-preserving `copy2` only for `errno.EXDEV`; other errors still fail. Tests cover same-filesystem inode sharing, forced EXDEV metadata/symlink behavior, and propagation of EPERM.

The actual host probe copied the bundle's presenter from the external volume (device 2051) to `/tmp` (device 44), preserved SHA-256, and produced a distinct inode. The focused runner suite passed 109 tests. The full suite had previously passed 570 tests with 6 skips before the test-only metadata assertions were committed. Three native presenter tests also passed in the prior verified run.

## Host result

The original `engineering-830eef7` service was restarted after diagnostics and reached `RUNNING`. Its Settings readiness window delivered 73 frames from 76 submissions; all 76 buffers were released and outstanding ownership returned to zero. Evidence is under `results/release/debian12-portability-20261112/host-original-830eef7/`.

A fresh install of `engineering-3668fcd` was not completed. The external ext4 workspace health gate blocked the attempt; a current read-only assessment reports `HEALTH_UNKNOWN` because the recovery attestation is stale or incomplete. The existing installation and userdata were preserved. This host result validates recovery of the prior runtime, not installation of the new candidate.

## Debian 12 VM result

The existing guest runs Debian 12.15, glibc 2.36, kernel `6.1.190-aaas`, 6 GiB RAM, and QEMU `virtio-vga-gl`. Android was exercised in the existing `engineering-830eef7` installation with disposable source/presenter replacements; it was **not** an exact-candidate installation.

- Composer compilation succeeded with the VM-local compiler wrapper adding `/usr/include/x86_64-linux-gnu`.
- The EXDEV overlay fallback progressed past Native Bridge overlay preparation.
- The exact `engineering-3668fcd` candidate presenter was checked in Debian: all `ldd` dependencies resolved, it ran `--help`, and its highest GLIBC requirement was 2.34. The old installed 830 presenter required GLIBC 2.38; that old-bundle limitation does not apply to the candidate binary.
- KWin's `wayland-2` socket was discovered and the Android producer completed its handshake and configure. No Android frame was submitted.
- Android remained in framework `BOOTING`; `sys.boot_completed` was unset. Package Manager resolved Settings, but Settings was not launched and presenter imports/submissions/presented counts remained zero.
- Android logs recorded fs-verity `EOPNOTSUPP` while persisting Package Manager/runtime permissions on ext4 `/dev/vdb`; Netd NFLOG socket creation returned “Protocol not supported”; and `timerfd_create` returned `EPERM`, causing AlarmManager to fall back. The evidence confirms these unsupported operations but does not prove which one blocks boot completion. This needs further kernel/runtime compatibility work; no kernel rebuild or source workaround was made in this bounded run.
- Audio, Android networking, and ARM64 app execution were not tested because Android never reached `RUNNING`.

Detailed captured logs are in [the evidence directory](../../results/release/debian12-portability-20261112/), including the Android logcat, mount snapshot, presenter build log, Wayland interface listing, and presenter event log. The original VM installation's runner scripts and presenter binary were restored; its AaaS service is stopped, with no Android processes left. The VM and KWin remain available.

## Acceptance summary

| Gate | Original host | Debian 12 VM |
|---|---|---|
| Bundle integrity | PASS (candidate verification) | PASS (candidate presenter binary only; exact bundle not installed) |
| Fresh installation | BLOCKED by workspace health gate | NOT TESTED (exact bundle not installed) |
| Android `RUNNING` | PASS on preserved 830 installation | FAIL on mixed-source 830 diagnostic installation |
| Settings frame | PASS on preserved 830 installation | FAIL; zero frames submitted |
| ARM64 Berberis | NOT TESTED on new candidate | NOT TESTED |
| Audio | NOT TESTED on new candidate | NOT TESTED |
| Networking | NOT TESTED on new candidate | NOT TESTED |
| Restart and shutdown | Prior host installation remained healthy | Diagnostic service stopped; no Android process leak |
| Exact candidate portability | NOT VERIFIED | NOT VERIFIED |

The known-good `engineering-830eef7` bundle and host userdata remain intact. Do not treat this report as a Debian portability pass.
