# Android 16 SDK rootfs reconstruction

## Purpose and safety boundary

`scripts/assemble_android_rootfs.py` assembles a **new, incomplete** rootfs from
the repository's retained Android 16 SDK image. It does not start Android,
install userdata, copy from `rootfs_m1b1`, or make the candidate provisionable.
The candidate status is `ASSEMBLED_INCOMPLETE`, its runtime-ready flag is
false, and the production CLI continues to reject it.

The supported input is Android 16/API 36/x86_64 SDK package revision r02,
build `BE2A.250530.026.D1`. Its retained archive is matched by size and the
recorded SHA-1; the manifest's SHA-256 was measured locally and is not claimed
as a Google-published checksum. The assembly verifies both digests before
reading the image.

## Build

Enroll and validate the workspace using the normal setup flow, then run:

```sh
aaas images build android16-ranchu-x86_64 --dry-run
aaas images build android16-ranchu-x86_64
```

An alternate verified archive may be supplied using `--image PATH`. The
command checks workspace health and the configured storage budget before
writing. It reuses partition caches only after verifying them against the LP
extents in the source `system.img`. Existing output candidates are never
overwritten. A previous staging directory is removed only when its marker
proves it was created by this exact assembler for the same profile and source
archive; removal runs under the mapped user namespace so Android-owned files
remain removable without host privilege.

The output is under the configured workspace:

`rootfs-candidates/android16-ranchu-x86_64/BE2A.250530.026.D1/`

It contains `rootfs/`, `manifest.json`, `file-inventory.jsonl`, the extracted
ramdisk inventory, and compressed source-partition archives. The system
partition is system-as-root and is materialized at the candidate root. The
other dynamic partitions are materialized at their named mountpoints. The
Android ramdisk's `init` replaces the image's `/init` symlink; device nodes
are recorded but omitted for session-time creation.

Partition exports preserve numeric UID/GID, POSIX ACLs, generic xattrs, and
SELinux labels in the retained source tarballs. Files are materialized in a
subordinate-ID user namespace. Since the current host has no SELinux LSM, the
candidate tree does not receive `security.selinux` xattrs. It must not be
executed as if those labels had been restored.

## 2026-11-08 assembly evidence

The first candidate was assembled from the verified archive and the five LP
partitions (`system`, `system_ext`, `product`, `vendor`, `system_dlkm`). All 16
modified critical-file base hashes in the historical audit matched the clean
SDK partition contents; the separate stock SurfaceFlinger finding remains
byte-identical in the source audit. Candidate inventory: 4,347 entries and
1,621,372,225 logical bytes for regular and hard-linked partition files.
The candidate occupies approximately 2,393,317,376 allocated bytes. Its
manifest records each partition and tarball SHA-256, the full source archive
identity, file-inventory SHA-256, SELinux-label preservation count, and missing
runtime components.

The independent transformation map is
[`android16-reconstruction-transformations.json`](../manifests/android16-reconstruction-transformations.json).
It records the 16 historical critical changes and the modified SwiftShader
checkout. Historical evidence identifies the diagnostic `apexd` wrapper as a
status-property stub and the diagnostic `vdc` as a 24-byte exit-0 stub. The
candidate excludes both changes and retains stock binaries. M1D's correction
uses the verified stock `vdc` through a read-only per-session overlay. The
other critical binary/init changes and SwiftShader edits remain unresolved;
their diagnostic outputs are not copied. Both known SELinux success shims are
excluded. No APEX activation is inferred from extracted payloads or status
properties.

The candidate's Android build properties and required-file paths match the
profile, and the 16 critical original hashes verify. The profile inspector
checks the pinned source identity, transformation-map hash, critical-file
summary, and inventory-file hash. This validates the assembly record only; it
is not a signed image attestation and does not recalculate all rootfs file
hashes. This is structural image acceptance only. APEX activation, SELinux
enforcement, rootless runtime containment, exact-image graphics
allocator/mapper/Composer compatibility,
Native Bridge, audio, desktop helpers, and live Android startup remain
unverified. Do not use `aaas start` or install applications into this
candidate.

## Evidence and tests

The machine-readable assembly observation is
[`results/m6/android16-rootfs-assembly-2026-11-08.json`](../results/m6/android16-rootfs-assembly-2026-11-08.json).
The retained candidate is outside Git and is intentionally not a release
artifact. M4's historical `PASS/CLOSED` status is unchanged; the portable
runtime foundation and independently runnable Android 16 rootfs remain
`PARTIAL/OPEN`.

## First-boot preflight

`aaas debug boot --candidate PATH --json` performs a read-only, candidate-bound
preflight. It checks workspace enrollment/health, candidate identity, assembly
record validity, profile compatibility, known SELinux bypass artifacts, the
host SELinux policy interface, and declared missing components. It never
launches Android, mounts APEX images, creates a session, or falls back to
`rootfs_m1b1`. A nonzero exit means the candidate is blocked; `launch_permitted`
is always false until a separately validated runtime profile and launcher
exist.

On 2026-11-08 the preflight reported `SECURITY_BLOCKED`: the assembly record,
profile, workspace health, and static bypass scan passed, while the host had
LSMs `capability,landlock,lockdown,yama,bpf` and no SELinux policy-load
interface. APEX activation was unverified and the exact-image graphics
allocator/mapper/Composer stack was missing. No Android process was started.
Historical M1B evidence in `docs/m1b4-runtime-decision.md` records the stock
ServiceManager abort at `selinux_status_open`; that is diagnostic history, not
a new test of this candidate. The preflight deliberately refuses to turn that
failure into a successful boot by adding an authorization shim.
