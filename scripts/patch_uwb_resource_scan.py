#!/usr/bin/env python3
"""Build the M1B.8 UWB APEX resource scan compatibility overlay.

The original signed resources APK is scanned through the system_ext path in
the extracted Android image. Keep the APEX check and accept that one path for
that one package. Never modify the original runtime JAR in place.
"""

import argparse
import hashlib
import subprocess
import tempfile
import zipfile
from pathlib import Path

ORIGINAL_SHA256 = "2960d2681e4998d20c9f87e449a97c2d5f8abcf45061ef75a1e8d091dee1a97b"
SOURCE = Path("smali/com/android/server/uwb/UwbContext.smali")
OLD = """    .locals 1

    .line 70
    iget-object p0, p0, Landroid/content/pm/ApplicationInfo;->sourceDir:Ljava/lang/String;

    sget-object v0, Lcom/android/server/uwb/UwbContext;->UWB_APEX_PATH:Ljava/lang/String;

    invoke-virtual {p0, v0}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z

    move-result p0

    return p0
.end method"""
NEW = """    .locals 2

    .line 70
    iget-object v0, p0, Landroid/content/pm/ApplicationInfo;->sourceDir:Ljava/lang/String;

    sget-object v1, Lcom/android/server/uwb/UwbContext;->UWB_APEX_PATH:Ljava/lang/String;

    invoke-virtual {v0, v1}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z

    move-result v1

    if-nez v1, :accepted

    iget-object v1, p0, Landroid/content/pm/ApplicationInfo;->packageName:Ljava/lang/String;

    const-string p0, "com.android.uwb.resources"

    invoke-virtual {v1, p0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result p0

    if-eqz p0, :rejected

    const-string p0, "/system_ext/priv-app/ServiceUwbResources/"

    invoke-virtual {v0, p0}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z

    move-result p0

    return p0

    :accepted
    const/4 p0, 0x1

    return p0

    :rejected
    const/4 p0, 0x0

    return p0
.end method"""


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--apktool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sha256(args.original) != ORIGINAL_SHA256:
        parser.error("original JAR checksum differs from the Android 16 baseline")
    if args.output.resolve() == args.original.resolve():
        parser.error("output must not replace the original JAR")

    with tempfile.TemporaryDirectory(prefix="aaas-uwb-") as temp:
        temp = Path(temp)
        decoded = temp / "decoded"
        rebuilt = temp / "rebuilt.apk"
        subprocess.run(["java", "-jar", str(args.apktool), "d", "-f", "-r",
                        str(args.original), "-o", str(decoded)], check=True)
        smali = decoded / SOURCE
        source = smali.read_text()
        start = source.index(".method private static isAppInUwbApex(")
        end = source.index(".end method", start) + len(".end method")
        method = source[start:end]
        if method.count(OLD) != 1:
            raise RuntimeError("unexpected UwbContext bytecode; patch not applied")
        method = method.replace(OLD, NEW, 1)
        smali.write_text(source[:start] + method + source[end:])
        subprocess.run(["java", "-jar", str(args.apktool), "b",
                        str(decoded), "-o", str(rebuilt)], check=True)
        with zipfile.ZipFile(rebuilt) as package:
            dex = package.read("classes.dex")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.original) as original, zipfile.ZipFile(args.output, "w") as output:
            for info in original.infolist():
                output.writestr(info, dex if info.filename == "classes.dex" else original.read(info.filename))
    print(f"{args.output}: sha256={sha256(args.output)}")


if __name__ == "__main__":
    main()
