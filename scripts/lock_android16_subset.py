#!/usr/bin/env python3
"""Resolve selected AOSP projects from one immutable release manifest tag."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import subprocess
from urllib.request import urlopen
import base64
import xml.etree.ElementTree as ET


TAG = "android-16.0.0_r1"
MANIFEST_URL = "https://android.googlesource.com/platform/manifest"
PATHS = (
    "build/make", "build/blueprint", "build/release", "build/soong",
    "art", "bionic", "external/minigbm", "external/protobuf",
    "frameworks/base", "frameworks/native", "hardware/interfaces",
    "prebuilts/clang/host/linux-x86", "prebuilts/go/linux-x86",
    "system/apex", "system/core", "system/sepolicy",
)
HEX = re.compile(r"[0-9a-f]{40}\Z")


def revision(url, tag=TAG):
    result = subprocess.run(["git", "ls-remote", url,
                             f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
                            capture_output=True, text=True, check=True, timeout=60)
    refs = dict(line.split("\t", 1)[::-1] for line in result.stdout.splitlines())
    commit = refs.get(f"refs/tags/{tag}^{{}}", refs.get(f"refs/tags/{tag}"))
    if not commit or not HEX.fullmatch(commit):
        raise ValueError(f"missing immutable tag {tag}: {url}")
    return commit


def lock():
    manifest_commit = revision(MANIFEST_URL)
    encoded = urlopen(f"{MANIFEST_URL}/+/{manifest_commit}/default.xml?format=TEXT", timeout=30).read()
    xml = base64.b64decode(encoded, validate=True)
    root = ET.fromstring(xml)
    if root.find("default").get("revision") != f"refs/tags/{TAG}":
        raise ValueError("manifest default revision differs from release tag")
    superproject = root.find("superproject")
    if superproject is None or superproject.get("revision") != TAG:
        raise ValueError("manifest superproject revision differs from release tag")
    projects = {item.get("path", item.get("name")): item for item in root.findall("project")}
    for path in PATHS:
        if path not in projects or projects[path].get("revision", f"refs/tags/{TAG}") != f"refs/tags/{TAG}":
            raise ValueError(f"missing or overridden project: {path}")
    def resolve(path):
        name = projects[path].get("name")
        url = f"https://android.googlesource.com/{name}"
        return {"path": path, "repository": url, "revision": revision(url)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        resolved = list(pool.map(resolve, PATHS))
    return {"schema": 1, "release_tag": TAG, "manifest_repository": MANIFEST_URL,
            "manifest_revision": manifest_commit, "manifest_sha256": hashlib.sha256(xml).hexdigest(),
            "superproject_ref": TAG, "projects": resolved,
            "scope": "selected component inventory; not a complete repo sync or minimal-product closure"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with open(args.output, "w") as stream:
        json.dump(lock(), stream, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    main()
