#!/usr/bin/env python3
"""Build the Android 16 HIDL factory-selection compatibility interposer."""
import argparse
from pathlib import Path
import subprocess

SOURCE = Path(__file__).with_name('factory_compat.cpp')
VERSION_SCRIPT = Path(__file__).with_name('factory_compat.map')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clang', default='clang++')
    args = parser.parse_args()
    rootfs = args.rootfs.resolve(strict=True)
    system = rootfs / 'system/lib64'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        args.clang, '-target', 'x86_64-linux-android36', '-std=c++17',
        '-Wall', '-Wextra', '-Werror', '-fPIC', '-fno-exceptions', '-fno-rtti',
        '-nostdlib', '-shared', str(SOURCE), '-L', str(system),
        '-Wl,-rpath-link,' + str(system),
        '-Wl,--version-script,' + str(VERSION_SCRIPT),
        '-Wl,--no-undefined', '-ldl', '-lbinder', '-lutils', '-lc++', '-lc',
        '-o', str(args.output),
    ], check=True)
    header = subprocess.run(['readelf', '-h', str(args.output)], check=True,
                            capture_output=True, text=True).stdout
    symbols = subprocess.run(['readelf', '-Ws', str(args.output)], check=True,
                             capture_output=True, text=True).stdout
    required = ('DevicesFactoryHalInterface6createEv',
                'EffectsFactoryHalInterface6createEv')
    if 'Advanced Micro Devices X86-64' not in header or any(
            symbol not in symbols for symbol in required):
        raise SystemExit('invalid Android x86_64 audio factory compatibility library')
    print(args.output)


if __name__ == '__main__':
    main()
