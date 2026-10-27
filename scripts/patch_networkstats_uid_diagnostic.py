#!/usr/bin/env python3
"""Diagnostic only: let a missing UID BPF map return an invalid FD.

This mirrors the source-level unavailable-map patch while its Android build is
pending. The existing two-template diagnostic is the only accepted input.
Never deploy the output as the sole implementation of NetworkStats handling.
"""

import hashlib
from pathlib import Path
import sys


INPUT_SHA256 = "a2fd5b8bb3471957fb3c7577f210db1eafbfbf697ce0be08522570e2d9bfd75a"
OFFSET = 0x18EF0
BEFORE = bytes.fromhex("0f887a020000")  # js abort at 0x19170
AFTER = bytes.fromhex("0f885d020000")   # js checked return at 0x19153


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_networkstats_uid_diagnostic.py INPUT OUTPUT")
    source, target = map(Path, sys.argv[1:])
    data = bytearray(source.read_bytes())
    if hashlib.sha256(data).hexdigest() != INPUT_SHA256:
        raise SystemExit("input checksum differs from retained diagnostic baseline")
    if data[OFFSET:OFFSET + len(BEFORE)] != BEFORE:
        raise SystemExit("UID-map abort branch differs from inspected machine code")
    data[OFFSET:OFFSET + len(BEFORE)] = AFTER
    target.write_bytes(data)
    print(hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
