#!/usr/bin/env python3
"""Build and run the bounded SwiftShader Marl ticket lifetime contract test."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "experiments/graphics-stability/renderer_ticket_lifetime.cpp"
PINNED_REVISION = "cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5"


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--swiftshader-root",
        type=Path,
        default=Path("/run/media/mrkus/Aaas/aaas-workspace/sources/swiftshader"),
    )
    parser.add_argument("--sanitize", action="store_true",
                        help="build the harness with ASan and UBSan")
    args = parser.parse_args()
    root = args.swiftshader_root.resolve()
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != PINNED_REVISION:
        raise SystemExit(f"expected SwiftShader {PINNED_REVISION}, got {revision}")
    include = root / "third_party/marl/include"
    library = root / "build/third_party/marl/libmarl.a"
    if not include.is_dir() or not library.is_file():
        raise SystemExit("pinned SwiftShader Marl headers/library are unavailable")
    with tempfile.TemporaryDirectory(prefix="aaas-swiftshader-lifetime-") as tmp:
        binary = Path(tmp) / "renderer-ticket-lifetime"
        compile_cmd = [
            os.environ.get("CXX", "c++"), "-std=c++17", "-O2", "-g",
            "-Wall", "-Wextra", "-Werror", "-pthread",
            "-I", str(include), str(SOURCE), str(library), "-o", str(binary),
        ]
        if args.sanitize:
            compile_cmd[1:1] = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        subprocess.run(compile_cmd, check=True, timeout=120)
        result = subprocess.run(
            [str(binary)], check=False, capture_output=True, text=True, timeout=10
        )
        record = {
            "test": "swiftshader_renderer_ticket_lifetime_contract",
            "source_revision": revision,
            "source_sha256": sha256(SOURCE),
            "sanitized": args.sanitize,
            "marl_library": str(library),
            "marl_library_sha256": sha256(library),
            "compile_command": compile_cmd,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "semantics": (
                "Exercises the pinned SwiftShader Marl Ticket::Queue used by "
                "Renderer::draw and Renderer::synchronize with a deterministic "
                "in-flight worker gate; the invalid-ordering control checks a "
                "liveness guard and never dereferences released memory."
            ),
        }
        print(json.dumps(record, indent=2))
        if result.returncode != 0:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
