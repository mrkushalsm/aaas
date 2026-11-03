#!/usr/bin/env python3
"""Build a minimal, permission-free AaaS Android latency probe APK."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile

ANDROID_NS = "http://schemas.android.com/apk/res/android"
NO_INDEX = 0xFFFFFFFF
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_BOOLEAN = 0x12


def chunk(kind: int, header_size: int, body: bytes) -> bytes:
    return struct.pack("<HHI", kind, header_size, 8 + len(body)) + body


def uleb(value: int) -> bytes:
    if value < 0x80:
        return bytes([value])
    return bytes([(value & 0x7F) | 0x80, value >> 7])


def string_pool(strings: list[str]) -> bytes:
    offsets = []
    data = bytearray()
    for value in strings:
        encoded = value.encode("utf-8")
        utf16_len = len(value.encode("utf-16le")) // 2
        offsets.append(len(data))
        data.extend(uleb(utf16_len))
        data.extend(uleb(len(encoded)))
        data.extend(encoded)
        data.append(0)
    while len(data) % 4:
        data.append(0)
    strings_start = 28 + 4 * len(strings)
    body = struct.pack("<IIIII", len(strings), 0, 0x100, strings_start, 0)
    body += b"".join(struct.pack("<I", off) for off in offsets)
    body += data
    return chunk(0x0001, 28, body)


def xml_node(kind: int, ext: bytes) -> bytes:
    body = struct.pack("<II", 1, NO_INDEX) + ext
    return chunk(kind, 16, body)


def namespace(kind: int, prefix: int, uri: int) -> bytes:
    return xml_node(kind, struct.pack("<II", prefix, uri))


def attribute(ns: int, name: int, value: int | str | bool, index: dict[str, int]) -> bytes:
    if isinstance(value, bool):
        raw = NO_INDEX
        typ, data = TYPE_INT_BOOLEAN, int(value)
    elif isinstance(value, int):
        raw = NO_INDEX
        typ, data = TYPE_INT_DEC, value
    else:
        raw = index[value]
        typ, data = TYPE_STRING, index[value]
    return struct.pack("<IIIHBBI", ns, name, raw, 8, 0, typ, data)


def start_element(strings: list[str], tag: str, attrs: list[tuple[str | None, str, int | str | bool]]) -> bytes:
    index = {s: i for i, s in enumerate(strings)}
    attr_bytes = b"".join(attribute(NO_INDEX if ns is None else index[ANDROID_NS], index[name], value, index)
                          for ns, name, value in attrs)
    ext = struct.pack("<IIHHHHHH", NO_INDEX, index[tag], 20, 20, len(attrs), 0, 0, 0)
    return xml_node(0x0102, ext + attr_bytes)


def end_element(strings: list[str], tag: str) -> bytes:
    return xml_node(0x0103, struct.pack("<II", NO_INDEX, strings.index(tag)))


def binary_manifest(package_name: str) -> bytes:
    strings = [
        "android", ANDROID_NS, "manifest", "package", package_name,
        "versionCode", "versionName", "1.0", "uses-sdk", "minSdkVersion",
        "targetSdkVersion", "application", "hasCode", "label", "AaaS Input Probe",
        "activity", "name", ".ProbeActivity", "exported", "intent-filter",
        "action", "category", "android.intent.action.MAIN",
        "android.intent.category.LAUNCHER",
    ]
    nodes = [
        namespace(0x0100, 0, 1),
        start_element(strings, "manifest", [
            (None, "package", package_name),
            ("android", "versionCode", 1), ("android", "versionName", "1.0"),
        ]),
        start_element(strings, "uses-sdk", [
            ("android", "minSdkVersion", 28), ("android", "targetSdkVersion", 28),
        ]),
        end_element(strings, "uses-sdk"),
        start_element(strings, "application", [
            ("android", "hasCode", True), ("android", "label", "AaaS Input Probe"),
        ]),
        start_element(strings, "activity", [
            ("android", "name", ".ProbeActivity"), ("android", "exported", True),
            ("android", "label", "AaaS Input Probe"),
        ]),
        start_element(strings, "intent-filter", []),
        start_element(strings, "action", [("android", "name", "android.intent.action.MAIN")]),
        end_element(strings, "action"),
        start_element(strings, "category", [("android", "name", "android.intent.category.LAUNCHER")]),
        end_element(strings, "category"),
        end_element(strings, "intent-filter"),
        end_element(strings, "activity"),
        end_element(strings, "application"),
        end_element(strings, "manifest"),
        namespace(0x0101, 0, 1),
    ]
    attr_ids = {
        "label": 0x01010001, "name": 0x01010003, "hasCode": 0x0101000C,
        "exported": 0x01010010, "minSdkVersion": 0x0101020C,
        "versionCode": 0x0101021B, "versionName": 0x0101021C,
        "targetSdkVersion": 0x01010270,
    }
    resource_map = chunk(0x0180, 8, b"".join(
        struct.pack("<I", attr_ids.get(value, 0)) for value in strings))
    body = string_pool(strings) + resource_map + b"".join(nodes)
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apktool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package", default="org.aaas.latencyprobe")
    parser.add_argument("--animation-hz", type=int, choices=(0, 30, 60), default=0,
                        help="opt-in continuous sequence-marker rendering cadence")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", args.package):
        parser.error("--package must be a dotted Android package name")
    root = Path(__file__).resolve().parent
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aaas-latency-probe-") as temp:
        work = Path(temp) / "project"
        work.mkdir()
        shutil.copytree(root / "smali", work / "smali")
        for smali_file in (work / "smali").rglob("*.smali"):
            text = smali_file.read_text()
            text = text.replace("org.aaas.latencyprobe", args.package)
            text = text.replace("org/aaas/latencyprobe", args.package.replace(".", "/"))
            if smali_file.name == "MarkerView.smali":
                period_ns = 0 if args.animation_hz == 0 else 1_000_000_000 // args.animation_hz
                text = text.replace("__ANIMATION_PERIOD_NS__",
                                    f"0x{period_ns:x}")
            smali_file.write_text(text)
        (work / "AndroidManifest.xml").write_bytes(binary_manifest(args.package))
        (work / "apktool.yml").write_text(
            "version: 3.0.3\napkFileName: AaasLatencyProbe.apk\n"
            "sdkInfo:\n  minSdkVersion: 28\n  targetSdkVersion: 28\n"
            "versionInfo:\n  versionCode: 1\n  versionName: 1.0\n"
        )
        subprocess.run(["java", "-jar", str(args.apktool), "b", "--no-apk", str(work)], check=True)
        dex_candidates = list((work / "build").rglob("classes.dex"))
        if not dex_candidates:
            raise RuntimeError("apktool did not emit classes.dex")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as apk:
            apk.write(work / "AndroidManifest.xml", "AndroidManifest.xml")
            apk.write(dex_candidates[0], "classes.dex")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
