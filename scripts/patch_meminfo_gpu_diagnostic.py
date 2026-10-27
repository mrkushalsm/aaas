#!/usr/bin/env python3
"""Diagnostic only: preserve libmeminfo's error path for an absent GPU BPF map.

The source-level fix is patches/m1b81/libmeminfo-unavailable-gpu-map.patch.
This binary branch adjustment is for a reversible boot-boundary experiment.
"""

import hashlib
from pathlib import Path
import sys


INPUT_SHA256 = "f0793a8cd9c637d4b4e1e3c4aec30d1821a1768a6b6d882b045b4bc2f22f4e3c"
OFFSET = 0x13E2E
BEFORE = bytes.fromhex("0f885e020000")  # js abort at 0x14092
AFTER = bytes.fromhex("0f8843020000")   # js normal return at 0x14077


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_meminfo_gpu_diagnostic.py INPUT OUTPUT")
    source, target = map(Path, sys.argv[1:])
    data = bytearray(source.read_bytes())
    if hashlib.sha256(data).hexdigest() != INPUT_SHA256:
        raise SystemExit("input checksum differs from inspected Android image")
    if data[OFFSET:OFFSET + len(BEFORE)] != BEFORE:
        raise SystemExit("BPF map abort branch differs from inspected machine code")
    data[OFFSET:OFFSET + len(BEFORE)] = AFTER
    target.write_bytes(data)
    print(hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
