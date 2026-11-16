# Licensing and external runtime inputs

The repository root now contains the canonical Apache License 2.0. Its grant
is limited to original AaaS source code that the project owner is authorized to
license. It does not relicense third-party material, research/media assets, the
Android image, or the prebuilt runtime. File-specific notices take precedence;
see [third-party source notices](../THIRD_PARTY_NOTICES.md).

This scope follows the owner's authorization. No file-by-file copyright
assignment is implied. The source review found AaaS implementations and tests,
generated AIDL/AOSP interfaces, upstream protocol descriptions, MIT-noticed
audio files, and SwiftShader patches. Origins for some generated/imported files
and the historical author/path privacy review remain incomplete. Do not treat
the repository history as cleared for public exposure until those issues are
reviewed.

The generated AIDL headers under `experiments/m1b/composer_aaas/include/aidl/`
identify QPR2 `hardware-interfaces` inputs in their generator comments. Those
paths match the pinned Android graphics source candidate:
`platform/hardware/interfaces` revision
`aa229558cbf04bc997ed27465c5e7ad497123d1b`, from superproject revision
`cc66c82349f536b77341e13862a548c01b048963`. I verified that all 92 referenced
AIDL files exist at that revision and contain Apache-2.0 license headers; the
276 generated headers are mapped to them in the
[AIDL provenance manifest](../manifests/composer-aidl-provenance.json). Their
source notices identify Android Open Source Project copyrights from 2019–2024.
The manifest also pins the referenced build-tools and AIDL compiler source
projects. No generation receipt captures the exact input/tool binary hashes
used for the historical generation, so a bit-for-bit source-to-output rebuild
is not claimed. These are AOSP-derived generated interfaces, not original AaaS
code covered by the root license. `docs/research-report.pdf` identifies its author as
“ChatGPT Deep Research” in PDF metadata and is not covered by the root Apache
grant; text-based privacy checks found no local home/mount path, email address,
IP address, or credential-label matches. The owner should still decide whether
the report's origin and content are suitable for public retention.

## Android image and bundle

The accepted preview used the Google Android SDK image
`system-images;android-36;default;x86_64`, revision `r02`, build
`BE2A.250530.026.D1`. The source checkout does not contain this image, does not
reproduce the accepted modified rootfs, and cannot boot Android by itself. The
SDK-derived system image and accepted bundle are not cleared for public
redistribution. A supported user-side acquisition/assembly workflow is not
implemented.

The current [bundle redistribution decision matrix](release/bundle-redistribution-decision.md)
summarizes the evidence and the exact remaining rights questions. It is an
engineering assessment, not legal advice or a clearance decision. The
Android SDK agreement and [AOSP file-level licensing guidance](https://source.android.com/docs/setup/contribute/licenses)
must be read separately: AOSP says Apache-2.0 is preferred but recognizes
exceptions, while the SDK agreement applies to SDK system files and treats
open-source components under their own licenses.

## Owner and maintainer actions

1. Confirm ownership of the AaaS-authored source covered by Apache-2.0,
   including employer or contributor rights where relevant.
2. Review the generated/imported files whose exact source revision or
   modification history is not established.
3. Decide whether the existing author identity and machine-specific history
   may be published. No history rewriting has been done.
4. Obtain qualified legal interpretation of the SDK agreement's application to
   this modified, shared-kernel Android runtime before distributing the image
   or bundle.
5. Complete the component/notice mapping for the immutable bundle before any
   binary release.

The source license does not authorize distribution of the Android SDK image or
the accepted bundle.
