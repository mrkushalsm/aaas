#!/usr/bin/env python3
"""Inspect the contents of a downloaded Android SDK system image zip.

Reads the zip central directory to enumerate files and sizes, parses LP dynamic
partition metadata from system.img/super.img, and uses guestfish to inspect
HAL binaries, VINTF manifests, and init configurations from vendor.img.
Produces a structured JSON report of Composer3, Gralloc, and Binder artifacts.
No root, no loopback mount, no host changes.

Usage:
    python3 scripts/inspect_android_image.py \
        --image /path/to/aaas-workspace/images/x86_64-36_r02.zip \
        --results results/m1b0/image-contents.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# Ensure read_lp_metadata is importable
sys.path.insert(0, str(Path(__file__).parent))
import read_lp_metadata as lp


VENDOR_HAL_PATHS = [
    '/bin/hw',
    '/etc/vintf',
    '/etc/vintf/manifest',
    '/etc/init',
    '/lib64',
    '/lib64/hw',
]

KEY_VINTF_FRAGMENTS = [
    'hwc3.xml',
    'android.hardware.graphics.gralloc.ranchu.xml',
]

KEY_INIT_SCRIPTS = [
    'hwc3.rc',
    'android.hardware.graphics.allocator-service.ranchu.rc',
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
    """Extract a single .img file from the zip to dest_dir.

    Strips any directory prefix in the zip member name so the output is always
    dest_dir/<basename>. Skips extraction if the destination already exists.
    """
    basename = Path(img_name).name
    dest = dest_dir / basename
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


def guestfish_run_commands(img_path: Path, mount_dev: str, commands: list) -> dict:
    """Run guestfish commands on an image partition mounted read-only."""
    if shutil.which('guestfish') is None:
        return {'error': 'guestfish not available'}

    script_lines = ['run', f'mount-ro {mount_dev} /']
    for cmd in commands:
        script_lines.append(cmd)

    input_script = '\n'.join(script_lines) + '\n'
    result = subprocess.run(
        ['guestfish', '--ro', '-a', str(img_path)],
        input=input_script,
        capture_output=True,
        text=True,
        timeout=60
    )
    if result.returncode != 0:
        return {'error': result.stderr.strip(), 'stdout': result.stdout.strip()}
    return {'output': result.stdout.strip()}


def guestfish_ls(img_path: Path, mount_dev: str, path: str) -> list:
    """List directory contents using guestfish (read-only, no root)."""
    res = guestfish_run_commands(img_path, mount_dev, [f'ls {path}'])
    if 'error' in res:
        return {'error': res['error']}
    return [line for line in res.get('output', '').splitlines() if line]


def guestfish_cat(img_path: Path, mount_dev: str, file_path: str) -> str:
    """Read a text file from the image."""
    res = guestfish_run_commands(img_path, mount_dev, [f'cat {file_path}'])
    if 'error' in res:
        return None
    return res.get('output', '')


def inspect_vendor_partition(vendor_img_path: Path) -> dict:
    """Inspect vendor.img filesystem (GPT partition /dev/sda1)."""
    report = {'vendor_img': str(vendor_img_path), 'hal_paths': {}, 'vintf': {}, 'init': {}}
    mount_dev = '/dev/sda1'

    for p in VENDOR_HAL_PATHS:
        listing = guestfish_ls(vendor_img_path, mount_dev, p)
        report['hal_paths'][p] = listing

    for frag in KEY_VINTF_FRAGMENTS:
        content = guestfish_cat(vendor_img_path, mount_dev, f'/etc/vintf/manifest/{frag}')
        if content:
            report['vintf'][frag] = content

    for init_rc in KEY_INIT_SCRIPTS:
        content = guestfish_cat(vendor_img_path, mount_dev, f'/etc/init/{init_rc}')
        if content:
            report['init'][init_rc] = content

    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image', required=True,
                    help='path to the downloaded .zip image file')
    ap.add_argument('--results', default='results/m1b0/image-contents.json',
                    help='output JSON report path')
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

    for m in zip_contents['members']:
        mib = m['file_size'] / 1024 / 1024
        print(f'  {m["name"]:40s}  {mib:8.1f} MiB')

    report = {
        'zip_path': str(zip_path),
        'zip_contents': zip_contents,
        'super_metadata': None,
        'vendor_inspection': None,
    }

    img_members = [m['name'] for m in zip_contents['members'] if m['name'].endswith('.img')]

    # 1. Parse super / system.img LP dynamic partition metadata
    system_img_name = next((m for m in img_members if 'system' in m), None)
    if system_img_name:
        print(f'\nextracting {system_img_name} for LP metadata inspection...')
        sys_path = extract_img_to_temp(zip_path, system_img_name, extract_dir)
        print('reading LP dynamic partition metadata...')
        lp_meta = lp.read_lp_metadata(sys_path)
        report['super_metadata'] = lp_meta
        if lp_meta.get('is_super'):
            print(f'  super partitions found: {len(lp_meta["partitions"])}')
            for p in lp_meta['partitions']:
                print(f'    {p["name"]:20s} {p.get("fs_type",""):8s} {p["total_size_mib"]:8.1f} MiB')

    # 2. Extract and inspect vendor.img for Composer3 and Gralloc HALs
    vendor_img_name = next((m for m in img_members if 'vendor' in m), None)
    if vendor_img_name:
        print(f'\nextracting {vendor_img_name} for HAL inspection...')
        vendor_path = extract_img_to_temp(zip_path, vendor_img_name, extract_dir)
        print('inspecting vendor partition (/dev/sda1) with guestfish...')
        report['vendor_inspection'] = inspect_vendor_partition(vendor_path)
        hw_binaries = report['vendor_inspection'].get('hal_paths', {}).get('/bin/hw', [])
        if isinstance(hw_binaries, list):
            print(f'  vendor /bin/hw contains {len(hw_binaries)} HAL binaries:')
            for b in hw_binaries:
                if 'composer' in b or 'allocator' in b or 'drm' in b:
                    print(f'    -> {b}')

    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(report, indent=2) + '\n')
    print(f'\ninspection report written: {results_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
