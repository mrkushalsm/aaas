#!/usr/bin/env python3
"""Reproducible build script for Android 16 LMKD from pinned sources."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = Path('/run/media/mrkus/Aaas/aaas-workspace')
SOURCES = WORKSPACE / 'sources'
ROOTFS = WORKSPACE / 'rootfs_m1b1'
TMP = WORKSPACE / 'tmp'
SOURCE_MANIFEST = ROOT / 'results/m1b85/source_manifest.json'
LMKD_PATCH = ROOT / 'patches/m1b83/lmkd-absent-memevents-fallback.patch'
LMKD_PATCH_DISPLAY = str(LMKD_PATCH.relative_to(ROOT))
ALLOWED_PATCHES = {
    'lmkd-android16': [LMKD_PATCH],
    'libmeminfo-android16': [ROOT / 'patches/m1b81/libmeminfo-unavailable-gpu-map.patch'],
    'connectivity-android16': [
        ROOT / 'patches/m1b81/connectivity-networkstats-unavailable-map.patch'],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(source: Path, *arguments: str) -> str:
    return subprocess.check_output(['git', '-C', str(source), *arguments],
                                   text=True).strip()


def git_raw(source: Path, *arguments: str) -> str:
    return subprocess.check_output(['git', '-C', str(source), *arguments],
                                   text=True)


def verify_sources():
    """Validate pinned commits and the exact applied source patches."""
    manifest = json.loads(SOURCE_MANIFEST.read_text())
    entries = {}
    errors = []
    for name, record in sorted(manifest['sources'].items()):
        source = Path(record['path'])
        actual_commit = git(source, 'rev-parse', 'HEAD')
        modified = git(source, 'diff', 'HEAD', '--name-only').splitlines()
        untracked = git(source, 'ls-files', '--others', '--exclude-standard').splitlines()
        if actual_commit != record['commit']:
            errors.append(f'{name}: HEAD {actual_commit} != pinned {record["commit"]}')
        patches = ALLOWED_PATCHES.get(name, [])
        expected_files = []
        for patch in patches:
            for line in patch.read_text().splitlines():
                if line.startswith('diff --git a/'):
                    expected_files.append(line.split(' b/', 1)[1])
        actual_diff = git_raw(source, 'diff', 'HEAD')
        expected_diff = ''.join(patch.read_text() for patch in patches)
        patch_matches = actual_diff == expected_diff
        if modified != expected_files:
            errors.append(f'{name}: modified files {modified} != expected {expected_files}')
        if untracked:
            errors.append(f'{name}: unexpected untracked files: {untracked}')
        if patches:
            if not patch_matches:
                errors.append(f'{name}: working tree does not match pinned patches')
        elif actual_diff:
            errors.append(f'{name}: unexpected source modifications')
        entry = {
            'path': record['path'],
            'expected_commit': record['commit'],
            'actual_commit': actual_commit,
            'commit_matches': actual_commit == record['commit'],
            'modified_files': modified,
            'patch_matches': patch_matches if patches else not modified,
        }
        if patches:
            entry['patches'] = [
                {'path': str(patch.relative_to(ROOT)) if patch.is_relative_to(ROOT)
                 else str(patch),
                 'sha256': sha256(patch)}
                for patch in patches
            ]
        entries[name] = entry
    if errors:
        raise RuntimeError('source provenance verification failed:\n' + '\n'.join(errors))
    return entries
def build_lmkd(output_path: Path) -> str:
    clang_res = subprocess.check_output(['clang++', '-print-resource-dir'], text=True).strip()
    clang_inc = Path(clang_res) / 'include'

    bionic_src = SOURCES / 'bionic-android16'
    lmkd_src = SOURCES / 'lmkd-android16'
    libbase_src = SOURCES / 'libbase-android16'
    core_src = SOURCES / 'core-android16'
    logging_src = SOURCES / 'logging-android16'
    meminfo_src = SOURCES / 'libmeminfo-android16'
    conn_src = SOURCES / 'connectivity-android16'
    libcxx_inc = WORKSPACE / 'toolchain/libc++/usr/include/c++/v1'

    build_dir = TMP / 'lmkd_build'
    build_dir.mkdir(parents=True, exist_ok=True)

    crtbegin_o = build_dir / 'crtbegin.o'
    crtend_o = build_dir / 'crtend.o'

    # 1. Compile crtbegin and crtend
    subprocess.run([
        'clang', '-target', 'x86_64-linux-android', '-c',
        '-nostdinc', '-D__BIONIC__', '-D__ANDROID_API__=35',
        f'-isystem{clang_inc}',
        f'-isystem{bionic_src}/libc/include',
        f'-isystem{bionic_src}/libc/kernel/android/uapi',
        f'-isystem{bionic_src}/libc/kernel/uapi',
        f'-isystem{bionic_src}/libc/kernel/uapi/asm-x86',
        f'-I{bionic_src}/libc',
        str(bionic_src / 'libc/arch-common/bionic/crtbegin.c'),
        '-o', str(crtbegin_o)
    ], check=True)

    subprocess.run([
        'clang', '-target', 'x86_64-linux-android', '-c',
        f'-I{bionic_src}/libc/arch-common/bionic',
        str(bionic_src / 'libc/arch-common/bionic/crtend.S'),
        '-o', str(crtend_o)
    ], check=True)

    # 2. Compile C++ sources
    cpp_flags = [
        'clang++', '-target', 'x86_64-linux-android', '-std=c++20', '-c',
        '-nostdinc', '-fPIC',
        '-D__BIONIC__', '-D_GNU_SOURCE', '-D__ANDROID_API__=35', '-D__ANDROID_MIN_SDK_VERSION__=36',
        '-D__BIONIC_AVAILABILITY_GUARD(api_level)=1',
        '-D__INTRODUCED_IN(n)=',
        '-DLMKD_TRACE_KILLS', '-DLMKD_LOG_STATS', '-DAAAS_CONTAINER_RUNTIME',
        f'-isystem{libcxx_inc}',
        f'-isystem{clang_inc}',
        f'-isystem{bionic_src}/libc/include',
        f'-isystem{bionic_src}/libc/kernel/android/uapi',
        f'-isystem{bionic_src}/libc/kernel/uapi',
        f'-isystem{bionic_src}/libc/kernel/uapi/asm-x86',
        f'-I{lmkd_src}/include',
        f'-I{lmkd_src}',
        f'-I{lmkd_src}/libpsi/include',
        f'-I{libbase_src}/include',
        f'-I{core_src}/libcutils/include',
        f'-I{core_src}/libprocessgroup/include',
        f'-I{core_src}/libsystem/include',
        f'-I{logging_src}/liblog/include',
        f'-I{meminfo_src}/libmemevents/include',
        f'-I{conn_src}/bpf/headers/include',
        f'-I{conn_src}/bpf/syscall_wrappers/include',
    ]

    objects = []
    sources = [
        lmkd_src / 'lmkd.cpp',
        lmkd_src / 'reaper.cpp',
        lmkd_src / 'watchdog.cpp',
        lmkd_src / 'statslog.cpp',
        lmkd_src / 'liblmkd_utils.cpp',
        lmkd_src / 'libpsi/psi.cpp',
    ]

    for src in sources:
        obj = build_dir / f'{src.stem}.o'
        subprocess.run(cpp_flags + [str(src), '-o', str(obj)], check=True)
        objects.append(obj)

    # 3. Link executable
    link_cmd = [
        'clang++', '-target', 'x86_64-linux-android',
        '-nostdlib', '-pie',
        str(crtbegin_o),
    ] + [str(o) for o in objects] + [
        str(crtend_o),
        f'-L{ROOTFS}/system/lib64',
        f'-L{ROOTFS}/system/lib64/bootstrap',
        '-lbase', '-lcutils', '-llog', '-lmemevents', '-lprocessgroup', '-lpsi',
        '-lc++', '-lc', '-lm', '-ldl',
        '-Wl,-dynamic-linker,/system/bin/linker64',
        '-Wl,-rpath,/system/lib64',
        '-o', str(output_path)
    ]
    subprocess.run(link_cmd, check=True)
    output_path.chmod(0o755)

    digest = sha256(output_path)
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=TMP / 'm1b85_lmkd_source_built')
    parser.add_argument('--receipt', type=Path,
                        help='write a machine-readable build receipt to this path')
    parser.add_argument('--allow-source-drift', action='store_true',
                        help='build even if pinned commits or the LMKD patch do not match')
    args = parser.parse_args()

    sources = None
    if args.allow_source_drift:
        print('WARNING: source provenance verification skipped', file=sys.stderr)
    else:
        sources = verify_sources()
        print('Source provenance verified')

    digest = build_lmkd(args.output)
    print(f'Built LMKD: {args.output}')
    print(f'SHA256: {digest}')

    if args.receipt:
        receipt = {
            'schema': 1,
            'timestamp_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'output': str(args.output),
            'sha256': digest,
            'size_bytes': args.output.stat().st_size,
            'compiler': subprocess.check_output(
                ['clang++', '--version'], text=True).splitlines()[0],
            'build_defines': ['LMKD_TRACE_KILLS', 'LMKD_LOG_STATS',
                              'AAAS_CONTAINER_RUNTIME'],
            'patch': {
                'path': LMKD_PATCH_DISPLAY,
                'sha256': sha256(LMKD_PATCH),
            },
            'sources': sources,
            'source_verification': 'skipped' if sources is None else 'passed',
        }
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        print(f'Receipt: {args.receipt}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
