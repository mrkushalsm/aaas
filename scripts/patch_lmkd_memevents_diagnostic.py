#!/usr/bin/env python3
"""Diagnostic LMKD overlay: exercise its existing vmstats fallback.

Only for an AaaS container where the pinned LMKD memevents ring buffer is
absent. The production correction belongs in the source-level capability
check; this overlay is an experiment against one identified Android 16 ELF.
"""

import argparse
import hashlib
from pathlib import Path

INPUT_SHA256 = "46af90db625b96ecd71c70d2d7f2712887f618e32ed56d80e9719902450851c0"
OFFSET = 0xDC60
BEFORE = bytes.fromhex("554889")  # push rbp; mov rbp,...
AFTER = bytes.fromhex("31c0c3")  # return false from init_memevent_listener_monitoring


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = bytearray(args.source.read_bytes())
    if hashlib.sha256(data).hexdigest() != INPUT_SHA256:
        parser.error("input checksum differs from the inspected Android 16 lmkd")
    if data[OFFSET:OFFSET + len(BEFORE)] != BEFORE:
        parser.error("function prologue differs from inspected disassembly")
    if args.source.resolve() == args.output.resolve():
        parser.error("output must be a separate diagnostic overlay")
    data[OFFSET:OFFSET + len(BEFORE)] = AFTER
    args.output.write_bytes(data)
    args.output.chmod(0o755)
    print(hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
