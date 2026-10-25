#!/usr/bin/env python3
"""Probe the host Binder context-manager ioctl in a disposable user namespace."""

import fcntl
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


BINDER_CTL_ADD = 0xC1086201
BINDER_SET_CONTEXT_MGR_EXT = 0x4018620D
FLAT_BINDER_FLAG_TXN_SECURITY_CTX = 0x1000


def child():
    with tempfile.TemporaryDirectory(prefix="aaas-binder-ctx-") as directory:
        subprocess.run(["mount", "-t", "binder", "binder", directory], check=True)
        try:
            control = os.open(f"{directory}/binder-control", os.O_RDWR)
            try:
                request = bytearray(struct.pack("256sII", b"aaas-ctx", 0, 0))
                fcntl.ioctl(control, BINDER_CTL_ADD, request)
            finally:
                os.close(control)
            device = os.open(f"{directory}/aaas-ctx", os.O_RDWR)
            try:
                context = bytearray(struct.pack("IIQQ", 0, FLAT_BINDER_FLAG_TXN_SECURITY_CTX, 0, 0))
                try:
                    fcntl.ioctl(device, BINDER_SET_CONTEXT_MGR_EXT, context)
                    result = {"accepted": True, "errno": None}
                except OSError as error:
                    result = {"accepted": False, "errno": error.errno}
                print(json.dumps(result, sort_keys=True))
            finally:
                os.close(device)
        finally:
            subprocess.run(["umount", directory], check=True)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--child":
        child()
    elif len(sys.argv) == 1:
        subprocess.run(["unshare", "-Ur", "-m", sys.executable, str(Path(__file__).resolve()), "--child"], check=True)
    else:
        raise SystemExit("usage: probe_binder_context_manager.py")
