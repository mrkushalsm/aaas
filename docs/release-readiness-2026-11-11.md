# Local publication readiness — 2026-11-11

This report describes the current source tree and the existing local engineering
bundle separately. It is not approval to publish either one.

## Current source checks

- Repository branch: `master`; source changes are committed through `e6998d3`; current release documentation is being finalized on that source revision.
- Python regression suite: **554 tests run: 548 passed, 6 skipped** on the current worktree.
- Focused bundle-provenance tests: **11 passed** after correcting how future manifests classify generated installer wrappers.
- M1A native presenter rebuild/test, Python compileall, shell syntax, and `git diff --check` passed. The M1A build used the render node selected by the host capability probe.
- Documentation inventory covers **98 Markdown/license-named files**. The audit records **42 corrected files**, 12 current operational/release documents reconciled against code/tests/evidence, and 354 local Markdown links checked with zero broken links. Historical records remain labeled as historical.
- All tracked JSON/JSONL evidence files parse successfully (271 checked). Tracked documentation and result records now use generic placeholders for local home/workspace paths and host storage identifiers; the Git history is unchanged and still contains historical host-specific values. The original `aaas-runtime.service` is active; `aaas-portable status` reports Android `RUNNING` from installation `$AAAS_INSTALLATION/rootfs`.

Evidence: [`documentation audit`](release/documentation-audit-2026-11-11.json),
[`candidate SBOM`](release/sbom-engineering-52926e6.json), and the
[machine-readable local acceptance record](release/local-prepublication-acceptance-52926e6-2026-11-11.json).

## Existing engineering bundle

- Name: `engineering-42ae1e4`
- Bundle ID: `52926e6cb5e54766918af1a4dd7b0ec7`
- Path: `$XDG_DATA_HOME/aaas-release-artifacts/engineering-42ae1e4`
- Source revision recorded by the bundle: `42ae1e4932f828d75f7c50d21c999d9d82300eb7`
- Manifest SHA-256: `dc181f591a4a54316fe733853d61b200937a3708681aaab691d580a4a0326834`
- Integrity: **PASS**, 6,991 manifest entries.
- Declared runtime closure: **PASS**, 24 inputs checked, no missing inputs.
- The bundle verifier also reports `general_runtime_start: BLOCKED` and `runtime_security: NOT_APPROVED`.
- Bundle contents do not include source changes committed after `42ae1e4`; they have not been rebuilt in this publication-preparation pass.

The candidate-specific SBOM hashes all 5,293 regular files, but does not establish
redistribution rights. Its provenance records remain incomplete: 1,965 of 1,982
executable/library rows have unverified provenance, all 1,982 license reviews
are unreviewed, and 3,311 other regular files are `NOASSERTION`.

## Candidate runtime evidence and open acceptance

The evidence available for this bundle includes a pristine first boot and
subsequent restart for isolated installation C, and earlier application-window
and ARM-translation observations. Installation B had an intermittent
SurfaceFlinger failure during pristine first boot. Its cause remains unknown;
the successful C run does not establish reliable first boot across installations.

The following are **not verified for this exact bundle** in the available
candidate-specific evidence: fresh-install repetition, exact-candidate update
and rollback, five lifecycle cycles, installed-candidate Android audio, and
installed-candidate Android DNS/HTTPS. Prior audio/network tests and update/
rollback evidence belong to a different candidate (`engineering-7226838`, ID
`fd386b95a7a949de9da3bb18c88e5c64`) and must not be attributed to this bundle.

Other historical candidate evidence is indexed in
[`acceptance-2026-11-11.json`](release/acceptance-2026-11-11.json); that record
explicitly concerns the older `fd386b95` bundle and is not acceptance evidence
for `52926e6c`.

## Security and redistribution

- Runtime security: **NOT APPROVED**. The bundle uses Android SELinux
  compatibility shims; enforcement and untrusted-APK isolation are not approved.
- AaaS source license: **absent**. No project-level `LICENSE` grants rights to
  publish AaaS-authored source.
- Binary redistribution: **NOT CLEARED**. Android image and third-party
  provenance/license obligations are unresolved. The candidate SBOM marks no
  files cleared for redistribution.
- Git history contains historical host paths and hardware identifiers. History
  was not rewritten; no full-history sanitization has been performed.
- No Git remote is configured, and no push or release upload was attempted.

The component inventory in [`dependencies-and-licenses.md`](dependencies-and-licenses.md)
and the SBOM are technical tracking artifacts, not legal approval. Do not publish
the source or binary bundle until the project license is authorized and the
binary rights/provenance review is complete.

## Decision

**AAAS NOT YET READY TO PUBLISH.** Source-level tests and documentation checks
pass, and the local bundle passes integrity and declared dependency closure.
The bundle's runtime-start and security gates are not approved; several
candidate-specific live gates remain unverified; the bundle predates current
source changes; and source/binary publication rights are unresolved. The
original installation remains active and reports Android `RUNNING`.
