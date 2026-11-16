# Third-party source notices

This index identifies source-level notices found during the current review. It
does not replace file headers or claim that every imported/generated file has
been identified. Preserve the notice and license text with each source file.

| Source material | License evidence | Handling |
|---|---|---|
| `experiments/m4/audio/audio_hal.c`, `audio_protocol.h`, and `ashmem_compat.c` | Each file has `SPDX-License-Identifier: MIT` and an AaaS contributors copyright line | MIT terms are in [`LICENSES/MIT.txt`](LICENSES/MIT.txt); these files remain MIT, separate from the root Apache grant |
| `experiments/m1b/**/include/aidl/**` and Android Binder/JNI headers | Individual files contain AOSP/Android copyright and license headers; AOSP describes Apache-2.0 as preferred but notes exceptions | Preserve each file's own header and terms; do not infer a single license for all Android-derived files |
| `experiments/m1a/protocols/linux-drm-syncobj-v1.xml` and `viewporter.xml` | The XML files carry upstream copyright and permission terms inline | Keep the full embedded notices in each file |
| `experiments/m1b/swiftshader/gemini-native-buffer.patch` and `experiments/m1e/patches/swiftshader_coherent_diagnostic.patch` | These patches contain SwiftShader copyright/license context, but exact patch origin and upstream revision are not established | Treat as independently licensed upstream-derived material; do not apply the AaaS Apache grant without completing provenance review |
| Digitalis/Berberis and Android SDK/runtime binaries | Present in the accepted local bundle, not as source files in this repository; the bundle includes an embedded Digitalis notice but file-to-notice coverage is unresolved | No binary distribution rights are asserted here; see the [bundle decision matrix](docs/release/bundle-redistribution-decision.md) |

No separate upstream `NOTICE` file for the source groups above was identified
in the tracked source tree. This is not a complete third-party inventory. The
root [`LICENSE`](LICENSE) covers only eligible original AaaS source code and
does not supersede any per-file terms.
