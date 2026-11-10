# AaaS diagnostic release security review — 2026-11-11

**Result: NOT APPROVED for untrusted APKs or public binary release.** This is a
bounded engineering review of candidate `fd386b95a7a949de9da3bb18c88e5c64`,
not a penetration test or production security certification.

## Findings

| Finding | Severity in intended public/untrusted use | Evidence | Disposition |
|---|---|---|---|
| Android SELinux authorization shim is present | High / release blocker | Bundle manifest lists `rootfs/system/lib64/libselinux_shim.so` and `rootfs/vendor/lib64/libselinux_shim.so`; runtime security is `NOT_APPROVED`. The diagnostic shim substitutes authorization behavior. | Do not run untrusted APKs. Rebuild a supported image with verified SELinux policy enforcement before public/untrusted use. |
| Android SELinux enforcement is not verified | High / release blocker | Candidate manifest says host policy enforcement unavailable/unverified. Static image inspection cannot prove kernel policy load/enforcement. | Requires a SELinux-capable, correctly integrated runtime and live enforcement evidence. |
| Android rootfs and third-party binary provenance/license chain is incomplete | High for redistribution | SBOM covers 5,296 regular bundle files and manifest contains 1,982 executable/library provenance rows; 1,965 provenance rows are unverified and all 1,982 license states are `NOT_REVIEWED_FOR_DISTRIBUTION`. | Public binary redistribution blocked. Obtain authoritative source/build/license records or use a lawful tested acquisition workflow. |
| Bundle publisher authenticity is not established | High for downloaded updates | Bundle manifest hash verifies integrity relative to the manifest, but no publisher signature/verified trust anchor is present. | Do not treat a checksum as publisher authentication. A signed release/update trust chain remains required. |
| Project source has no root license grant | Release blocker for source publication | No root `LICENSE` exists; third-party licenses do not license AaaS-authored files. | Project owner must select/authorize a license before public source publication. |
| Runtime exposes user-session integration endpoints | Medium, trust-boundary limitation | The runtime binds Wayland/PipeWire/user-session interfaces to integrate windows/audio; this is not isolation from a malicious host-session workload. | Treat installed apps as trusted. No claim of a hostile-app sandbox. |

## Controls observed

- Android runs through rootless user/mount/PID/network namespace setup with
  Bubblewrap and a per-user systemd service.
- Network forwarding uses rootless virtual Ethernet/slirp4netns; physical host
  Wi-Fi remains host-managed.
- Per-install helper signing material is stored outside the bundle in private
  XDG state; the distributable bundle excludes private signing keys.
- Bundle/update code verifies manifests and immutable installation hashes and
  retains a previous installation for rollback. Unsigned bundle metadata still
  does not authenticate the publisher.
- The one-time 1 GiB reserve exception used for this user's disposable update/
  rollback test was scoped to `aaas-m5-final-test.service`, removed afterward,
  and did not change source or global systemd environment.

## Verification and residual risk

The final candidate manifest reports `DIAGNOSTIC_ONLY`,
`general_runtime_start=BLOCKED`, `runtime_security=NOT_APPROVED`, and
`untrusted_apks=NOT_APPROVED`. The candidate did start and run trusted test apps
under the explicit local diagnostic service during update acceptance. That
functional result does not approve the security boundary. Do not publish or
recommend this image for untrusted APKs, multi-user isolation, or production.
