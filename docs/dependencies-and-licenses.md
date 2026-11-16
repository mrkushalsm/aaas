# Licensing and external runtime inputs

The repository root now contains the canonical Apache License 2.0. Its grant
is limited to original AaaS source code that the project owner is authorized to
license. It does not relicense third-party material, research/media assets, the
Android image, or the prebuilt runtime. File-specific notices take precedence;
see [third-party source notices](../THIRD_PARTY_NOTICES.md).

The owner authorized Apache-2.0 for eligible AaaS-authored code they own; this
does not imply a file-by-file copyright assignment or cover third-party files.
The owner also approved the preserved historical identities/paths and chose to
retain the research report. This final source review found no high-confidence
credential or private-key patterns in 2,340 reachable Git blobs. This is a
bounded scan, not a guarantee against every form of sensitive information.

The generated Composer AIDL headers under `experiments/m1b/composer_aaas/include/aidl/`
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
code covered by the root license. The separate allocator AIDL generated files
name three source inputs under the same pinned `hardware/interfaces` revision;
all three were fetched from that exact revision and verified to carry AOSP
copyright and Apache-2.0 headers. The generated outputs are upstream-derived,
not AaaS-owned, and no historical generation receipt records the actual input
or tool binary hashes. The AOSP Binder/JNI headers reviewed in the source tree
retain their file-level Apache notices. The reduced Mapper `android/rect.h`
and `cutils/native_handle.h` headers now carry restored AOSP copyright and
Apache notices, verified against the Android 16 pinned `frameworks/native` and
`system/core` source revisions.

The SwiftShader project is Apache-2.0. The coherent diagnostic patch is tied by
the engineering record to upstream revision
`cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5`; the earlier Android-buffer patch
has no exact base revision recorded. That gap limits historical reproduction,
but the files it patches are SwiftShader Apache-2.0 source and no separate
incompatible patch origin was found. See [third-party notices](../THIRD_PARTY_NOTICES.md).

`docs/research-report.pdf` is retained by owner decision and is not covered by
the root Apache grant. Its metadata identifies ChatGPT Deep Research; review
found 36 pages of cited technical analysis, no embedded raster images, and no
personal paths, email addresses, IP addresses, or credentials. Metadata alone
does not establish authorship or a rights defect. The report has no separate
license notice; the owner's instruction authorizes retention, and no concrete
third-party or confidentiality issue was identified in this review. The three
selected screenshots are genuine accepted-run captures, contain no visible
personal contact data, and likewise remain outside the Apache source grant.
OpenAI's [individual Terms of Use](https://openai.com/policies/terms-of-use/)
effective January 1, 2026 state that, as between OpenAI and the user and to the
extent permitted by law, the user owns Output and OpenAI assigns any interest
it may have. If the PDF metadata reflects output from the owner's individual
account under those terms, they support retaining the generated report; they
do not grant rights to third-party source material included in the user's
inputs. This is a documented basis, not a legal opinion.

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

1. Obtain qualified legal interpretation of the SDK agreement's application to
   this modified, shared-kernel Android runtime before distributing the image
   or bundle.
2. Complete the component/notice mapping for the immutable bundle before any
   binary release.

The source license does not authorize distribution of the Android SDK image or
the accepted bundle.
