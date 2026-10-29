#!/usr/bin/env python3
"""Build an Android 16 framework overlay for AaaS desktop IME policy.

The overlay changes only InputMethodService.onEvaluateInputViewShown(). When
the per-user Settings.Secure key ``aaas_desktop_mode`` is non-zero, the method
returns false. InputMethodService remains bound to the editor and retains its
InputConnection; Android simply does not attach/show the soft-input window.

The framework JAR is immutable input. Apktool is used to rebuild the modified
DEX, and the resulting overlay replaces only classes2.dex in a copy of the
original JAR.
"""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path


ORIGINAL_SHA256 = "9430cd45f370bc95b5cdab0274bb8e885ae163660ba9dd7cd7ed4847b635fed0"
APKTOOL_SHA256 = "dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423"
DEX_ENTRY = "classes2.dex"
AOSP_SOURCE_REVISION = "99b01a65cc4c104933788b3143285ab6bae65827"
AOSP_SOURCE_SHA256 = "823216e5872bb4f16c777252011f018785bb1e9d96e4e1b88efe95d3910a7242"
AOSP_SOURCE_PATH = "core/java/android/inputmethodservice/InputMethodService.java"
SOURCE_PATCH = Path(__file__).resolve().parents[1] / "patches/m1d/framework-inputmethod-desktop-policy.patch"
CLASS_PATH = Path("smali_classes2/android/inputmethodservice/InputMethodService.smali")
METHOD_NAME = ".method public whitelist onEvaluateInputViewShown()Z"
METHOD_END = ".end method"
DESKTOP_CHECK = """    const-string v0, "aaas_desktop_mode"

    invoke-virtual {p0}, Landroid/inputmethodservice/InputMethodService;->getContentResolver()Landroid/content/ContentResolver;

    move-result-object v1

    const/4 v2, 0x0

    invoke-static {v1, v0, v2}, Landroid/provider/Settings$Secure;->getInt(Landroid/content/ContentResolver;Ljava/lang/String;I)I

    move-result v0

    if-eqz v0, :aaas_desktop_mode_disabled

    const/4 v0, 0x0

    return v0

    :aaas_desktop_mode_disabled

"""


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def patch_smali_method(source):
    if source.count(METHOD_NAME) != 1:
        raise RuntimeError("InputMethodService method signature mismatch")
    start = source.index(METHOD_NAME)
    end = source.index(METHOD_END, start) + len(METHOD_END)
    method = source[start:end]
    local_marker = "    .locals 5\n"
    if method.count(local_marker) != 1:
        raise RuntimeError("InputMethodService register layout mismatch")
    if "aaas_desktop_mode" in method:
        raise RuntimeError("desktop IME policy is already present")
    method = method.replace(local_marker, local_marker + "\n" + DESKTOP_CHECK, 1)
    return source[:start] + method + source[end:]


def build_overlay(original, apktool, output, work_parent=None):
    original = Path(original).resolve()
    apktool = Path(apktool).resolve()
    output = Path(output).resolve()
    if original == output:
        raise ValueError("overlay output must not replace the original framework JAR")
    if sha256(original) != ORIGINAL_SHA256:
        raise ValueError("original framework JAR checksum differs from the pinned Android 16 image")
    if not apktool.is_file():
        raise FileNotFoundError(apktool)
    if sha256(apktool) != APKTOOL_SHA256:
        raise ValueError("apktool checksum differs from the pinned 3.0.3 build tool")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="aaas-m1d-ime-", dir=work_parent) as temp:
        temp = Path(temp)
        decoded = temp / "decoded"
        rebuilt = temp / "rebuilt.apk"
        subprocess.run(["java", "-jar", str(apktool), "d", "-f", "-r",
                        str(original), "-o", str(decoded)], check=True)
        smali = decoded / CLASS_PATH
        if not smali.is_file():
            raise RuntimeError(f"expected framework class not found: {smali}")
        source = smali.read_text()
        smali.write_text(patch_smali_method(source))
        subprocess.run(["java", "-jar", str(apktool), "b", str(decoded),
                        "-o", str(rebuilt)], check=True)
        with zipfile.ZipFile(rebuilt) as package:
            patched_dex = package.read(DEX_ENTRY)
        staged_fd, staged_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
        os.close(staged_fd)
        staged = Path(staged_name)
        try:
            with zipfile.ZipFile(original) as source_jar, zipfile.ZipFile(staged, "w") as target_jar:
                entries = [info for info in source_jar.infolist() if info.filename == DEX_ENTRY]
                if len(entries) != 1:
                    raise RuntimeError(f"expected exactly one {DEX_ENTRY} entry")
                for info in source_jar.infolist():
                    payload = patched_dex if info.filename == DEX_ENTRY else source_jar.read(info.filename)
                    target_jar.writestr(info, payload)
            os.replace(staged, output)
        finally:
            staged.unlink(missing_ok=True)

    return {
        "original": str(original),
        "original_sha256": sha256(original),
        "overlay": str(output),
        "overlay_sha256": sha256(output),
        "overlay_classes2_dex_sha256": hashlib.sha256(
            _read_zip_entry(output, DEX_ENTRY)).hexdigest(),
        "apktool": str(apktool),
        "apktool_version": subprocess.check_output(
            ["java", "-jar", str(apktool), "--version"], text=True).strip(),
        "aosp_source_repository": "https://android.googlesource.com/platform/frameworks/base",
        "aosp_source_revision": AOSP_SOURCE_REVISION,
        "aosp_source_path": AOSP_SOURCE_PATH,
        "aosp_source_sha256": AOSP_SOURCE_SHA256,
        "source_patch": str(SOURCE_PATCH),
        "source_patch_sha256": sha256(SOURCE_PATCH),
        "changed_entry": DEX_ENTRY,
        "policy_setting": "Settings.Secure.aaas_desktop_mode",
        "behavior": "InputMethodService does not show its input view when desktop mode is enabled",
    }


def _read_zip_entry(path, name):
    with zipfile.ZipFile(path) as archive:
        return archive.read(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--apktool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-parent", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = build_overlay(args.original, args.apktool, args.output, args.work_parent)
    rendered = json.dumps(receipt, indent=2) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
