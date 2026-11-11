# Runtime security review — candidate `d3d7278094324b93be4f3ad57ae5883d` — 2026-11-11

**Result: NOT APPROVED for untrusted APKs, public binary release, or hostile multi-user use.** This is a bounded source/artifact review, not a penetration test or certification.

| Finding | Severity | Evidence | Status |
|---|---|---|---|
| SELinux enforcement is unavailable/unverified; compatibility shims exist in the diagnostic image. | High for untrusted workloads | Bundle `rootfs` contains SELinux shims; installation metadata reports `runtime_security=NOT_APPROVED`. | Open; only trusted local APKs. |
| Bundle integrity metadata has no publisher authentication chain. | High for remote update trust | Manifest integrity passes, but bundle is locally unsigned. | Open; checksum does not authenticate publisher. |
| Android base image provenance is incomplete. | High for redistribution | Historical modified M4 diagnostic rootfs, not rebuilt from the full pinned Android source graph; per-file inventory has `NOASSERTION` licenses. | Open; binary redistribution not cleared. |
| Host desktop/audio/network endpoints are deliberately integrated with the runtime. | Medium trust-boundary limitation | Wayland, PipeWire, and slirp integration are available to trusted runtime processes. | Documented; not a hostile-app sandbox. |
| External development volume has suspected device/I/O faults. | Operational | Workspace health ledger records USB/UAS and block-I/O errors. | Writes suspended; candidate and test install are on root filesystem. |

## Controls observed

- Rootless user, mount, PID, and network namespace setup with Bubblewrap and a per-user systemd service.
- Network forwarding through virtual Ethernet and slirp4netns; Android does not own the physical Wi-Fi device.
- Per-install signing identity is kept in private XDG state and excluded from the bundle.
- Manifest hashes detect content drift relative to the manifest, not a malicious or substituted manifest.

## Decision

Use only in a trusted local development context. Do not publish the bundle or recommend it for untrusted APKs. Security approval remains open. See [candidate readiness](../release-readiness-2026-11-11.md) and [the bundle inventory](../../results/release/sbom-engineering-d3d72780.json).
