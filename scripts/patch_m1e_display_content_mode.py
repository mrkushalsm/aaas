#!/usr/bin/env python3
"""Build the opt-in M1E display-content compatibility overlay.

The input is the preserved M1B.8 services diagnostic overlay. Only classes.dex
is rebuilt. The stock services.jar and default runtime are never modified.
"""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches/m1e/display-content-mode-compat.patch"
SOURCE = ROOT / "experiments/m1e/framework_refs/DisplayManagerFlags.java"
SOURCE_SHA256 = "a0f68c8fd2f7fb06810f0efde60cf3c1d378bed2d5ce979c81ff6a7bc29022e3"
SOURCE_REVISION = "99b01a65cc4c104933788b3143285ab6bae65827"
BASE_SHA256 = "878461b6366adad72b86b06f3defaa7c44a2dc0bdb83cc2f31789fe7845e8359"
APKTOOL_SHA256 = "dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423"
DEX_CLASS = Path("smali/com/android/server/display/feature/DisplayManagerFlags.smali")
METHOD = ".method public isDisplayContentModeManagementEnabled()Z"
END = ".end method"
BODY = '''.method public isDisplayContentModeManagementEnabled()Z
    .locals 2

    const-string v0, "debug.aaas.display_content_mode_management"

    const/4 v1, 0x0

    invoke-static {v0, v1}, Landroid/os/SystemProperties;->getBoolean(Ljava/lang/String;Z)Z

    move-result v0

    if-nez v0, :aaas_display_content_mode_enabled

    iget-object v0, p0, Lcom/android/server/display/feature/DisplayManagerFlags;->mEnableDisplayContentModeManagementFlagState:Lcom/android/server/display/feature/DisplayManagerFlags$FlagState;

    invoke-static {v0}, Lcom/android/server/display/feature/DisplayManagerFlags$FlagState;->-$$Nest$misEnabled(Lcom/android/server/display/feature/DisplayManagerFlags$FlagState;)Z

    move-result v0

    :aaas_display_content_mode_enabled
    return v0
.end method'''


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def patch_smali(source):
    if source.count(METHOD) != 1:
        raise RuntimeError("DisplayManagerFlags method signature mismatch")
    start = source.index(METHOD)
    end = source.index(END, start) + len(END)
    current = source[start:end]
    if "debug.aaas.display_content_mode_management" in current:
        raise RuntimeError("display-content compatibility is already applied")
    if "mEnableDisplayContentModeManagementFlagState" not in current:
        raise RuntimeError("DisplayManagerFlags implementation differs from pinned image")
    return source[:start] + BODY + source[end:]


def build_overlay(original, apktool, output, work_parent=None):
    original, apktool, output = map(lambda p: Path(p).resolve(),
                                    (original, apktool, output))
    if original == output:
        raise ValueError("output must not replace the preserved input overlay")
    if sha256(original) != BASE_SHA256:
        raise ValueError("services diagnostic overlay checksum mismatch")
    if sha256(apktool) != APKTOOL_SHA256:
        raise ValueError("apktool checksum mismatch")
    if sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("pinned DisplayManagerFlags source checksum mismatch")
    source_text = SOURCE.read_text()
    if source_text.count("return mEnableDisplayContentModeManagementFlagState.isEnabled();") != 1:
        raise RuntimeError("pinned Java source contract changed")
    if not PATCH.is_file() or "debug.aaas.display_content_mode_management" not in PATCH.read_text():
        raise RuntimeError("source patch missing or inconsistent")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aaas-m1e-services-", dir=work_parent) as td:
        td = Path(td)
        decoded, rebuilt = td / "decoded", td / "rebuilt.apk"
        subprocess.run(["java", "-jar", str(apktool), "d", "-f", "-r",
                        str(original), "-o", str(decoded)], check=True)
        smali = decoded / DEX_CLASS
        if not smali.is_file():
            raise RuntimeError(f"pinned framework class not found: {smali}")
        smali.write_text(patch_smali(smali.read_text()))
        subprocess.run(["java", "-jar", str(apktool), "b", str(decoded),
                        "-o", str(rebuilt)], check=True)
        with zipfile.ZipFile(rebuilt) as built:
            patched_dex = built.read("classes.dex")
        staged = output.with_suffix(output.suffix + ".tmp")
        try:
            with zipfile.ZipFile(original) as src, zipfile.ZipFile(staged, "w") as dst:
                if src.namelist().count("classes.dex") != 1:
                    raise RuntimeError("expected one classes.dex entry")
                for info in src.infolist():
                    dst.writestr(info, patched_dex if info.filename == "classes.dex"
                                 else src.read(info.filename))
            os.replace(staged, output)
        finally:
            staged.unlink(missing_ok=True)

    with zipfile.ZipFile(output) as built:
        if built.namelist().count("classes.dex") != 1:
            raise RuntimeError("output overlay has invalid dex structure")
        dex_hash = hashlib.sha256(built.read("classes.dex")).hexdigest()
    return {
        "input": str(original), "input_sha256": sha256(original),
        "output": str(output), "output_sha256": sha256(output),
        "classes_dex_sha256": dex_hash,
        "changed_entry": "classes.dex",
        "source_revision": SOURCE_REVISION,
        "source_path": str(SOURCE.relative_to(ROOT)),
        "source_sha256": SOURCE_SHA256,
        "source_patch": str(PATCH.relative_to(ROOT)),
        "source_patch_sha256": sha256(PATCH),
        "property": "debug.aaas.display_content_mode_management",
        "default_behavior": "stock Aconfig flag unless the experimental session sets the property",
        "apktool_sha256": APKTOOL_SHA256,
    }


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
