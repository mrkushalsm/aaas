# M3 — ARM64 Native Bridge feasibility

**Status: PASS/CLOSED.** This document follows [canonical Plan A](../roadmap.md); it does not refer to the historical zero-copy M3 in Plan C. The implementation is a bounded feasibility proof, not universal ARM64 application compatibility.

## Objective and entry prerequisites

Execute a genuine ARM64 shared library through Android Native Bridge inside the existing x86_64 Android runtime and verify Java/JNI values. The existing Android 16 runtime, ART, Zygote, x86_64 applications, KWin window path, runtime overlays, logs, and tombstone capture met the M3 entry requirements. M3 did not modify the base image or graphics implementation.

## Candidate decision

| Candidate | Evidence and decision |
|---|---|
| Digitalis / Berberis ARM64-to-x86_64 | Selected. Digitalis source is Apache-2.0 and targets Android 16/API 36. The verified prebuilt bundle was obtained from Refract commit `ddef6e6ae7de37dd3e400d6a07d3f18cb21a0ebc`; its manifest pins `digitalis` revision `a6edb72029cd25cb616bdee1a12b2d64e3a6a3ae` and `platform_frameworks_libs_binary_translation` revision `9e7f4407e0e32a582fe2a56f87492443ca55d6fa`. The bundle marks Digitalis/Berberis as Apache-2.0 and records per-component guest-library notices. Its translator has three Refract source patches; no bundle binaries are checked into AaaS. The exact binary and bundle checksums are in the M3 acceptance JSON. |
| Teto | Not selected. The inspected Droidloom `droidloom` revision `365d035faed6734fa07e47c33b92e9cbac17569b` is Apache-2.0 and describes itself as an experimental ARM64 Android derivative of Digitalis/Berberis. It offered no independent Android 16 Native Bridge path with stronger integration evidence; its README warns compatibility remains experimental. |
| AOSP Berberis | Not selected by itself. The Android 16 ARM64-to-x86_64 backend used here is the Digitalis fork; upstream Berberis work alone does not supply the required ARM64 host backend. |
| Houdini / `libndk_translation` | Rejected for this milestone: proprietary artifacts were unavailable in the runtime and did not offer source/license provenance suitable for this integration. |

The release bundle is pinned and acquired reproducibly using its exact Refract Git commit and 74-entry SHA256SUMS manifest. A full Android platform source build was not attempted: the documented full AOSP checkout/build storage requirement exceeds AaaS's 80 GiB workspace ceiling. This is a prebuilt acquisition, not a claim that the translator binary was rebuilt from source. Do not redistribute the external bundle without rechecking its component notices and applicable license terms.

## Integration

Android Native Bridge is enabled only with the opt-in `--diagnostic-native-bridge-overlay` runner option and the experimental virtual-display path. The runner rejects bundles outside workspace `tmp`, verifies all 74 checksums and safe paths, constructs a temporary merged system view using hard links, and removes it after process teardown. Init sees these session-only properties before Zygote:

- `ro.dalvik.vm.native.bridge=libberberis_arm64.so`
- `ro.dalvik.vm.isa.arm64=x86_64`
- `ro.product.cpu.abilist=x86_64,arm64-v8a`
- `ro.product.cpu.abilist64=x86_64,arm64-v8a`
- `ro.enable.native.bridge.exec=0` (JNI Native Bridge is enabled; binfmt execution is not needed)

Native x86_64 stays first and remains usable. The Android 16 `libnativebridge` loads Digitalis's exported `NativeBridgeItf`; the bridge callback table is version 8. The live log records the Zygote `-XX:NativeBridge` option and NativeBridge `DlOpen`/JNI library-load success. The overlay does not change `rootfs_m1b1`.

## Diagnostic application and result

Source: [native bridge probe](../../experiments/m3/native_bridge_probe/README.md). The generated APK package is `org.aaas.latencyprobe`; the only native library is `lib/arm64-v8a/libm3probe.so`. It is ELF64/AArch64, has no DT_NEEDED dependencies, and the APK has no x86 or x86_64 native fallback.

The ARM64 JNI function validates and returns a result string only after the following operations pass: `7,3 → 77`; `1234567890123,9 → 38271604593822`; `2.0,4.0 → 7.0`; UTF string `AaaS M3` round-trip; Java int array `[1,2,3,4] → 10`; callback `14 → 42`; negative-input error `-1 → -22`; and four NEON lanes `[1,2,3,4]+[4,3,2,1] → [5,5,5,5]`. The Activity compares the complete returned string against its independent expected value before logging/displaying PASS. The observed Android log was `M3 ARM64 Native Bridge PASS mask=255 int=77 array=10 callback=42 error=-22 long=38271604593822 double=7.0 neon=5x4 echo=AaaS M3`.

## Acceptance summary

| Gate | Result |
|---|---|
| Candidate, API, license and pinned provenance review | PASS |
| Android Native Bridge active before app process | PASS |
| Genuine ARM64 ELF executed through JNI | PASS |
| Exact Java-observed primitive, string, array, callback, error and NEON results | PASS |
| ARM64-only APK recognized and launched by PackageManager | PASS |
| AaaS Android virtual display and native KWin Wayland presenter | PASS |
| JIT evidence in application process | PASS — `/memfd:exec` mappings captured while the app ran |
| Native x86_64 regression | PASS — Settings and Contacts launched concurrently with the bridge enabled |
| Runtime/presenter cleanup | PASS — stopped sessions, 0 outstanding presenter buffers, temporary overlay removed |
| Full Android-platform source rebuild | Not performed; the pinned, hash-verified prebuilt bundle was used |

Session IDs, exact hashes, result values, runtime fingerprint, presenter accounting, test commands, and external log locations are in **`results/m3/acceptance.json`** (maintainer archive only). Large raw logs remain in the external AaaS workspace.

## Supported scope and limitations

Verified: the tested Android 16/API 36 x86_64 image, Digitalis/Berberis Native Bridge initialization, one ARM64 JNI library, the listed scalar/array/string/callback/NEON cases, an ARM64-only diagnostic APK, and the existing KWin AaaS app-window path. Native x86_64 Settings and Contacts still launch. The test does not establish arbitrary ARM64 APK compatibility, all JNI features, all instruction extensions, translated threads, vendor/graphics guest libraries, ARM64 standalone executable/binfmt operation, or performance comparable to native ARM64. M5 graphics performance and M6 compositor portability remain open; M4 is next.
