#!/usr/bin/env python3
"""Extract raw filesystem partitions from an Android super.img.

Uses LP metadata to extract individual ext4/erofs raw partition images
from Android dynamic partition container without root privileges.
"""

import argparse
import json
import sys
from pathlib import Path
from read_lp_metadata import read_lp_metadata


def extract_partitions(image_path: Path, out_dir: Path, partitions_to_extract: list = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = read_lp_metadata(image_path)
    if metadata.get('error') or not metadata.get('is_super'):
        raise RuntimeError(f"Failed to read LP metadata: {metadata.get('error')}")

    base_offset = metadata.get('base_offset', 0)
    results = {}

    with open(image_path, 'rb') as src:
        for part in metadata['partitions']:
            name = part['name']
            if partitions_to_extract and name not in partitions_to_extract:
                continue

            fs_type = part.get('fs_type', 'unknown')
            out_file = out_dir / f"{name}.raw.img"
            print(f"Extracting '{name}' ({part['total_size_mib']:.1f} MiB, {fs_type}) -> {out_file.name} ...")

            with open(out_file, 'wb') as dst:
                for ext in part['extents']:
                    target_type = ext['target_type']
                    size = ext['size_bytes']
                    if target_type == 0:  # LINEAR
                        ext_offset = base_offset + ext['offset_bytes']
                        src.seek(ext_offset)
                        bytes_left = size
                        buf_size = 1024 * 1024  # 1 MiB chunk
                        while bytes_left > 0:
                            chunk = src.read(min(bytes_left, buf_size))
                            if not chunk:
                                raise EOFError(f"Unexpected EOF while reading partition {name}")
                            dst.write(chunk)
                            bytes_left -= len(chunk)
                    elif target_type == 1:  # ZERO
                        dst.write(b'\x00' * size)
                    else:
                        raise ValueError(f"Unknown target type: {target_type}")

            results[name] = {
                'path': str(out_file),
                'size_bytes': part['total_size_bytes'],
                'size_mib': part['total_size_mib'],
                'fs_type': fs_type,
            }

    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image', required=True, help='Path to super.img')
    ap.add_argument('--out-dir', required=True, help='Output directory for extracted images')
    ap.add_argument('--partitions', nargs='*', help='Specific partitions to extract (default: all)')
    args = ap.parse_args()

    image_path = Path(args.image)
    out_dir = Path(args.out_dir)

    extracted = extract_partitions(image_path, out_dir, args.partitions)
    print("\nExtraction summary:")
    for name, info in extracted.items():
        print(f"  - {name}: {info['size_mib']:.1f} MiB ({info['fs_type']}) at {info['path']}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
