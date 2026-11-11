# Dependency provenance and licensing assessment

**Current local bundle: not cleared for public redistribution. Source publication also requires an owner-authorized project license.** This engineering assessment is not legal advice or formal legal approval.

## Exact candidate

- Candidate: `engineering-830eef7`, bundle ID `d3d7278094324b93be4f3ad57ae5883d`.
- Source commit: `830eef735bfa41685a8def7a754d24a5740e8d30`.
- Android: 16/API 36, build `BE2A.250530.026.D1`, x86_64.
- Manifest: 8,789 entries; SHA-256 `5cf6e4cab68c907d5496930390497f9c563c8f6254b7c0efbb9a2d85420f80e2`.
- File-level inventory: [file-level inventory](../results/release/sbom-engineering-d3d72780.json). It records every bundle path, mode, type, symlink target, and SHA-256/size for every regular file.

The manifest groups 6,154 Android rootfs entries, 1,946 workspace/build inputs, 684 runtime entries, and 5 installer/metadata entries. Group membership and file hashes establish identity, not the legal origin or license of the files. The rootfs is a historical modified M4 diagnostic image, not a clean rebuild from a complete pinned Android source graph. The per-file licenses and redistribution rights are not proven for the bundled image. The current SBOM clears **zero** files for redistribution; Android/vendor contents and many bundled build/runtime inputs remain `NOASSERTION` or unreviewed.

## Component-level findings

| Component group | Observed source/origin | License/provenance state | Distribution decision |
|---|---|---|---|
| Android 16 diagnostic rootfs | Historical modified M4 rootfs, Android build `BE2A.250530.026.D1`; full source graph and exact upstream image provenance not retained in this candidate record | Per-file source, license, vendor status, notices, and source-offer obligations unresolved | Do not redistribute. Replace with a reproducibly assembled image from verified sources or implement/test a lawful user-side acquisition process. |
| Berberis/Digitalis translation and compatibility overlays | Present in runtime/build inputs; inventory identifies path/hash but not a complete upstream revision-to-file map | Component-specific notices and exact file mapping require review | Not cleared until mapping, license texts, modifications, and notices are verified. |
| SwiftShader/ANGLE and graphics libraries | Present in Android/runtime image; exact binary-to-source mapping incomplete | License/provenance unresolved at artifact level | Not cleared. |
| Helper APKs and generated overlays | Rebuild pipeline exists; signing keys remain outside the bundle | Generated artifacts still need source notices, license review of embedded dependencies, and exact hash-to-build record | Local use only until SBOM and notices are closed. |
| slirp4netns and host tools | Build/runtime input metadata contains hashes; version/source/license closure not complete in the bundle inventory | Must inspect pinned revision, license, notices, and host package assumptions | Not cleared by this report. |
| AaaS-authored source | Repository code and documentation | No root project `LICENSE`; copyright-holder authorization and chosen license absent | Do not publish under an assumed license. |

No inference is made that an Android-derived binary is redistributable merely because it is downloadable or because some AOSP source is open licensed. Vendor images, SDK/emulator images, bundled APKs, fonts/assets, and generated binaries need their own provenance and terms.

## Source license decision for the owner

No license has been added. The copyright owner must choose and authorize it. Suggested options:

- **Apache-2.0 (recommended if the owner wants a permissive license with an express contributor patent grant):** includes copyright and patent grants and conditions for redistribution, NOTICE handling, and modified-file notices. It is more detailed than MIT. See the [Apache License 2.0 text](https://www.apache.org/licenses/LICENSE-2.0).
- **MIT (short permissive alternative):** requires retaining copyright and permission notices and disclaims warranty; it is simpler, but has no express patent-license section. See the [OSI MIT text](https://opensource.org/license/mit).
- **GPL-3.0-or-later (copyleft alternative):** appropriate if the owner wants distributed modified versions of the covered program to remain under GPL-compatible terms and corresponding source obligations to apply. It complicates combining/distributing the runtime with differently licensed components; it does not automatically relicense independent bundled components. See [GNU GPLv3](https://www.gnu.org/licenses/gpl-3.0.html).

Recommendation: Apache-2.0 for original AaaS code if the owner prioritizes broad reuse and an express patent grant. MIT is a reasonable simpler alternative. Select GPL-3.0-or-later only if reciprocal copyleft is an intentional project goal. Any choice requires owner authorization and a contributor-rights review; this report does not apply a license.

## Answers and required decisions

1. **Can source be published now?** Technically, the tracked source is separable from runtime binaries, but legally the repository has no AaaS license grant and its history contains historical machine-specific identifiers. Do not publicly publish until the owner authorizes a license and reviews history/privacy exposure.
2. **Recommended source license?** Apache-2.0, subject to owner approval; MIT is the simpler permissive alternative.
3. **Third-party notices?** Preserve each upstream license and NOTICE with the exact files to which it applies. Current candidate does not have a complete file-to-notice map.
4. **Can the complete engineering bundle be redistributed?** No, not on present evidence.
5. **Exact blockers?** The Android diagnostic rootfs (including possible vendor/SDK image content), Android/runtime binaries, translation/graphics components, helper APK contents, and build utilities lack a complete authoritative provenance/license mapping; runtime security is also not approved for untrusted apps.
6. **Can a redistributable bundle be built?** Not demonstrated. A legal, source-pinned component set or tested user-side acquisition/assembly workflow is needed, followed by install and runtime validation.
7. **What changes are required?** Establish reproducible origin and version for each component; replace restricted/unknown files or exclude them; package notices/source offers; regenerate SBOM and validate the resulting bundle.
8. **Can source-only distribution work meanwhile?** Potentially, after owner authorizes a project license and history/privacy review, while excluding generated/runtime binaries and explaining how users provide permitted inputs. This is not yet cleared.
9. **Owner decision:** choose/authorize a project license; decide whether historical Git history may be sanitized or must remain; authorize any copyright notices/contributor terms; obtain legal review for uncertain Android image/vendor rights before binary distribution.

## Scope and caveat

This is an engineering provenance audit, not a legal opinion. The file-level SBOM is traceable to the local candidate bytes, but unknown source identities remain unknown. No public source or binary upload was performed.
