#!/usr/bin/env python3
"""Build a temporary Android audioserver factory-selection interposer."""
import argparse
from pathlib import Path
import subprocess

SOURCE = Path(__file__).with_name('factory_probe.cpp')
VERSION_SCRIPT = Path(__file__).with_name('factory_probe.map')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clang', default='clang++')
    args = parser.parse_args()
    rootfs = args.rootfs.resolve(strict=True)
    system = rootfs / 'system/lib64'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    libutils_include = (rootfs.parent / 'sources/core-android16/libutils/include')
    liblog_include = (rootfs.parent / 'sources/logging-android16/liblog/include')
    subprocess.run([
        args.clang, '-target', 'x86_64-linux-android36', '-std=c++17',
        '-Wall', '-Wextra', '-Werror', '-fPIC', '-fno-exceptions', '-fno-rtti',
        '-nostdlib', '-shared', '-I', str(libutils_include),
        '-I', str(liblog_include), str(SOURCE),
        '-L', str(system), '-Wl,-rpath-link,' + str(system),
        '-Wl,--version-script,' + str(VERSION_SCRIPT),
        '-Wl,--no-undefined', '-ldl', '-llog', '-lbinder', '-lutils', '-lc++', '-lc',
        '-o', str(args.output),
    ], check=True)
    header = subprocess.run(['readelf', '-h', str(args.output)], check=True,
                            capture_output=True, text=True).stdout
    symbols = subprocess.run(['readelf', '-Ws', str(args.output)], check=True,
                             capture_output=True, text=True).stdout
    if ('Advanced Micro Devices X86-64' not in header
            or 'DevicesFactoryHalInterface6createEv' not in symbols):
        raise SystemExit('factory probe is not a valid x86_64 interposer')
    print(args.output)


if __name__ == '__main__':
    main()
