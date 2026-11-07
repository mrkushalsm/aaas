#!/usr/bin/env python3
"""Build the tiny Android x86_64 legacy-ashmem session compatibility shim."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess

SOURCE = Path(__file__).with_name('ashmem_compat.c')


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clang', default='clang')
    args = parser.parse_args()
    rootfs = args.rootfs.resolve(strict=True)
    libc = rootfs / 'vendor/lib64/libc.so'
    if not libc.exists():
        libc = rootfs / 'system/lib64/libc.so'
    if not libc.exists():
        raise SystemExit('Android x86_64 Bionic libc not found')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    obj = args.output.with_suffix('.o')
    subprocess.run([args.clang, '-target', 'x86_64-linux-android36', '-std=gnu11',
                    '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-c', str(SOURCE), '-o', str(obj)], check=True)
    subprocess.run([args.clang, '-target', 'x86_64-linux-android36', '-nostdlib',
                    '-shared', str(obj), '-L', str(libc.parent), '-lc',
                    '-Wl,--no-undefined', '-Wl,-soname,libaaas-audio-ashmem.so',
                    '-o', str(args.output)], check=True)
    header = subprocess.run(['readelf', '-h', str(args.output)], check=True,
                            capture_output=True, text=True).stdout
    symbols = subprocess.run(['readelf', '-Ws', str(args.output)], check=True,
                             capture_output=True, text=True).stdout
    if 'Advanced Micro Devices X86-64' not in header or 'ashmem_create_region' not in symbols:
        raise SystemExit('invalid Android x86_64 ashmem shim')
    obj.unlink(missing_ok=True)
    print(f'{args.output} sha256={sha256(args.output)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
