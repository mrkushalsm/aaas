# Third-party source notices

This index identifies source-level notices found during the current review. It
does not replace file headers or claim that every imported/generated file has
been identified. Preserve the notice and license text with each source file.

| Source material | License evidence | Handling |
|---|---|---|
| `experiments/m4/audio/audio_hal.c`, `audio_protocol.h`, and `ashmem_compat.c` | Each file has `SPDX-License-Identifier: MIT` and an AaaS contributors copyright line | MIT terms are in [`LICENSES/MIT.txt`](LICENSES/MIT.txt); these files remain MIT, separate from the root Apache grant |
| Generated AIDL headers under `experiments/m1b/composer_aaas/include/aidl/**` | The 276 generator comments map to 92 AIDL inputs in Android 16 QPR2 `platform/hardware/interfaces` revision `aa229558cbf04bc997ed27465c5e7ad497123d1b`. All 92 inputs have Apache-2.0 headers and AOSP copyright notices. The related source snapshot pins `prebuilts/build-tools` at `412724a805835d89234d67c363f7ada7f5f8a67f` and `system/tools/aidl` at `3747384b876442e7ea0c355fe5adc75b29362833`. The generated headers themselves contain no per-file notices. | Treat these as AOSP-derived generated interface material under the upstream Apache-2.0 terms, not AaaS-owned source. Preserve the AOSP attribution and all per-input notice strings recorded in [`composer AIDL provenance`](manifests/composer-aidl-provenance.json). The source mapping is verified against the pinned candidate; no original generation receipt records the actual input/tool hashes used at generation time. |
| Android Binder/JNI and platform headers | Individual upstream headers contain Android Open Source Project copyright and Apache-2.0 license text; AOSP describes Apache-2.0 as preferred but notes exceptions | Preserve each file's own header and terms; do not infer a single license for all Android-derived files |
| `experiments/m1a/protocols/linux-drm-syncobj-v1.xml` and `viewporter.xml` | The XML files carry upstream copyright and permission terms inline | Keep the full embedded notices in each file |
| `experiments/m1b/swiftshader/gemini-native-buffer.patch` and `experiments/m1e/patches/swiftshader_coherent_diagnostic.patch` | These patches contain SwiftShader copyright/license context, but exact patch origin and upstream revision are not established | Treat as independently licensed upstream-derived material; do not apply the AaaS Apache grant without completing provenance review |
| Digitalis/Berberis and Android SDK/runtime binaries | Present in the accepted local bundle, not as source files in this repository; the bundle includes an embedded Digitalis notice but file-to-notice coverage is unresolved | No binary distribution rights are asserted here; see the [bundle decision matrix](docs/release/bundle-redistribution-decision.md) |

No separate upstream `NOTICE` file for the source groups above was identified
in the tracked source tree. This is not a complete third-party inventory. The
root [`LICENSE`](LICENSE) covers only eligible original AaaS source code and
does not supersede any per-file terms.
