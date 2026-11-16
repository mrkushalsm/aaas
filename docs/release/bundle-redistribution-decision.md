# M5 bundle redistribution decision

**Decision: BLOCKED pending component provenance and qualified legal review.**
This is an engineering evidence summary, not legal advice. The accepted bundle
remains immutable and was not rebuilt or repackaged.

## Candidate and evidence scope

| Item | Recorded value |
|---|---|
| Bundle | `engineering-af3dcb4` |
| Bundle ID | `43d04579ec874746a7c9da5152419bd6` |
| Artifact count | 8,795 |
| Manifest SHA-256 | `d638937b4bcb16f550b2e204175c70ec247190ca10b6e7229447560909db2a64` |
| Base image | `system-images;android-36;default;x86_64`, r02, `BE2A.250530.026.D1` |

The retained M5 component grouping has 1,985 executable/library rows: 1,844
assigned to the historical Android SDK-derived rootfs group, 94 generated
workspace artifacts, 27 untracked local runtime outputs, 17 tracked source
rows, two installer wrappers, and one generated compatibility preload. The
manifest marks all 1,985 `NOT_REVIEWED_FOR_DISTRIBUTION`; 1,965 have
`UNVERIFIED_PROVENANCE`. These are grouped evidence gaps, not 1,965 separate
legal findings.

### What is tied to the accepted bundle

Hash comparison of the diagnostic rootfs audit against the immutable M5
manifest matched all 19 audited rootfs paths exactly:

- **16 modified SDK base files:** `system/bin/apexd`, `system/bin/servicemanager`,
  `system/bin/vdc`, `system/bin/vold`, `system/lib64/libandroid_runtime.so`,
  `system/lib64/libbinder.so`, `system/lib64/libhidlbase.so`,
  `system_ext/bin/hwservicemanager`, `system/etc/init/apexd.rc`,
  `system/etc/init/hw/init.rc`, `system/etc/init/netbpfload.rc`,
  `system/etc/init/vold.rc`, `vendor/etc/init/hw/init.ranchu.rc`,
  `vendor/etc/init/hwc3.rc`,
  `vendor/etc/init/android.hardware.graphics.allocator-service.ranchu.rc`,
  and `vendor/etc/init/lights-default.rc`. The audit says their changes lack a
  source-controlled transformation recipe; the differing hashes establish
  identity, not authorship, correctness, or license.
- `system/bin/surfaceflinger` was byte-identical to the extracted SDK base.
- `rootfs/system/lib64/libselinux_shim.so` and
  `rootfs/vendor/lib64/libselinux_shim.so` match the audited shim hashes and map
  to `experiments/m1b/shim_selinux.c`. This diagnostic shim fabricates SELinux
  authorization/context success and is not approved for untrusted apps.

The 11 modified entries in the local SwiftShader source checkout are **not**
tied by source revision/hash to the M5 SwiftShader overlay. The bundle contains
`workspace-artifacts/tmp/m1e_swiftshader_fixed_notrace_v2.so` and its manifest,
but that does not establish which local source changes produced it. The 19
rootfs matches are a bounded audit, not a complete comparison of all 8,795
artifacts.

## Component decision matrix

Categories: **A** established open-source terms for the identified files;
**B** a known contractual restriction applies to the relevant class of
material; **C** origin, license, or modification evidence is incomplete;
**D** a technically plausible replacement path exists but may be unverified;
**E** explicit rights-holder permission or qualified legal interpretation is
needed. A row may have multiple categories. None of these labels alone clears
the complete bundle.

| Component | Origin, revision, modification evidence | Category and distribution status | What would move it forward / replacement status |
|---|---|---|---|
| Original AaaS source, CLI, tests, build scripts | Source checkout; current root `LICENSE` covers eligible original AaaS code the owner is authorized to license. The accepted bundle identifies 17 tracked executable/library rows, but its two generated installer rows cite `71105b7` with a dirty worktree while the top-level capture cites `af3dcb4` and dirty. | **A** for covered source; **C** for exact provenance of some prebuilt copies. Not a bundle-wide grant. | Confirm ownership for covered contributions and map generated binaries to exact source/build state. No runtime change required. |
| MIT-noticed AaaS audio source | `experiments/m4/audio/audio_hal.c`, `audio_protocol.h`, `ashmem_compat.c` carry MIT SPDX notices. | **A**, under the file-level MIT terms, separate from root Apache-2.0. | Preserve headers and include `LICENSES/MIT.txt`. |
| AOSP/Binder/JNI and generated AIDL source | Tracked headers carry Android/AOSP copyright and Apache-2.0 notices; individual files govern. AOSP says Apache-2.0 is preferred but recognizes exceptions. | **A** only for individually identified files with matching headers; other generated files remain **C**. Does not license the Google image. | Record upstream paths/revisions and retain each file's own notices. Do not blanket-relicense. |
| Wayland protocol XML | `linux-drm-syncobj-v1.xml` and `viewporter.xml` carry upstream copyright and permission terms inline. | **A** for those exact files under their embedded terms. | Preserve the embedded notices. |
| Android SDK system image | Google package `system-images;android-36;default;x86_64`, r02/build `BE2A.250530.026.D1`. The archive record has SDK-index SHA-1 `829c076e8ff448a336097ae25a355b495ba36e2c`; the recorded SHA-256 is locally measured, not a Google-published digest. | **B/C/E**: SDK terms restrict copying, modification, and redistribution except for open-source components; exact membership of open-source vs other SDK files is not mapped. Applicability to this runtime needs legal interpretation. | Obtain a component map and qualified legal interpretation of SDK agreement §§1.1, 3.1, 3.4, 3.5; permission from Google only if required by that interpretation. User-side download alone does not resolve usage/modification terms. |
| Modified Binder/framework binaries and Android init configuration | The 16 listed modified files are hash-tied to M5. The audit does not establish their source changes or a reproducible build. | **C/E**. They are integrated in the SDK-derived rootfs; no permission status can be inferred from filename or hash. | Need exact source revisions, patches, build recipes, per-file licenses, and SDK-rights interpretation. Rebuilding select AOSP components is possible in principle but no compatible replacement was verified. |
| SurfaceFlinger | `system/bin/surfaceflinger` matches the SDK base hash in both audit and M5 manifest. | **C/E** as a Google SDK image component until the SDK terms question is resolved; its unchanged status is verified. | Same SDK terms decision as above. |
| SELinux compatibility shim overlays | Two bundle files match the audited `shim_selinux.c` output. Source is AaaS diagnostic code; runtime security is explicitly not approved. | **A** for owner-authorized source under Apache-2.0; **C/E** for the containing SDK-derived binary package. Security suitability is a separate blocker to general distribution/use. | Keep security limitation prominent. Removing/replacing the shims is not a verified drop-in change. |
| SwiftShader | Patch context contains SwiftShader notices; local audit found 11 modified checkout entries without a pinned revision. M5 contains a SwiftShader overlay library whose producing source is not tied to those entries. | **C**, not cleared as a bundle component. Upstream licensing does not prove the modified binary's provenance or compliance. | **D, proposed only:** rebuild/replace with a pinned upstream SwiftShader under its applicable terms. ABI, graphics behavior, and output compatibility are unverified. |
| Digitalis/Berberis | M5 has 66 grouped payload rows under the retained package; a related 74-file checksum set was verified locally. Embedded notice states Apache-2.0; associated Refract source is GPL-3.0-or-later, and the recorded Refract revision is incomplete. | **C/E**: checksums prove identity, not source-to-binary mapping or applicable binary terms. The Refract source license cannot be assigned automatically to every prebuilt. | Need exact component mapping, complete source revision, license/NOTICE package, modification evidence, and any source obligations. **D, proposed only:** replacing Native Bridge or dropping ARM64 payload is untested and would change accepted functionality. |
| Android helper APKs, overlays, and other generated workspace artifacts | 94 grouped workspace artifacts; 28 are other helpers/overlays/tools/assets beyond the Digitalis subgroup. | **C**; producer, embedded dependencies, notices, and source mapping are incomplete. | Map each included artifact to source/build producer and licenses; rebuild only from authorized source. |
| Other untracked runtime outputs | 27 executable/library rows have no producer paths in the old capture. | **C**; not cleared. | Identify exact source, build recipe, dependency licenses, and required notices. |
| Host-provided runtime dependencies | The candidate declares 25 runtime inputs in its closure. Those supplied by the host distribution are not automatically part of the bundle and remain under their own distribution terms. | Outside the bundle where genuinely host-provided; not a clearance for copied dependencies. | Confirm packaging does not copy them into a public archive and document host package requirements. |

### Google SDK terms: supportable conclusion

The official [Android SDK agreement](https://developer.android.com/studio/terms)
defines the SDK to include Android system files (§1.1), limits the license to
developing apps for “compatible implementations” (§3.1; defined by CDD and CTS),
restricts copying/modifying/redistributing SDK material except where third-party
open-source licenses require otherwise (§3.4), and says open-source components
are governed by their own licenses (§3.5). The accepted image is modified and
used as a shared-kernel diagnostic runtime; the evidence does not establish that
this runtime is a CDD/CTS-compatible implementation. These clauses are a real
restriction/interpretation issue, but the evidence does **not** prove that every
file in the SDK archive is proprietary or categorically non-redistributable.
Qualified legal review is required for this specific use and distribution.

Downloading the SDK independently through Google's tools would not by itself
complete the needed local transformation recipe or establish that the proposed
use/modification is permitted. `android16-reconstruction-transformations.json`
is marked `PARTIAL` with 15 unresolved transformations; the source checkout
does not produce the accepted rootfs. A user-side SDK acquisition path is
therefore not currently a supported, lawful-and-working substitute.

## Distribution choices

| Strategy | Assessment |
|---|---|
| **A + D: Apache source plus unchanged bundle after full clearance** | **Lowest engineering effort and best preservation of today's install experience if cleared.** The current bundle cannot be uploaded today. First resolve SDK terms and map/clear every included component; keep the bundle unchanged if review permits. |
| **A + C + D: replace only components that cannot be redistributed** | No limited replacement set is established. The SDK image is the runtime's core and thousands of files are involved; the 16 changed base files are only the modifications, not the complete image. Replacing selected components may be feasible after a component map, but compatibility is unverified. |
| **B + D: users obtain Android inputs and assemble locally** | Not ready. A user download does not answer SDK usage rights, and the supported transformation recipe is incomplete. No AOSP rebuild is proposed for this milestone. |
| **D initially: source-only contributors' repository** | The new Apache license prepares eligible AaaS code, but source-origin questions, historical privacy findings, unreviewed tracked images/PDF, and unclear ownership for some imported/generated files remain. Public source publication is not yet safe to declare complete. |

## Exact decisions and evidence still needed

1. Qualified legal interpretation of SDK agreement §§3.1/3.4 for a modified
   Android SDK image used as a non-CDD/CTS-verified shared-kernel runtime, and
   written permission if required.
2. Per-component source/license mapping for the SDK image, Digitalis/Berberis,
   SwiftShader overlay, helper APKs, and 27 untracked runtime outputs; include
   any required notices/source offers.
3. Source/build provenance for the 16 modified base files and a consistent
   provenance record for the generated installer wrappers.
4. Owner decision on publishing existing author metadata and historical
   machine-specific paths; no history rewriting has been performed.
5. Review or exclusion decision for the 97 tracked `results/` images, 13
   tracked `artifacts/` images, one old release image, and
   `docs/research-report.pdf`. Only the three selected `docs/media/` M5
   screenshots were previously selected for public display; the other binary
   evidence was not visually/license reviewed in this pass.

Until these are resolved, the unchanged bundle is **not approved for public
upload**. The lowest-disruption route is to seek a rights interpretation for
the exact existing SDK-derived bundle first; do not rebuild or substitute
components speculatively.

## Source-repository publication blockers

The previous read-only history scan found no high-confidence credential
patterns in the scanned text objects; 116 binary Git objects were not searched
as text, so this is not a clean-history certification. A redacted-value
`git log -G` scan found machine-specific home-path strings in 324 repository
paths across 42 commits. Of these, 276 generated AIDL files are under
`experiments/m1b/allocator_aaas/include/aidl/**` and
`experiments/m1b/composer_aaas/include/aidl/**`, in commits
`0e5f2f04d1e7` and `177a907b9310`. Forty-eight other paths span docs, tests,
scripts, and `results/`; representative commits are `8b0b7ca29725`,
`fc7cd8de246b`, and `7ddf991e2de5`. The individual file/commit map is retained
locally at `~/.local/share/aaas-m8-local-review/history-path-occurrences.json`;
matched values are not in that file. The current tracked tree has no matching
home-path literal.

A machine-specific host label was found historically in
`docs/m1b1-status.md`, `results/m0/host/uname_-a.log`,
`results/m1a/uname.log`, and `results/m1b/host-preflight.log`, across commits
`4e70351ad799`, `5942d5883e3a`, `972cc70920ff`, `a8acc6410367`,
`5f074c7634ee`, and `8243a64a73b2`. The label is redacted here. History contains
one distinct author identity with a public-provider email address. The owner
must decide whether to expose these history details; no rewriting was
performed.

The current tree no longer includes the one-time export tool and candidate
SBOM/group report, but those files remain reachable in old commits
`d37ca0a`, `4e70351`, and `75f932c`. The M5 acceptance tag and full history are
preserved. A full clone therefore still contains these audit artifacts; the
owner must decide whether to publish the existing history or separately
authorize another publication format.

The current Git tree also tracks 114 image files: three selected M5 screenshots
in `docs/media/`, 97 under `results/`, 13 under `artifacts/`, and one old image
under `docs/release/`. It tracks one `docs/research-report.pdf`. Only the three
selected M5 screenshots were previously reviewed as public-facing media; the
other image/PDF items need provenance/privacy review or an explicit exclusion
decision. They are preserved as historical evidence in the current repository
and are not silently declared suitable for public release.
