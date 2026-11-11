# Host regression acceptance — engineering-3668fcd — 2026-11-12

## Result

**NOT CLOSED.** The exact `engineering-3668fcd` candidate is intact and passes
integrity and dependency-closure checks. A fresh host installation and runtime
acceptance were not attempted: the external ext4 volume has current-boot
USB/UAS, block-I/O, and ext4 `EIO`/potential-data-loss events, and the
installer capacity check would breach its configured free-space reserve.
No storage-health gate or reserve was bypassed.

## Candidate

- Bundle ID: `385a08cf0cef4b6fbef8c62df57c8a76`
- Artifact count: 8,790
- Manifest SHA-256: `0b272a111fabbadd60012765bb33a899a7c826e91f413bd3baf96805a3f11e89`
- Integrity: PASS
- Runtime dependency closure: PASS, 25 inputs
- Debian 12 portability: NOT VERIFIED

The bundle manifest records builder source revision `3668fcd7999c8794cd109eb084162e0bb54a758b` and `worktree_dirty=true`. The packaged versions of the five primary runtime scripts checked in this run match the current repository files. This does not substitute for a clean-source rebuild.

## Host status and blocker

The original user service `aaas-runtime.service` remained active, with Android
session status `RUNNING`, using the preserved `830eef7` installation and
userdata. It was not changed.

The external ext4 volume reports 129 correlated current-boot events in the
bounded kernel journal: 5 USB transport, 32 UAS transport, 68 block I/O, and
24 ext4 integrity events. The records include block-device `EIO` and ext4
messages warning of potential data loss. Workspace health is
`HEALTH_UNKNOWN` because its recovery attestation is stale/incomplete.

The exact candidate installation would write 4,895,656,848 bytes across the
installation and workspace artifact trees. With 6,330,970,112 bytes available,
that would leave 1,435,313,264 bytes, below the configured 2 GiB reserve by
712,170,384 bytes. Installing on `/` also fails the configured 20 GiB root
reserve. The installation was therefore not attempted.

## Tests completed

- Python regression suite: 570 run, 570 passed, 6 skipped.
- Existing native regression binaries: 17 run, 17 passed. The three DRM-backed
  tests were rerun with `/dev/dri/renderD129` from host graphics discovery.
- Native Bridge overlay tests: 3 passed, covering same-filesystem hard-link
  behavior, `EXDEV` copy fallback with metadata preservation, and propagation
  of unrelated link errors.
- Bundle integrity and 25-input dependency closure: PASS.

## Acceptance

| Gate | Result |
|---|---|
| Candidate integrity | PASS |
| Runtime dependency closure | PASS |
| Python suite | PASS (6 skipped) |
| Native tests | PASS |
| Original runtime readiness | PASS (`830eef7`, RUNNING) |
| Fresh isolated candidate install | BLOCKED |
| Candidate Android readiness and apps | NOT TESTED |
| Candidate ARM64, audio, networking | NOT TESTED |
| Candidate restart, cleanup, uninstall | NOT TESTED |
| Host regression acceptance | NOT CLOSED |
| Debian 12 portability | NOT VERIFIED |

Machine-readable details and test logs are in
[`acceptance.json`](../../results/release/host-regression-engineering-3668fcd-2026-11-12/acceptance.json).
