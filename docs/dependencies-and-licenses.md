# Dependency provenance and redistribution status

**Status: not cleared for binary redistribution or public source publication.** This is an engineering inventory, not legal advice or a grant of rights.

## Current candidate

The latest locally built bundle is `engineering-7226838`, bundle ID
`fd386b95a7a949de9da3bb18c88e5c64`, from source revision
`7226838e908e071d971d37e5a9989f111c72d47d`. Its manifest SHA-256 is
`1d743363858b5836f7364d7d6b67c22cfb190c4eda10dfa6b58e0805f774faa2`, with 6,999 entries and runtime closure PASS (24 checked inputs).
The machine-readable per-file inventory is
[`sbom-engineering-fd386b95.json`](release/sbom-engineering-fd386b95.json).
It records relative bundle paths and hashes, with `NOASSERTION` and
`NOT_CLEARED` where source/license rights are unverified. The candidate was
built while the repository worktree was dirty; it has not passed installed
fresh-boot acceptance.

The manifest has 1,982 executable/library provenance records: 1,846 Android
platform files, 94 retained historical generated workspace artifacts, 25 local
runtime artifacts with unverified acquisition, and 17 AaaS source files. Of
these, 1,965 provenance records are marked unverified; all 1,982 license
reviews are `NOT_REVIEWED_FOR_DISTRIBUTION`. The SBOM includes relative paths
and hashes for 5,296 regular files; the bundle manifest additionally records
all 6,999 filesystem entries, including directories and links.

The Android image is Android 16/API 36, build `BE2A.250530.026.D1`, described as
a historical modified M4 diagnostic rootfs based on an Android SDK image, not a
rebuild from the complete AOSP source graph. The manifest does not include a
complete verified source/license chain for the Android image, vendor
components, Berberis/Digitalis, graphics/audio overlays, helper APKs, and host
utilities.

The artifact-level inventory is useful for tracing each path to a hash. It does
not establish that each artifact's stated origin is correct, that notices are
complete, or that redistribution is permitted. The local engineering bundle
also contains SELinux compatibility shims and is not approved for untrusted
APKs.

### Component-group disposition

The SBOM is a path/hash inventory, not a legally complete SBOM. Its 6,999
manifest entries comprise 5,296 regular files and 1,703 directories or
symlinks. The generated records group the known gaps as follows:

| Group | Count | Recorded identity | Distribution decision |
|---|---:|---|---|
| Android runtime image files | 1,846 | Modified Android 16/API 36 M4 diagnostic rootfs, build `BE2A.250530.026.D1`, local source root `rootfs_m1b1` | Not cleared; SDK package/source URL and per-component license/notice chain are not established. |
| Retained generated workspace artifacts | 94 | Historical M4 runtime/workspace artifacts | Not cleared; generating source inputs and licenses are not recorded. |
| Local runtime binaries | 25 | Local M4 runtime closure | Not cleared; exact upstream origin, source revision, and licenses are missing. |
| AaaS source files in the bundle | 17 | Revision `7226838e908e071d971d37e5a9989f111c72d47d` | Not cleared; there is no AaaS project license grant. |
| Unclassified image/resource files | 3,314 | `NOT_ESTABLISHED` / `NOASSERTION` | Not cleared; no reliable component/source identity is attached. |

The first four groups are the 1,982 executable/library provenance records. All
1,982 have license review `NOT_REVIEWED_FOR_DISTRIBUTION`; the other 3,314
regular-file records have `NOASSERTION`. **Zero of the 6,999 bundle entries
have been approved for redistribution.** The image's Android build ID does not
identify all constituent upstream projects or their applicable terms. Names
such as Berberis, ANGLE, SwiftShader, Mesa, and PipeWire in architecture/build
notes are not evidence that the particular bundled binaries were built from a
known revision or can be redistributed.

## Distribution decisions

| Distribution form | Status | Reason |
|---|---|---|
| Local trusted engineering use | Available with diagnostic/security limitations | Integrity and declared runtime closure pass; use trusted APKs only. |
| Public source publication | Not ready | No root project `LICENSE` grants rights for AaaS-authored source; a license choice/authorization is needed. |
| Full binary bundle | Not approved | Android image and third-party provenance/license obligations are unresolved; runtime security and publisher authenticity are not approved. |
| Reduced binary bundle | Not prepared | No legally cleared, technically complete subset has been assembled and validated. |

No bundled third-party component is counted as cleared for redistribution by
this audit. Resolve component licenses, notices, source-offer obligations,
Android image provenance, and any proprietary terms from authoritative source
records before publication. If the image cannot be redistributed, a lawful
user-side acquisition/build path must be implemented and tested before it can
replace the image in a public installation workflow.

## Source changes after this candidate

The repository source now includes commit
`2a9d97431e051fd2c6c91907133293996d91d719`, which changes the AaaS Wayland
presenter and its tests to retain a window through Android Composer resize
reconnects. The engineering bundle above predates that change and is not the
same artifact as the current source tree. The presenter change does not resolve
the Android-image provenance or third-party redistribution findings. The
resize acceptance record is
[`dynamic-resize-acceptance-2026-11-11.json`](../results/m1a/dynamic-resize-acceptance-2026-11-11.json).

The repository itself has no project-level license file. Do not infer a license
for AaaS code from licenses of upstream dependencies.

## Historical research

The earlier Lipstick/Qt-HWC audit in [`lipstick-m01.md`](lipstick-m01.md) is a
scoped historical source experiment. Its license observations apply only to
that source subset and do not clear the current Android runtime or bundle.
