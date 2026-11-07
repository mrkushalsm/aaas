#!/usr/bin/env python3
"""Reproducibly build the x86_64 Android primary HAL overlay."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
SOURCE_DIR = Path(__file__).resolve().parent
HAL_SOURCE = SOURCE_DIR / 'audio_hal.c'
PROTOCOL_HEADER = SOURCE_DIR / 'audio_protocol.h'
INCLUDE_DIR = SOURCE_DIR / 'android-headers'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True,
                        help='Android rootfs used for Bionic link libraries')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clang', default='clang')
    args = parser.parse_args()
    rootfs = args.rootfs.resolve(strict=True)
    libc = rootfs / 'system/lib64/libc.so'
    if not libc.exists():
        raise SystemExit(f'Android Bionic libc not found: {libc}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output = args.output.resolve()
    obj = args.output.with_suffix('.o')
    subprocess.run([args.clang, '-target', 'x86_64-linux-android36', '-std=gnu11',
                    '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I', str(INCLUDE_DIR), '-I', str(SOURCE_DIR),
                    '-c', str(HAL_SOURCE), '-o', str(obj)], check=True)
    subprocess.run([args.clang, '-target', 'x86_64-linux-android36', '-nostdlib',
                    '-shared', str(obj), '-L', str(libc.parent), '-lc', '-llog',
                    '-Wl,--no-undefined', '-Wl,-soname,audio.primary.aaas.so',
                    '-o', str(args.output)], check=True)
    readelf = subprocess.run(['readelf', '-h', str(args.output)], check=True,
                             capture_output=True, text=True).stdout
    dynamic = subprocess.run(['readelf', '-d', str(args.output)], check=True,
                             capture_output=True, text=True).stdout
    symbols = subprocess.run(['readelf', '-Ws', str(args.output)], check=True,
                             capture_output=True, text=True).stdout
    if 'Advanced Micro Devices X86-64' not in readelf:
        raise SystemExit('HAL output is not Android x86_64 ELF')
    if ('[libc.so]' not in dynamic or '[liblog.so]' not in dynamic
            or 'audio.primary.aaas.so' not in dynamic):
        raise SystemExit('HAL dynamic dependencies or SONAME are invalid')
    if not re.search(r'\bHMI\b', symbols):
        raise SystemExit('HAL_MODULE_INFO_SYM (HMI) is not exported')
    manifest = {
        'schema_version': 1,
        'source': 'AaaS legacy audio HAL, session-selected through Android HIDL 7.1 adapter',
        'target': 'x86_64-linux-android36',
        'android_header_source': 'AOSP android16-release exported HAL headers',
        'hal_sha256': sha256(args.output),
        'source_sha256': sha256(HAL_SOURCE),
        'protocol_sha256': sha256(PROTOCOL_HEADER),
        'output': str(args.output),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + '.manifest.json')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    obj.unlink(missing_ok=True)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
