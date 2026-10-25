#!/usr/bin/env python3
"""Build a host APEX manifest parser from the pinned Android 16 schema."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time
from urllib.request import urlopen

SCHEMA_SHA256 = "e9505454f5fa759c6364e8680542f48b219f1b57d394a63deadfcfc6e8268ce7"


def run(command, cwd=None):
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {command}\n{result.stdout}{result.stderr}")
    return result.stdout + result.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "manifests/android16-r1-subset.json").read_text())
    project = next(item for item in lock["projects"] if item["path"] == "system/apex")
    run(["python3", str(root / "scripts/android_workspace.py"), "--workspace",
         str(args.workspace), "--predict-gib", "0.1", "check"])
    build = args.workspace / "m1b4/apex-proto"
    build.mkdir(parents=True, exist_ok=True)
    url = f'{project["repository"]}/+/{project["revision"]}/proto/apex_manifest.proto?format=TEXT'
    data = base64.b64decode(urlopen(url, timeout=30).read(), validate=True)
    digest = hashlib.sha256(data).hexdigest()
    if digest != SCHEMA_SHA256:
        raise RuntimeError(f"schema digest mismatch: {digest}")
    (build / "apex_manifest.proto").write_bytes(data)
    run(["protoc", "--cpp_out=.", "apex_manifest.proto"], cwd=build)
    flags = run(["pkg-config", "--cflags", "--libs", "protobuf"]).split()
    compile_command = ["clang++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                       "-I.", "apex_manifest.pb.cc",
                       str(root / "experiments/m1b4/apex_manifest_probe.cpp"),
                       "-o", "apex_manifest_probe", *flags]
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    start = time.monotonic()
    run(compile_command, cwd=build)
    elapsed = time.monotonic() - start
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    samples = {}
    for name in ("com.android.runtime", "com.android.art"):
        path = args.workspace / "rootfs_m1b1/apex" / name / "apex_manifest.pb"
        samples[name] = run([str(build / "apex_manifest_probe"), str(path)]).strip()
        if not samples[name].startswith(f"name={name} "):
            raise RuntimeError(f"unexpected parsed identity: {samples[name]}")
    dynamic = run(["readelf", "-d", str(build / "apex_manifest_probe")])
    needed = [line.split("[")[1].split("]")[0] for line in dynamic.splitlines() if "(NEEDED)" in line]
    report = {"schema": 1, "source_revision": project["revision"],
              "source_url": url, "source_sha256": digest, "host_only": True,
              "protoc": run(["protoc", "--version"]).strip(),
              "clang": run(["clang++", "--version"]).splitlines()[0],
              "protobuf_pkg_version": run(["pkg-config", "--modversion", "protobuf"]).strip(),
              "compile_command": compile_command, "compile_exit": 0,
              "elapsed_seconds": round(elapsed, 3), "peak_compiler_rss_kib": peak,
              "previous_child_peak_rss_kib": before, "build_bytes": sum(p.stat().st_size for p in build.iterdir() if p.is_file()),
              "binary_needed": needed, "samples": samples,
              "limitation": "host glibc/protobuf parser; not an Android target binary or platform ABI check"}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("compile_exit", "elapsed_seconds", "build_bytes", "samples")}, indent=2))


if __name__ == "__main__":
    main()
