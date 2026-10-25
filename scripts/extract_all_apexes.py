#!/usr/bin/env python3
"""Extract all Android APEX/CAPEX packages into target rootfs /apex directory.

Handles both uncompressed .apex and compressed .capex packages, extracting
the internal ext4/erofs apex_payload.img using 7z.
"""

import argparse
import io
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def extract_single_apex(apex_path: Path, target_dir: Path):
    pkg_name = apex_path.name
    for ext in ('.capex', '.apex'):
        if pkg_name.endswith(ext):
            pkg_name = pkg_name[:-len(ext)]
            break

    dest = target_dir / pkg_name
    dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(apex_path, 'r') as zf:
        # Check if CAPEX (contains original_apex)
        if 'original_apex' in zf.namelist():
            inner_bytes = zf.read('original_apex')
            inner_zf = zipfile.ZipFile(io.BytesIO(inner_bytes))
        else:
            inner_zf = zf

        if 'apex_payload.img' not in inner_zf.namelist():
            print(f"Skipping {apex_path.name}: no apex_payload.img found")
            return

        with tempfile.NamedTemporaryFile(suffix='.img', delete=False) as tmp_img:
            tmp_img_path = Path(tmp_img.name)
            tmp_img.write(inner_zf.read('apex_payload.img'))

    try:
        # Extract using 7z
        subprocess.run(
            ['7z', 'x', '-y', f'-o{dest}', str(tmp_img_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True
        )
        print(f"Extracted: {pkg_name} -> {dest}")
    finally:
        if tmp_img_path.exists():
            tmp_img_path.unlink()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apex-dir', required=True, help='Directory containing .apex/.capex files')
    ap.add_argument('--target-apex', required=True, help='Target /apex mount root directory')
    args = ap.parse_args()

    apex_dir = Path(args.apex_dir)
    target_apex = Path(args.target_apex)
    target_apex.mkdir(parents=True, exist_ok=True)

    files = sorted(list(apex_dir.glob('*.apex')) + list(apex_dir.glob('*.capex')))
    print(f"Found {len(files)} APEX packages in {apex_dir}")

    for f in files:
        extract_single_apex(f, target_apex)

    # Also symlink com.android.runtime to /apex/com.android.runtime@* if expected
    print("\nAll APEX packages successfully processed.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
