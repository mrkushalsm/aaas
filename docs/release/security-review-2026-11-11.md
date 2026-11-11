# Diagnostic candidate security review — 2026-11-11

**Result: NOT APPROVED for untrusted APKs or public binary release.** This is a
bounded engineering review of bundle `engineering-42ae1e4`
(`52926e6cb5e54766918af1a4dd7b0ec7`), not a penetration test or production
security certification.

## Findings

| Finding | Severity | Evidence | Disposition |
|---|---|---|---|
| Android SELinux enforcement is unavailable/unverified in the diagnostic runtime; SELinux authorization compatibility shims are present. | High for untrusted workloads | Candidate manifest reports `runtime_security=NOT_APPROVED`; the bundle includes `rootfs/system/lib64/libselinux_shim.so` and `rootfs/vendor/lib64/libselinux_shim.so`. | Do not use untrusted APKs. A supported enforcing image and live policy-enforcement evidence are required. |
| Bundle publisher authenticity is not established. | High for remote update use | Manifest/hash verification checks integrity relative to supplied metadata; no signed publisher trust chain is established. | Do not treat a checksum as publisher authentication. |
| Runtime start approval is blocked. | Release blocker | Exact candidate verification reports `general_runtime_start=BLOCKED`, despite isolated installation evidence of Android reaching RUNNING. | Resolve the supported startup/health gate before calling the candidate release-ready. |
| Android image and third-party provenance/license chain is incomplete. | High for redistribution | Candidate SBOM covers 5,293 regular files; 1,965 of 1,982 executable/library rows have unverified provenance, all those license reviews are unreviewed, and 3,311 other files are `NOASSERTION`. | Public binary redistribution is not cleared. Establish authoritative source, build and license records or a lawful tested acquisition path. |
| AaaS-authored source has no project license grant. | Blocker for source publication | No root project `LICENSE` exists. | Project owner must authorize a license before source publication. |
| Historical Git history contains host-specific paths and hardware identifiers. | Privacy concern for source publication | Current working files were scrubbed; historical commits were not rewritten or fully sanitized. | Review history before publishing; do not rewrite it without authorization. |
| Host session integration is exposed to the trusted runtime. | Medium trust-boundary limitation | The runtime uses user-session Wayland/PipeWire and other integration endpoints. | Treat installed apps as trusted; this is not a hostile-app sandbox. |

## Controls observed in source and candidate

- The runtime uses rootless user, mount, PID, and network namespace setup with
  Bubblewrap and a per-user systemd service.
- Network forwarding uses rootless virtual Ethernet/slirp4netns; the physical
  Wi-Fi device remains host-managed.
- Per-install helper signing material is stored in private XDG state and is
  excluded from the bundle.
- Bundle/update code validates manifests and immutable installation hashes and
  retains a prior generation. Hash verification does not establish publisher
  identity.

These are source and artifact observations, not a substitute for adversarial
security testing. Update/rollback evidence for the older `engineering-7226838`
candidate must not be attributed to this candidate.

## Decision

The exact candidate verifier reports `general_runtime_start=BLOCKED` and
`runtime_security=NOT_APPROVED`. The bundle is suitable only for local trusted
development under its documented limitations. Do not publish it as a public
binary or recommend it for untrusted APKs, multi-user isolation, or production.

Current source changes after this bundle include portability and resize work;
they have not been rebuilt into this candidate. See the
[release-readiness record](../release-readiness-2026-11-11.md) and
[candidate SBOM](sbom-engineering-52926e6.json).
