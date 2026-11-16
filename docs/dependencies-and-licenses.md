# Provenance, licensing, and distribution plan

**Status: no project-wide license has been authorized; the accepted binary is
not cleared for public redistribution; user-side image assembly is not yet a
supported installation route.** This is an engineering evidence report, not
legal advice. Questions about the Android SDK agreement and uncertain imported
code require review by the rights holders or qualified counsel.

## Scope and preserved release

This review covers source files tracked by this repository and the immutable
M5 developer-preview candidate `engineering-af3dcb4`:

| Identity | Recorded value |
|---|---|
| Bundle ID | `43d04579ec874746a7c9da5152419bd6` |
| Artifact count | 8,795 |
| Manifest SHA-256 | `d638937b4bcb16f550b2e204175c70ec247190ca10b6e7229447560909db2a64` |
| Recorded source revision | `af3dcb4711d13197826942f0a1c7f2b1698589ec` |
| Recorded source worktree state | Dirty, without a complete dirty-file snapshot |

The bundle and `v0.1.0-dev-preview` tag were not modified. Integrity and
dependency closure are engineering checks; they do not establish copyright
ownership or redistribution rights. The detailed SPDX 2.3 inventory is
[`sbom-engineering-af3dcb4.json`](release/sbom-engineering-af3dcb4.json). Its
`NOASSERTION` values are intentional: the SBOM is not a license grant.
The grouped record counts and matching criteria are also available in the
[machine-readable component groups](release/component-groups-engineering-af3dcb4.json).

## Source ownership boundary

The tracked source tree contains no top-level `LICENSE`, `COPYING`, or
`NOTICE`. Therefore, there is no blanket permission to use, modify, or
redistribute AaaS-authored code. Publicly visible source is not necessarily
open-source licensed.

The repository scan found these concrete signals:

| Group | Evidence | Release handling |
|---|---|---|
| AaaS-authored source | Most project scripts, native integration, tests, and documentation appear authored in this repository; this is an origin assessment, not proof of copyright ownership | Owner must license material they own; review contributor/employer ownership before applying a project license |
| AaaS audio files with SPDX | `experiments/m4/audio/audio_hal.c`, `audio_protocol.h`, and `ashmem_compat.c` explicitly say MIT | Retain their headers; do not assume the rest of the project is MIT |
| AOSP-attributed/imported source | 36 tracked files contain AOSP attribution; 38 contain Apache-2.0 header text, including Binder/JNI/audio/graphics interfaces | Keep per-file notices and verify each file's source and modifications; AOSP itself says Apache-2.0 is preferred but exceptions exist |
| SwiftShader patches | Two tracked patch files mention SwiftShader copyright | Trace patch origin and preserve upstream notices; no project-wide license inferred |
| Wayland protocol descriptions | `experiments/m1a/protocols/linux-drm-syncobj-v1.xml` has upstream copyright and permission terms; `viewporter.xml` is also upstream protocol material | Preserve source headers and record exact upstream version/terms |
| Generated source and local ignored sources | `sources/` and other ignored local inputs are not Git-tracked and are not established as part of source redistribution | Do not publish these as project source without a separate origin and license review |
| Unknown/adapted files | Some history and file headers do not establish whether material is original, copied, or adapted | Keep unresolved; inspect origin before licensing or publishing those files |

The [AOSP licensing guide](https://source.android.com/docs/setup/contribute/licenses)
says most Android software uses Apache-2.0 but identifies exceptions and says
individual file headers matter. That is useful context, not a blanket license
for all files bearing Android-related names. Repository history also contains
older machine-specific paths and identifiers; public source preparation should
review the existing history for privacy before publication. This report does
not rewrite history.

### Project license recommendation — owner decision required

No license has been added. For original AaaS-authored files, **Apache-2.0 is
the recommended default**, contingent on ownership review and the owner's
explicit approval. It grants an express patent license and is familiar in the
Android/Linux tooling ecosystem. It also requires preserving notices and
handling any `NOTICE` obligations. It will not relicense imported files or
clear the Android image.

| Choice | Tradeoff for AaaS-authored files |
|---|---|
| Apache-2.0 (recommended) | Permissive reuse with an express patent grant; clear notice and attribution duties; fits a tool likely to receive contributions |
| MIT | Short, permissive terms and simple attribution; no express patent grant comparable to Apache-2.0 |
| GPL-3.0-or-later | Copyleft obligations on covered derivative distributions; suitable if the owner wants reciprocal terms, but can complicate combining and redistributing the mixed-license runtime |

The owner must choose the project license and confirm they have authority to
license the original contributions. A maintainer must not make that choice by
adding a license file unilaterally.

## Accepted bundle: grouped provenance assessment

The SBOM has 1,985 executable/library records. It marks 1,965
`UNVERIFIED_PROVENANCE` and all 1,985 `NOT_REVIEWED_FOR_DISTRIBUTION`. The
1,965 records are **not 1,965 independent legal issues**; they cluster as
follows. Paths and SHA-256 values remain traceable in the SBOM and immutable
bundle manifest.

| Group | Records | Best-supported origin | License / redistribution status | Remaining work |
|---|---:|---|---|---|
| Android image executable, library, and app files | 1,844 | Android 16/API 36 x86_64 SDK package `system-images;android-36;default;x86_64`, revision `r02`, archive `x86_64-36_r02.zip`, build `BE2A.250530.026.D1`; the accepted rootfs is historically modified | Mixed Android/AOSP and possibly vendor/package terms. Not cleared as a group or file set | Map each shipped file to upstream source/license and modifications; identify proprietary content; collect notices and any source-offer duties |
| Generated workspace compatibility/helper artifacts | 94 | Candidate calls these “retained historical M4 generated workspace artifact”; 91 paths are under `tmp`, 3 under `sources`; this label does not prove origin | Mostly unresolved. Some subset is Digitalis/Berberis; other helpers, overlays, APKs, libraries, and tools need exact mapping | Split by actual component and hash, link to source/build inputs, preserve license texts, determine whether generated outputs include third-party code |
| Untracked local runtime outputs | 27 | Candidate calls these local runtime artifacts from the M4 closure; exact source path is not recorded in the old manifest | Unknown until linked to reproducible build inputs; not cleared | Map each path/hash to its producer, source revision, build recipe, and license |
| Tracked runtime source rows | 17 | AaaS checkout; each recorded file hash matches its content at both `71105b7` and `af3dcb4` | Mixed AaaS and upstream headers; no blanket project license | File-level origin and licensing review remains |
| Bundle installer wrappers | 2 | Generated by the AaaS release builder | AaaS source ownership likely, but no project license; old source identity is inconsistent | Correct future capture metadata; do not infer an earlier builder revision from this field |
| Compatibility preload | 1 | Generated from `experiments/m1b/selinux_xattr_compat.c` by `scripts/build_android_selinux_xattr_compat.py` | Source license/ownership follows source file and its included headers; candidate row is not a rights review | Include source, notices, and exact toolchain/build record in any redistributable package |

### Named third-party components

| Component | Evidence and license evidence | Bundle status / action |
|---|---|---|
| Digitalis / Berberis | The retained package has a SHA256SUMS file whose 74 entries verified locally. M3 evidence records Digitalis `a6edb72029cd25cb616bdee1a12b2d64e3a6a3ae`, translator repository revision `9e7f4407e0e32a582fe2a56f87492443ca55d6fa`, and translator artifact SHA-256 `13821f9b70146e843d1c0e3cb28fc085d06cb5a51ecfec7299f97a67ba31301a`. It records the Refract revision string `ddef6e6ae7de37dd3e4006d07d3f18cb21a0ebc`, which is 39 hex characters and therefore not a complete SHA-1 object ID. Embedded NOTICE describes Digitalis/Berberis as Apache-2.0. The associated [Refract repository](https://github.com/MIXIDtheSilly/Refract) is GPL-3.0-or-later, while its notice says third-party prebuilts retain their own terms. | 74-file checksum validity confirms file identity only. Exact component-to-bundle mapping, modifications, applicable terms, and required license texts still need review. The embedded Digitalis directory lacks a top-level Apache license text; include appropriate license/NOTICE materials if distribution is authorized. Do not assume Refract's source license automatically determines every prebuilt's license. |
| SwiftShader | Tracked patch references and the Android rootfs audit identify 11 locally modified SwiftShader checkout entries | Exact upstream commit, patch set, binaries, build flags, and notices are not fully connected. Not cleared as bundled. |
| Android SDK image and emulator vendor files | The image manifest identifies an official SDK package and build; the rootfs audit records 16 modified base files, one unchanged base file, two known SELinux shim overlays, and locally modified SwiftShader entries | The image is not a clean AOSP build. Per-file rights and modification basis are unresolved; do not redistribute it. |
| Host tools/libraries, APKs, overlays, and audio/network helpers | Candidate closure and workspace manifest identify files, but the SBOM does not consistently identify exact upstream releases/license files | Review each material component before including it in a public binary or source archive. Host-provided dependencies still need documentation and provenance, but are not automatically bundled. |

Ignored local `sources/` checkouts and their license files are useful research
evidence only. They do not show that those exact sources generated the accepted
artifact. The 74-entry Digitalis checksum result likewise establishes
integrity, not the right to redistribute.

## Android image terms and acquisition

The recorded base is Google SDK package
`system-images;android-36;default;x86_64`, revision `r02`, build
`BE2A.250530.026.D1`. Its archive was recorded as 844,217,077 bytes, with
SDK-index SHA-1 `829c076e8ff448a336097ae25a355b495ba36e2c`. SHA-256
`e1b9d9fb665001ef27b16e57d8762a2d54aec6bff617e17506edb8676667b9da` was
measured locally; Google did not publish that SHA-256 in the evidence reviewed.
The source package's historical availability does not itself grant permission
to republish the archive or modified contents.

The current [Android SDK agreement](https://developer.android.com/studio/terms)
defines the SDK to include Android system files. It says SDK use is licensed
for developing apps for “compatible implementations” (defined there by the
CDD and CTS), restricts copying/modifying/redistributing SDK material except
where third-party open-source terms require otherwise, and gives open-source
components their own governing licenses. The AaaS diagnostic image is modified
and has not been shown to meet CDD/CTS compatibility. Applying these terms to
this project's particular use and modifications requires legal review; this
report does not decide that question.

Keep these cases distinct:

1. **AOSP source:** published Git projects carry component-specific licenses.
   AOSP documentation says a Cuttlefish build can run directly, while
   device-specific proprietary binaries are separately obtained and licensed.
   AOSP source availability does not establish that the accepted SDK image is
   redistributable.
2. **Self-built AOSP binaries:** rights follow the source components and any
   separately acquired vendor binaries; the build's exact source manifest,
   notices, and outputs still need review. A clean AOSP/Cuttlefish build is not
   technically equivalent to the accepted rootless AaaS runtime.
3. **Google prebuilt SDK system image:** the SDK agreement applies to SDK
   packages and system files; a local download does not by itself establish a
   right to redistribute, modify, or use it for this runtime.
4. **User-side download:** requiring users to accept terms through official
   Android SDK tooling avoids AaaS mirroring the archive, but does not
   automatically cure restrictions on use or modification. The official
   Android tooling documentation now marks `sdkmanager` deprecated in favor of
   `android sdk`; package installation requires license acceptance. An
   installer must not automate acceptance on a user's behalf.
5. **Local transformation:** a user-side workflow still needs exact input
   verification, a complete deterministic transformation recipe, compatible
   outputs, and an adequate legal basis for each transformation. The current
   recipe is incomplete and the accepted rootfs contains modifications whose
   origins and purposes are not fully reconstructed.

Evidence files [`android16-diagnostic-rootfs-audit.json`](../manifests/android16-diagnostic-rootfs-audit.json),
[`android16-reconstruction-transformations.json`](../manifests/android16-reconstruction-transformations.json),
[`android-profiles.json`](../manifests/android-profiles.json), and
[`android-source-lock.md`](android-source-lock.md) all describe an incomplete
or diagnostic state. The profile explicitly says it is not automatically
installable: the SDK image is not the accepted rootless runtime, a complete
source lock and transformation recipe are absent, and APEX activation remains
unverified.

Therefore **Option B is not currently implemented or ready to promise**. A
future lawful assembly route would need to stop before downloading until the
user chooses an official package and accepts its terms, verify a vendor-backed
revision/checksum, apply a complete reviewed recipe, and prove output hashes
and runtime compatibility. If the SDK terms do not permit this use, investigate
a compatible self-built source image under component licenses instead. Do not
offer an unofficial mirror or silently turn the SDK package into a derived
public download.

## Bundle source revision and dirty-worktree discrepancy

The immutable candidate records top-level repository revision
`af3dcb4711d13197826942f0a1c7f2b1698589ec` and
`source_tree_dirty_at_capture=true`. Its 17 tracked runtime executable/library
rows and both generated installer rows instead identify
`71105b74c364ed9f179b55c5cd4cf1572b07e646` with `worktree_dirty=True`.
This cannot be interpreted as evidence that the candidate was wholly built at
either revision: a boolean dirty marker does not list changed files, and the
installer identity conflicts with the top-level capture identity.

Hash comparison against Git confirms all 17 tracked executable/library row
hashes match at both revisions. Those commit versions provide no way to tell
which one was copied. Other candidate files may have changed between the
commits; matching an artifact hash to a commit proves content identity for
that file only. The retained evidence does not establish whether the old
manifest/SBOM was composed from multiple captures, edited after construction,
or produced by a different local builder state. Exact reconstruction of the
candidate's original capture is therefore **not established**. No claim of
bit-for-bit reproducibility is made.

The release builder previously used one broad dirty flag for unrelated
untracked/generated outputs and repeated it in installer provenance. The
current source change records the HEAD, tracked worktree changes included in
the runtime, included untracked runtime paths, and other untracked-file count
separately. This improves future evidence; it does not repair or retroactively
change the M5 candidate.

## Distribution options

| Model | Legal dependencies | Engineering/user effort | Decision |
|---|---|---|---|
| **A. Source-only** | Owner must select a project license; imported source notices and source-origin questions must be resolved. Exclude system images and uncleared binaries. | Lowest ongoing engineering burden; users cannot run the accepted runtime from source alone yet | **Recommended near-term**, after owner license approval and source cleanup. Until then, a public repository has unspecified AaaS reuse rights and is not a completed open-source release. |
| **B. Source plus user-side assembly** | Requires an acceptable legal basis for the SDK image or a clean self-built alternative, plus all third-party terms | Highest user setup burden and substantial engineering work; exact transforms and clean image compatibility are not ready | Future direction only. Do not advertise or implement as working today. |
| **C. Fully redistributable binary** | Requires rights, notices, source obligations, and provenance for the entire dependency closure, especially Android image and modified files | Easiest user experience; highest compliance and maintenance burden | Not currently possible to approve. Do not upload the accepted bundle. |

## Actionable publication checklist

1. **Owner:** select Apache-2.0, MIT, GPL-3.0-or-later, or another license for
   code the owner controls; confirm contributor/employer rights. No license is
   applied by this report.
2. **Maintainer:** inventory tracked files by origin, preserve imported
   notices, resolve the SwiftShader and protocol sources, and remove or
   separately license any copied material that cannot be cleared.
3. **Maintainer:** review Git history for host-specific/private information
   before making the existing history public; do not silently rewrite it.
4. **Maintainer/reviewer:** map all 94 workspace artifacts and 27 untracked
   runtime outputs to exact source, build recipe, and license. Add upstream
   license and NOTICE texts where required.
5. **Legal review:** determine whether use/modification of the SDK r02 image
   for this non-CTS-proven Android implementation is permitted under the
   applicable agreement, or select a separately licensed source-build path.
6. **Engineering:** only after that decision, implement and test an explicit
   user-consented acquisition/assembly flow or produce a fully cleared
   binary closure. Verify exact inputs and output hashes.
7. **Release maintainer:** regenerate the SBOM from the chosen release payload,
   ensure every component has an evidence-backed license conclusion or an
   explicit exclusion, attach notices/source offers as required, and obtain
   final review before publication.

## Decision summary

- **AaaS source:** not yet an authorized open-source release; project owner
  must choose a license. Apache-2.0 is the recommended default for
  owner-controlled source after the origin review.
- **Best near-term model:** source-only after authorization and cleanup. Do
  not claim users can currently assemble the accepted runtime from official
  inputs.
- **Android image:** source package identity is recorded, but the local
  SHA-256 is not vendor-published; modifications and applicable SDK terms
  need review. User-side download alone does not resolve the question.
- **Binary:** the M5 bundle is not cleared for public redistribution. The
  Android image, modified platform files, workspace artifacts, and several
  third-party components remain unresolved.
- **M5:** functional acceptance is preserved; this licensing investigation
  neither reopens nor changes it.

## Authoritative references

- [Android SDK License Agreement](https://developer.android.com/studio/terms)
- [AOSP license headers and component licensing](https://source.android.com/docs/setup/contribute/licenses)
- [AOSP source acquisition and proprietary device binaries](https://source.android.com/docs/setup/download)
- [Android SDK package tools and license acceptance](https://developer.android.com/tools/sdkmanager)
- [Digitalis](https://github.com/DigitalisX64/digitalis) and [Refract](https://github.com/MIXIDtheSilly/Refract) upstream projects; exact release terms must be checked against the embedded artifact revisions

The linked upstream pages are evidence sources, not legal approval. Consult
the actual license texts shipped with each component and obtain qualified
review where terms or provenance remain uncertain.
