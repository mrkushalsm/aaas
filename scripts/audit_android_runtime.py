#!/usr/bin/env python3
"""Compare selected Android runtime files with immutable extracted partitions.

This is a preflight gate, not a boot test. It reports modifications without
changing the rootfs or attempting to repair it.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


CRITICAL = (
    'system/bin/apexd',
    'system/bin/servicemanager',
    'system/bin/surfaceflinger',
    'system/bin/vdc',
    'system/bin/vold',
    'system/lib64/libandroid_runtime.so',
    'system/lib64/libbinder.so',
    'system/lib64/libhidlbase.so',
    'system_ext/bin/hwservicemanager',
    'system/etc/init/apexd.rc',
    'system/etc/init/hw/init.rc',
    'system/etc/init/netbpfload.rc',
    'system/etc/init/vold.rc',
    'vendor/etc/init/hw/init.ranchu.rc',
    'vendor/etc/init/hwc3.rc',
    'vendor/etc/init/android.hardware.graphics.allocator-service.ranchu.rc',
    'vendor/etc/init/lights-default.rc',
)
FORBIDDEN_OVERLAYS = (
    'system/lib64/libselinux_shim.so',
    'vendor/lib64/libselinux_shim.so',
    'system/bin/surfaceflinger_minimal',
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def original_bytes(partition_image, relative_path):
    result = subprocess.run(
        ['debugfs', '-R', f'cat /{relative_path}', str(partition_image)],
        capture_output=True, check=False,
    )
    if result.returncode or b'not found' in result.stderr.lower():
        raise RuntimeError(f'debugfs could not read {relative_path}: '
                           f'{result.stderr.decode(errors="replace").strip()}')
    return result.stdout


def audit(rootfs, partitions, paths=CRITICAL):
    findings = []
    for path in paths:
        part = path.split('/', 1)[0]
        image = partitions / f'{part}.raw.img'
        target = rootfs / path
        if not image.is_file():
            findings.append(dict(path=path, status='missing_partition', image=str(image)))
            continue
        try:
            # This SDK's system image includes /system alongside root
            # symlinks; vendor and system_ext images are mountpoint roots.
            image_path = path if part == 'system' else path.split('/', 1)[1]
            original = original_bytes(image, image_path)
            current = target.read_bytes()
        except (RuntimeError, OSError) as exc:
            findings.append(dict(path=path, status='unreadable', reason=str(exc)))
            continue
        findings.append(dict(path=path,
                             status='identical' if current == original else 'modified',
                             original_sha256=sha256(original), current_sha256=sha256(current),
                             original_bytes=len(original), current_bytes=len(current)))
    return findings


def audit_overlays(rootfs, paths=FORBIDDEN_OVERLAYS):
    return [dict(path=path, status='unexpected_overlay')
            for path in paths if (rootfs / path).exists()]


def audit_source_checkout(path):
    if not path:
        return []
    result = subprocess.run(['git', '-C', str(path), 'status', '--porcelain'],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        return [dict(path=str(path), status='source_unreadable',
                     reason=result.stderr.strip())]
    if result.stdout.strip():
        return [dict(path=str(path), status='source_modified',
                     modified_entries=len(result.stdout.splitlines()))]
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', required=True, type=Path)
    parser.add_argument('--partitions', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--swiftshader-source', type=Path,
                        help='optional SwiftShader checkout to reject local source patches')
    args = parser.parse_args()
    findings = (audit(args.rootfs, args.partitions) +
                audit_overlays(args.rootfs) +
                audit_source_checkout(args.swiftshader_source))
    report = {'schema': 1, 'rootfs': str(args.rootfs),
              'partitions': str(args.partitions), 'findings': findings}
    encoded = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end='')
    return 0 if all(item['status'] == 'identical' for item in findings) else 1


if __name__ == '__main__':
    sys.exit(main())
