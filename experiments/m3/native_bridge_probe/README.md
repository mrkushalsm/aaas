# M3 ARM64 Native Bridge probe

This is a diagnostic-only APK builder. It compiles `native_probe.c` for
`aarch64-linux-android36`, assembles the small Activity from smali, packages
only `lib/arm64-v8a/libm3probe.so`, signs the APK, and verifies its ELF machine
and ABI inventory. The AOSP `jni.h` header is pinned in `include/` from
`platform/libnativehelper` revision
`2d584ec2da2c5271ed1576593c6590d652806f0d` (Apache-2.0).

Example build in the project workspace (set `AAAS_WORKSPACE` to its root first):

```sh
python3 experiments/m3/native_bridge_probe/build_probe.py \
  --apktool $AAAS_WORKSPACE/tmp/apktool_3.0.3.jar \
  --output $AAAS_WORKSPACE/tmp/m3_native_bridge/AaasM3NativeBridge.apk \
  --keystore $AAAS_WORKSPACE/tmp/m3_native_bridge/m3-debug.keystore
```

The tested tool versions were Clang 23.1.1, Apktool 3.0.3 (SHA-256
`dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423`), and
OpenJDK 21. The debug keystore and generated APK stay outside the Android base
image and repository build directories.

The ARM64 code checks integer, 64-bit, floating-point, string, array, Java
callback, controlled negative-argument error, and four-lane NEON results. Java
compares the returned diagnostic string with the expected result before
displaying it. There is no x86 native library or fallback implementation.

For the live run, pass the APK with `--input-response-probe-apk`, launch
`org.aaas.latencyprobe`, and pass a SHA256SUMS-verified Digitalis bundle with
`--diagnostic-native-bridge-overlay`. The runner merges that bundle into a
session-local hard-link view of system files, overrides Native Bridge and ABI
properties before init, and removes the merge after shutdown. The base image is
not changed.
