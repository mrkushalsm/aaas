# Provenance, licensing, and redistribution readiness

**Status: source licensing and binary redistribution are unresolved. The
engineering bundle is not approved for public redistribution.** This is an
engineering inventory, not legal advice or a grant of rights. It does not
replace review by the project owner and, where needed, counsel.

## Candidate under review

This report covers the immutable local candidate `engineering-af3dcb4`, bundle
ID `43d04579ec874746a7c9da5152419bd6`, source revision recorded as
`af3dcb4711d13197826942f0a1c7f2b1698589ec`, 8,795 manifest entries, manifest
SHA-256
`d638937b4bcb16f550b2e204175c70ec247190ca10b6e7229447560909db2a64`.
Integrity and runtime dependency closure passed (26 declared inputs). The
manifest classifies the bundle as `LOCAL_DEVELOPMENT_DIAGNOSTIC` and says
authenticity is not established. It also records `source_tree_dirty_at_capture`
as true. The acceptance result does not establish legal redistribution rights.

The machine-readable component inventory is
[`sbom-engineering-af3dcb4.json`](release/sbom-engineering-af3dcb4.json). It
maps every executable/library provenance row to a bundle-relative path and
SHA-256, and links the whole-file manifest digest above. It intentionally marks
unreviewed items unresolved instead of assigning a license by guesswork.

## Material component assessment

| Component | Evidence/origin | License evidence | Source redistribution | Binary redistribution | Open issues |
|---|---|---|---|---|---|
| AaaS-authored source | Repository history and tracked source | No project-level `LICENSE`; a few individual audio files carry SPDX MIT identifiers | No blanket grant exists. Public visibility alone does not grant reuse rights. | Not applicable as a separate bundle component; bundled copies still require provenance review | Owner must select and authorize a project license; identify any adapted/copied code and preserve notices |
| Android 16/API 36 image | Manifest: Android 16 build `BE2A.250530.026.D1`, based on historical SDK system image `system-images;android-36;default;x86_64`, revision r02; modified diagnostic rootfs | Android platform components have varied upstream licenses. Android licensing documentation says most AOSP is Apache-2.0 but exceptions exist. Google SDK terms separately cover SDK packages and system files. | Not cleared: the complete source/build graph and file-level attribution are absent | Not cleared | Confirm applicable SDK/system-image terms, image acquisition rights, modification rights, trademarks, and exact per-file origins. See [Android SDK terms](https://developer.android.com/studio/terms) and [AOSP licensing](https://source.android.com/license). |
| Modified Android/rootfs binaries | Bundle manifest and `manifests/android16-diagnostic-rootfs-audit.json`; 16 modified base files, 1 unchanged base file, shim overlays, locally modified SwiftShader checkout entries | Per-file licenses not mapped in the candidate; rootfs provenance is `UNVERIFIED_PROVENANCE` | Not cleared | Not cleared | Establish transformation and source for each material file; identify vendor/proprietary components and required source/notice obligations |
| Digitalis / Berberis translation components | Embedded Digitalis tree, internal manifest and source revisions; translation source points to Digitalis/Refract lineage | The inspected Digitalis upstream checkout has an Apache-2.0 license; embedded NOTICE describes Digitalis/Berberis components as Apache-2.0. The related Refract source repository is GPL-3.0-or-later and its NOTICE has attribution language while stating third-party prebuilts retain their own terms. | Source-specific terms may permit source use subject to their conditions; exact embedded modifications and obligations need reconciliation | Not cleared as bundled: no complete binary file-to-license review; expected Apache license/NOTICE packaging is incomplete in the embedded tree | Map each shipped prebuilt to exact upstream source/revision and applicable license. Reconcile Refract modifications, Apache components, guest libraries, and notices. Sources: [Digitalis project](https://github.com/DigitalisX64/digitalis) and [Refract repository](https://github.com/Refract-Foundation/Refract). The exact source revisions must be checked against the candidate before relying on upstream terms. |
| Android guest libraries and apps | 1,844 Android platform executable/library/app rows in candidate provenance | All candidate executable/library rows have `NOT_REVIEWED_FOR_DISTRIBUTION`; 1,965 rows overall are marked `UNVERIFIED_PROVENANCE` | Not cleared | Not cleared | Resolve upstream project, exact revision, license, notices, source offer, vendor status, and modification status per component |
| Runtime helpers and AaaS installer | Candidate records 44 host runtime code/executable rows, 2 installer wrappers, and 1 compatibility preload in its provenance summary; individual provenance entries are retained in the SBOM | Candidate rows remain `NOT_REVIEWED_FOR_DISTRIBUTION`; some are AaaS source, others pinned third-party tools | No AaaS project license; third-party terms require individual review | Not cleared as a complete package | The candidate's top-level source revision is `af3dcb4`, but installer provenance rows cite `71105b7` with a dirty worktree. Reconcile the build capture and exact source for every copied artifact |
| Slirp4netns, compiler/toolchain, and host libraries | Runtime closure lists 26 host-provided inputs; `slirp4netns` is described as pinned/hash-verified; several tools/libraries remain host dependencies | Candidate dependency-closure metadata is not a complete license report | Depends on each upstream item | Not all are bundled; no blanket conclusion applies | Record exact versions, hashes, upstream license texts, and redistribution obligations before packaging any of them |
| Generated overlays and helper APKs | Candidate runtime closure says overlays are re-extracted and helper APKs rebuilt from packaged inputs | Generated status does not remove upstream license obligations | Not cleared until all inputs are assessed | Not cleared | Trace generators and inputs, including Android platform-derived resources and embedded notices |

### Evidence limits

The candidate contains 1,985 executable/library provenance rows. All 1,985
have `license_review=NOT_REVIEWED_FOR_DISTRIBUTION`; 1,965 have unverified
provenance. Source URLs and license identifiers are not populated consistently.
The source revision is marked dirty at capture, and provenance rows for some
installer/runtime artifacts cite an earlier revision. The Android rootfs is
explicitly unverified and is not rebuilt from a complete materialized AOSP
source graph. The separate [Android source lock](android-source-lock.md) is a
research/pin record, not a complete build lock for this candidate.

Repository `sources/` trees and their upstream license files are ignored local
material, not tracked source files and not proof that corresponding sources or
licenses are included with the candidate. Historical license research applies
only to the named subset; it does not clear the accepted bundle.

## Tracked source-code license signals

The tracked repository has no top-level `LICENSE`, `COPYING`, or `NOTICE` file.
The scan found 36 tracked files with Android Open Source Project copyright
attribution, including JNI, Binder/AIDL, graphics, and audio headers. Thirty
eight files contain the Apache-2.0 license header text. Those file-level notices
must be retained; they do not license adjacent AaaS-authored files or the whole
repository. Three AaaS audio implementation files carry SPDX `MIT` identifiers.
Two tracked SwiftShader patch files contain SwiftShader copyright references,
and the tracked `linux-drm-syncobj-v1.xml` protocol includes its upstream
copyright and permission terms. A further Wayland protocol XML file is also
tracked. The exact upstream revisions and whether each patch contains
copyrightable upstream expression need review before treating source
redistribution as cleared.

Relevant upstream references include [AOSP source licensing](https://source.android.com/license),
[Android platform source](https://android.googlesource.com/platform/),
[Wayland protocols](https://gitlab.freedesktop.org/wayland/wayland-protocols),
and [SwiftShader](https://github.com/google/swiftshader). The tracked notices
are evidence for the individual files; the exact origin and applicable terms
for every imported/adapted portion remain to be reconciled. Tracked experiment
source is not necessarily included in the accepted runtime bundle.

## Distribution decision

1. **Can the complete source tree be published with an open-source license?**
   Not as an owner-authorized open-source release yet. There is no project-wide
   license grant. The owner must choose and authorize one, after a code-origin
   review. Do not infer permission from individual third-party licenses.
2. **Can the full binary bundle be distributed?** No. The Android image,
   modified platform/vendor files, Digitalis/Berberis payload, and other
   executable/library rows lack complete provenance and rights review.
3. **Is a reduced binary cleared?** No reduced, technically complete package
   has been assembled and assessed.
4. **Can source-only distribution work meanwhile?** The repository can be made
   visible, but without a project license recipients receive no general
   permission to copy, modify, or redistribute AaaS-authored code. The current
   history also contains older machine-specific paths and identifiers; assess
   that exposure before public publication without rewriting history silently.
5. **What is needed next?** Owner-selected project license; source-origin
   audit; exact bundle provenance reconciliation; per-component license and
   notice review; resolution of Android SDK/system-image terms; and legal review
   of any uncertain terms. Until then, do not attach or advertise the bundle as
   a public download.

The Android project describes AOSP as mostly Apache-2.0 with component
exceptions; this does not itself grant rights to a Google SDK system image or
every Android/vendor binary. Google's SDK terms separately govern SDK packages
and system files and contain restrictions and an open-source-component
exception; their application to this modified diagnostic image needs qualified
review. These documents are linked as evidence, not interpreted here as legal
approval.

## Possible AaaS project-license choices for the owner

No choice has been made or applied.

| License | Practical effect | Fit and tradeoff |
|---|---|---|
| MIT | Permissive reuse with copyright/license notice | Simple for broad reuse, but provides no express patent grant and may be less explicit about patent rights |
| Apache-2.0 | Permissive reuse, express patent grant, NOTICE handling | Strong fit for a developer tool with contributors; requires preserving notices and addressing patent termination terms |
| GPL-3.0-or-later | Copyleft for distributed derivative works, with source/license obligations | Better if the owner wants downstream derivatives to remain under reciprocal terms; may constrain integration and redistribution choices |

These options apply only to AaaS-authored material after an origin review; they
do not override third-party terms or clear the bundled Android image.

## Required release actions

- Obtain the owner's explicit project-license decision.
- Reconcile candidate capture revision, dirty state, and per-row provenance.
- Review all 1,985 executable/library records and their corresponding notices.
- Determine whether a lawful user-side image acquisition/assembly workflow is
  possible and implement/test it before distributing a bundle that depends on
  the image.
- Keep public binary distribution disabled until the full dependency closure is
  cleared and a reviewer approves the notices and obligations.

See also the [candidate release notes](release/v0.1.0-dev-preview.md),
[M5 acceptance record](release/portable-preview-af3dcb4-acceptance.json), and
[architecture guide](architecture.md).
