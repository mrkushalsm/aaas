#!/usr/bin/env python3
"""Build a signed ARM64-only Native Bridge JNI diagnostic APK."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from experiments.perf.input_latency_probe.build_probe import binary_manifest


ROOT = Path(__file__).resolve().parent


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def verify_arm64_only_apk(path: Path) -> None:
    with zipfile.ZipFile(path) as apk:
        libraries = [name for name in apk.namelist() if name.startswith("lib/")]
        if not libraries or any(not name.startswith("lib/arm64-v8a/") for name in libraries):
            raise RuntimeError(f"APK contains a non-ARM64 native library: {libraries}")
        native = [name for name in libraries if name.endswith(".so")]
        if native != ["lib/arm64-v8a/libm3probe.so"]:
            raise RuntimeError(f"unexpected APK native library inventory: {native}")
        elf = apk.read(native[0])
    if elf[:6] != b"\x7fELF\x02\x01":
        raise RuntimeError("native probe is not a little-endian ELF64 shared object")
    if int.from_bytes(elf[18:20], "little") != 183:
        raise RuntimeError("native probe ELF machine is not AArch64")
    with tempfile.NamedTemporaryFile(prefix="aaas-m3-elf-") as native_file:
        native_file.write(elf)
        native_file.flush()
        dynamic = subprocess.run(["readelf", "-d", native_file.name],
                                 capture_output=True, check=True).stdout.decode()
    if re.search(r"\(NEEDED\)", dynamic):
        raise RuntimeError("probe unexpectedly depends on an external shared library")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apktool", type=Path, required=True)
    parser.add_argument("--clang", default="clang")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keystore", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.keystore.parent.mkdir(parents=True, exist_ok=True)

    if not args.keystore.exists():
        run([
            "keytool", "-genkeypair", "-noprompt", "-keystore", str(args.keystore),
            "-storepass", "android", "-keypass", "android", "-alias", "m3-probe",
            "-dname", "CN=AaaS M3 Diagnostic", "-keyalg", "RSA", "-keysize", "2048",
            "-validity", "3650",
        ])

    with tempfile.TemporaryDirectory(prefix="aaas-m3-native-probe-") as temp_name:
        work = Path(temp_name)
        smali = work / "smali"
        shutil.copytree(ROOT / "smali", smali)
        (work / "AndroidManifest.xml").write_bytes(
            binary_manifest("org.aaas.latencyprobe"))
        (work / "apktool.yml").write_text(
            "version: 3.0.3\napkFileName: AaasM3NativeBridge.apk\n"
            "sdkInfo:\n  minSdkVersion: 28\n  targetSdkVersion: 28\n"
            "versionInfo:\n  versionCode: 1\n  versionName: 1.0\n"
        )
        run([str(args.clang), "--target=aarch64-linux-android36", "-ffreestanding",
             "-O0", "-fPIC",
             "-fno-stack-protector", "-shared", "-nostdlib", "-Wl,--no-undefined",
             "-I", str(ROOT / "include"), "-Wl,-soname,libm3probe.so",
             str(ROOT / "native_probe.c"),
             "-o", str(work / "libm3probe.so")])
        run(["java", "-jar", str(args.apktool), "b", "--no-apk", str(work)])
        dex = work / "build" / "apk" / "classes.dex"
        if not dex.is_file():
            candidates = list((work / "build").rglob("classes.dex"))
            if not candidates:
                raise RuntimeError("apktool did not emit classes.dex")
            dex = candidates[0]
        unsigned = work / "unsigned.apk"
        with zipfile.ZipFile(unsigned, "w") as apk:
            apk.write(work / "AndroidManifest.xml", "AndroidManifest.xml")
            apk.write(dex, "classes.dex")
            apk.write(work / "libm3probe.so", "lib/arm64-v8a/libm3probe.so")
        run(["jarsigner", "-keystore", str(args.keystore), "-storepass", "android",
             "-keypass", "android", "-sigalg", "SHA256withRSA", "-digestalg", "SHA-256",
             str(unsigned), "m3-probe"])
        shutil.copy2(unsigned, args.output)
    verify_arm64_only_apk(args.output)
    print(f"APK SHA-256: {hashlib.sha256(args.output.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
