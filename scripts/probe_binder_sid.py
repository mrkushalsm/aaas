#!/usr/bin/env python3
"""Compare Binder transactions with and without caller security contexts."""

import fcntl
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


SOURCE = Path(__file__).resolve().parents[1] / "experiments/m1b/probe_binder_sid.c"


def child(binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="aaas-binder-sid-") as directory:
        subprocess.run(["mount", "-t", "binder", "binder", directory], check=True)
        try:
            control = os.open(f"{directory}/binder-control", os.O_RDWR)
            try:
                request = bytearray(struct.pack("256sII", b"aaas-sid", 0, 0))
                fcntl.ioctl(control, 0xC1086201, request)
            finally:
                os.close(control)
            for flag in (0, 1):
                output = subprocess.check_output(
                    [str(binary), f"{directory}/aaas-sid", str(flag)],
                    text=True,
                    timeout=5,
                ).strip()
                print(output, flush=True)
        finally:
            subprocess.run(["umount", directory], check=True)


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]))
        return
    if len(sys.argv) != 1:
        raise SystemExit("usage: probe_binder_sid.py")
    with tempfile.TemporaryDirectory(prefix="aaas-binder-sid-build-") as directory:
        binary = Path(directory) / "probe_binder_sid"
        subprocess.run(
            ["cc", "-Wall", "-Wextra", "-Werror", "-O2", "-o", str(binary), str(SOURCE)],
            check=True,
        )
        result = subprocess.run(
            ["unshare", "-Ur", "-m", sys.executable, str(Path(__file__).resolve()), "--child", str(binary)],
            check=True,
            text=True,
            capture_output=True,
            timeout=15,
        )
        lines = result.stdout.splitlines()
        if len(lines) != 2 or "command=0x7206" not in lines[0] or "command=0x7211" not in lines[1]:
            raise RuntimeError(f"unexpected Binder replies: {lines!r}")
        print(json.dumps({"without_sid": lines[0], "with_sid": lines[1]}, indent=2))


if __name__ == "__main__":
    main()
