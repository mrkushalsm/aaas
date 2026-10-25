#!/usr/bin/env python3
"""Download and verify a public Android SDK system image into the AaaS workspace.

Sources are declared in manifests/android-images.json.  The script verifies
the workspace budget before starting the download, checks the declared SHA1
after completion, and writes a receipt to results/m1b0/.  It does not extract
or mount anything; a separate inspect step does that.

Usage:
    python3 scripts/fetch_android_image.py \
        --workspace /run/media/mrkus/Homework/aaas-workspace \
        --image system-images;android-36;default;x86_64 \
        [--dry-run]
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import android_workspace as ws

MANIFEST = Path(__file__).parent.parent / 'manifests' / 'android-images.json'
IMAGES_SUBDIR = 'images'
RECEIPT_FILENAME = 'fetch-receipt.json'


def load_manifest():
    if not MANIFEST.is_file():
        raise FileNotFoundError(f'image manifest not found: {MANIFEST}')
    return json.loads(MANIFEST.read_text())


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, expected_bytes: int) -> dict:
    """Download url to dest with a progress callback.  Returns timing stats."""
    tmp = dest.with_suffix('.tmp')
    t0 = time.monotonic()
    received = 0
    last_report = t0

    req = urllib.request.Request(url, headers={'User-Agent': 'AaaS/m1b0 fetch_android_image'})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, 'wb') as out:
        while True:
            chunk = resp.read(1 << 17)  # 128 KiB
            if not chunk:
                break
            out.write(chunk)
            received += len(chunk)
            now = time.monotonic()
            if now - last_report >= 5:
                pct = received / expected_bytes * 100 if expected_bytes else 0
                rate = received / (now - t0) / 1024
                print(f'  {received // 1024 // 1024} MiB / {expected_bytes // 1024 // 1024} MiB'
                      f'  ({pct:.1f}%)  {rate:.0f} KiB/s', flush=True)
                last_report = now

    elapsed = time.monotonic() - t0
    tmp.rename(dest)
    return {'bytes': received, 'elapsed_s': round(elapsed, 2),
            'rate_kib_s': round(received / elapsed / 1024, 1)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace', required=True,
                    help='path to the guarded AaaS workspace directory')
    ap.add_argument('--image', required=True,
                    help='SDK image path key, e.g. system-images;android-36;default;x86_64')
    ap.add_argument('--dry-run', action='store_true',
                    help='check budget and print plan without downloading')
    ap.add_argument('--results-dir', default=None,
                    help='directory to write the fetch receipt (default: results/m1b0)')
    args = ap.parse_args()

    manifest = load_manifest()
    images = {img['sdk_path']: img for img in manifest.get('images', [])}
    if args.image not in images:
        print(f'error: image "{args.image}" not in {MANIFEST}', file=sys.stderr)
        print('available:', *images.keys(), sep='\n  ', file=sys.stderr)
        return 2

    img = images[args.image]
    url = img['url']
    size_bytes = img['size_bytes']
    expected_sha1 = img['sha1']

    print(f'image  : {img["sdk_path"]}')
    print(f'url    : {url}')
    print(f'size   : {size_bytes // 1024 // 1024} MiB ({size_bytes} bytes)')
    print(f'sha1   : {expected_sha1}')

    try:
        budget = ws.check(args.workspace, predicted=size_bytes)
    except ws.WorkspaceError as exc:
        print(f'workspace guard: {exc}', file=sys.stderr)
        return 2

    workspace = Path(args.workspace)
    dest = workspace / IMAGES_SUBDIR / Path(url).name
    print(f'dest   : {dest}')

    free_after = (budget['free_bytes'] - size_bytes) // 1024 // 1024
    print(f'budget : used={budget["used_bytes"] // 1024 // 1024} MiB'
          f'  ceiling={budget["ceiling_bytes"] // 1024 // 1024} MiB'
          f'  free_after_download≈{free_after} MiB')

    if args.dry_run:
        print('dry-run: no download performed')
        return 0

    if dest.exists():
        actual = sha1_file(dest)
        if actual == expected_sha1:
            print(f'already present and verified: {dest}')
            return 0
        print(f'existing file has wrong SHA1 ({actual}); re-downloading', file=sys.stderr)
        dest.unlink()

    print('downloading...')
    try:
        stats = download(url, dest, size_bytes)
    except Exception as exc:
        print(f'download failed: {exc}', file=sys.stderr)
        partial = dest.with_suffix('.tmp')
        if partial.exists():
            partial.unlink()
        return 2

    print(f'verifying SHA1...')
    actual_sha1 = sha1_file(dest)
    if actual_sha1 != expected_sha1:
        print(f'SHA1 mismatch: expected {expected_sha1}, got {actual_sha1}', file=sys.stderr)
        dest.unlink()
        return 2

    print(f'SHA1 verified: {actual_sha1}')

    receipt = {
        'sdk_path': img['sdk_path'],
        'url': url,
        'dest': str(dest),
        'size_bytes': stats['bytes'],
        'sha1': actual_sha1,
        'elapsed_s': stats['elapsed_s'],
        'rate_kib_s': stats['rate_kib_s'],
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }

    results_dir = Path(args.results_dir) if args.results_dir else \
        Path(__file__).parent.parent / 'results' / 'm1b0'
    results_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = results_dir / RECEIPT_FILENAME
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'receipt: {receipt_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
