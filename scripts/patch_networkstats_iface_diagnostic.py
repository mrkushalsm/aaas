#!/usr/bin/env python3
"""Skip optional BPF interface-stat registration in the rootless Android VM.

This leaves routing, DNS, and packet forwarding untouched. The Android image's
NetworkStats BPF map is unavailable in this user namespace; registering an
interface reaches an aborting BPF map metadata check. Only the exported
bpfRegisterIface entry point is replaced with a return instruction. Per-UID
and aggregate stats retain their existing diagnostic behavior.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

INPUT_SHA256 = '18b466f60eb856d7ad4cbcb683a4566a0cf20280bad63a5543515b044cb051d7'
OFFSET = 0x6FB00
EXPECTED = bytes.fromhex('e92b9dfaff')
PATCHED = bytes.fromhex('c390909090')


def patch(source: Path, output: Path) -> str:
    data = bytearray(source.read_bytes())
    if hashlib.sha256(data).hexdigest() != INPUT_SHA256:
        raise RuntimeError('networkstats input differs from the reviewed diagnostic build')
    if data[OFFSET:OFFSET + len(EXPECTED)] != EXPECTED:
        raise RuntimeError('bpfRegisterIface entry bytes differ; refusing binary patch')
    data[OFFSET:OFFSET + len(PATCHED)] = PATCHED
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    temporary.write_bytes(data)
    temporary.replace(output)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(patch(args.input, args.output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
