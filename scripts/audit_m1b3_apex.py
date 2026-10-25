#!/usr/bin/env python3
"""Read-only APEX package inventory; never treats extraction as activation."""

import argparse
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("truncated varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError("oversized varint")


def manifest(data):
    """Decode only fields needed from AOSP ApexManifest, rejecting bad wire data."""
    result = {"provides": [], "requires": []}
    offset = 0
    while offset < len(data):
        tag, offset = varint(data, offset)
        field, wire = tag >> 3, tag & 7
        if not field:
            raise ValueError("invalid protobuf field zero")
        if wire == 0:
            value, offset = varint(data, offset)
        elif wire == 2:
            length, offset = varint(data, offset)
            if length > len(data) - offset:
                raise ValueError("truncated protobuf field")
            value = data[offset:offset + length]
            offset += length
        elif wire == 1:
            offset += 8
            if offset > len(data):
                raise ValueError("truncated fixed64")
            continue
        elif wire == 5:
            offset += 4
            if offset > len(data):
                raise ValueError("truncated fixed32")
            continue
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        if field in (1, 7, 8):
            if wire != 2:
                raise ValueError(f"wrong wire type for field {field}")
            value = value.decode("utf-8")
            if field == 1:
                result["name"] = value
            else:
                result["provides" if field == 7 else "requires"].append(value)
        elif field in (2, 6, 16):
            if wire != 0:
                raise ValueError(f"wrong wire type for field {field}")
            result[{2: "version", 6: "no_code", 16: "bootstrap"}[field]] = value
    if not result.get("name") or "version" not in result:
        raise ValueError("missing APEX name or version")
    return result


def package_manifest(path):
    with zipfile.ZipFile(path) as package:
        outer = manifest(package.read("apex_manifest.pb"))
        if path.suffix == ".capex":
            with zipfile.ZipFile(io.BytesIO(package.read("original_apex"))) as original:
                inner = manifest(original.read("apex_manifest.pb"))
            if (outer["name"], outer["version"]) != (inner["name"], inner["version"]):
                raise ValueError("CAPEX and original APEX identities differ")
        return outer


def audit(rootfs):
    rootfs = Path(rootfs)
    entries = ET.parse(rootfs / "apex/apex-info-list.xml").getroot().findall("apex-info")
    modules = []
    errors = []
    for entry in entries:
        name = entry.get("moduleName")
        path = entry.get("modulePath", "")
        record = {"name": name, "declared_version": entry.get("versionCode"),
                  "package": path, "active_claim": entry.get("isActive") == "true"}
        try:
            if not path.startswith(("/system/apex/", "/vendor/apex/")) or ".." in Path(path).parts:
                raise ValueError("package path outside declared APEX directories")
            package = rootfs / path.lstrip("/")
            if not package.is_file():
                raise ValueError("source package missing")
            metadata = package_manifest(package)
            record["manifest"] = metadata
            if metadata["name"] != name or str(metadata["version"]) != record["declared_version"]:
                raise ValueError("package metadata differs from apex-info-list")
            staged = rootfs / "apex" / name / "apex_manifest.pb"
            record["staged_manifest_present"] = staged.is_file()
            if staged.is_file():
                staged_metadata = manifest(staged.read_bytes())
                if (staged_metadata["name"], staged_metadata["version"]) != (name, metadata["version"]):
                    raise ValueError("staged payload identity differs from package")
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            record["error"] = str(exc)
            errors.append({"name": name, "error": str(exc)})
        modules.append(record)
    names = [item["name"] for item in modules]
    if len(names) != len(set(names)):
        errors.append({"error": "duplicate module names"})
    providers = {}
    for item in modules:
        for library in item.get("manifest", {}).get("provides", []):
            providers.setdefault(library, []).append(item["name"])
    dependencies = []
    for item in modules:
        for library in item.get("manifest", {}).get("requires", []):
            dependencies.append({"module": item["name"], "library": library,
                                 "apex_providers": providers.get(library, [])})
    return {"schema": 1, "source": "diagnostic rootfs original package archives",
            "module_count": len(modules), "modules": modules, "native_library_dependencies": dependencies,
            "errors": errors, "activation_verified": False,
            "reason": "archive metadata and staged payloads do not establish apexd verification or mounts"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.rootfs)
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")
    raise SystemExit(bool(report["errors"]))


if __name__ == "__main__":
    main()
