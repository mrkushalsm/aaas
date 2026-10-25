#!/usr/bin/env python3
"""Inspect the contents of a downloaded Android SDK system image zip.

Reads the zip central directory to enumerate files and sizes, then uses
guestfish (read-only, no mount) to list filesystem contents of system.img.
Produces a JSON report of what HAL-relevant binaries and AIDL service
descriptors are present.  No root, no loopback mount, no host changes.

Usage:
    python3 scripts/inspect_android_image.py \
        --image /path/to/aaas-workspace/images/x86_64-36_r02.zip \
        --results results/m1b0/image-contents.json \
        [--deep]         # also list /system/lib64/hw/ and AIDL descriptors
"""

import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


# Paths inside the system.img filesystem that are relevant to Composer3/HAL
HAL_PATHS = [
    '/system/lib64/hw',
    '/system/etc/vintf',
    '/system/lib64/android.hardware.composer',
    '/vendor/lib64/hw',
    '/vendor/etc/vintf',
    '/system/bin/surfaceflinger',
    '/system/bin/hwservicemanager',
    '/system/bin/servicemanager',
]

AIDL_PATTERNS = [
    'android.hardware.graphics.composer',
    'android.hardware.graphics.allocator',
    'android.hardware.graphics.common',
    'surfaceflinger',
    'hwcomposer',
]


def list_zip_contents(zip_path: Path) -> dict:
    """Return summary of zip members."""
    result = {'members': [], 'total_compressed_bytes': 0, 'total_uncompressed_bytes': 0}
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            result['members'].append({
                'name': info.filename,
                'compress_size': info.compress_size,
                'file_size': info.file_size,
                'compress_type': info.compress_type,
            })
            result['total_compressed_bytes'] += info.compress_size
            result['total_uncompressed_bytes'] += info.file_size
    result['member_count'] = len(result['members'])
    return result


def extract_img_to_temp(zip_path: Path, img_name: str, dest_dir: Path) -> Path:
    """Extract a single .img file from the zip to dest_dir."""
    dest = dest_dir / img_name
    if dest.exists():
        return dest
    print(f'  extracting {img_name} from zip...', flush=True)
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(img_name) as src, open(dest, 'wb') as out:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
    return dest


def guestfish_ls(img_path: Path, path: str) -> list:
    """List directory contents using guestfish (read-only, no mount)."""
    result = subprocess.run(
        ['guestfish', '--ro', '-a', str(img_path), '-m', '/dev/sda', 'ls', path],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        return {'error': result.stderr.strip()}
    return result.stdout.strip().splitlines()


def guestfish_find(img_path: Path, pattern_contains: str) -> list:
    """Find files matching a pattern using guestfish find."""
    result = subprocess.run(
        ['guestfish', '--ro', '-a', str(img_path), '-m', '/dev/sda',
         'find', '/'],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        return []
    return [l for l in result.stdout.splitlines() if pattern_contains.lower() in l.lower()]


def inspect_filesystem(img_path: Path, deep: bool) -> dict:
    """Use guestfish to inspect the filesystem contents."""
    report = {'img_path': str(img_path), 'hal_paths': {}, 'aidl_matches': {}}

    # Check if guestfish is available
    if subprocess.run(['which', 'guestfish'], capture_output=True).returncode != 0:
        report['error'] = 'guestfish not available; install libguestfs-tools'
        return report

    for path in HAL_PATHS:
        listing = guestfish_ls(img_path, path)
        report['hal_paths'][path] = listing

    if deep:
        for pattern in AIDL_PATTERNS:
            matches = guestfish_find(img_path, pattern)
            report['aidl_matches'][pattern] = matches

    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image', required=True,
                    help='path to the downloaded .zip image file')
    ap.add_argument('--results', default='results/m1b0/image-contents.json',
                    help='output JSON report path')
    ap.add_argument('--deep', action='store_true',
                    help='run guestfish find for AIDL descriptor paths (slow)')
    ap.add_argument('--extract-dir', default=None,
                    help='directory to extract .img files into (default: next to zip)')
    args = ap.parse_args()

    zip_path = Path(args.image).resolve()
    if not zip_path.is_file():
        print(f'error: image not found: {zip_path}', file=sys.stderr)
        return 2

    extract_dir = Path(args.extract_dir) if args.extract_dir \
        else zip_path.parent / (zip_path.stem + '-extracted')
    extract_dir.mkdir(parents=True, exist_ok=True)

    print(f'inspecting zip: {zip_path}')
    zip_contents = list_zip_contents(zip_path)
    print(f'  {zip_contents["member_count"]} members, '
          f'{zip_contents["total_uncompressed_bytes"] // 1024 // 1024} MiB uncompressed')

    # Print member listing
    for m in zip_contents['members']:
        mib = m['file_size'] / 1024 / 1024
        print(f'  {m["name"]:40s}  {mib:8.1f} MiB')

    report = {
        'zip_path': str(zip_path),
        'zip_contents': zip_contents,
        'filesystem': None,
    }

    # Find system.img among members
    img_members = [m['name'] for m in zip_contents['members'] if m['name'].endswith('.img')]
    system_img_name = next((m for m in img_members if 'system' in m), None)

    if system_img_name:
        print(f'\nextracting {system_img_name} for filesystem inspection...')
        img_path = extract_img_to_temp(zip_path, system_img_name, extract_dir)
        print(f'inspecting filesystem with guestfish...')
        report['filesystem'] = inspect_filesystem(img_path, args.deep)
    else:
        print('no system.img found in zip members')
        report['filesystem'] = {'error': 'no system.img in zip'}

    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(report, indent=2) + '\n')
    print(f'\nreport written: {results_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
