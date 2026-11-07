#!/usr/bin/env python3
"""Build an Android x86_64 legacy audio module lookup probe."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).with_name('hal_probe.c')
INCLUDES = Path(__file__).with_name('android-headers')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clang', default='clang')
    args = parser.parse_args()
    rootfs = args.rootfs.resolve(strict=True)
    vendor = rootfs / 'vendor/lib64'
    system = rootfs / 'system/lib64'
    log_include = rootfs.parent / 'sources/logging-android16/liblog/include'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        args.clang, '-target', 'x86_64-linux-android36', '-std=gnu11',
        '-Wall', '-Wextra', '-Werror', '-I', str(INCLUDES),
        '-I', str(log_include), '-fPIC',
        '-nostdlib', '-shared', str(SOURCE), '-L', str(vendor), '-L', str(system),
        '-Wl,-rpath-link,' + str(vendor), '-Wl,-rpath-link,' + str(system),
        '-Wl,--no-undefined', '-lhardware', '-llog', '-ldl', '-lc',
        '-o', str(args.output),
    ], check=True)
    header = subprocess.run(['readelf', '-h', str(args.output)], check=True,
                            capture_output=True, text=True).stdout
    if 'Advanced Micro Devices X86-64' not in header:
        raise SystemExit('probe is not an Android x86_64 ELF')
    print(args.output)


if __name__ == '__main__':
    main()
