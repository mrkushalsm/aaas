#!/usr/bin/env python3
"""Build the ordinary, short-lived Android service used for MediaStore scans."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from experiments.perf.input_latency_probe.build_probe import binary_manifest

PACKAGE = 'org.aaas.storagescan'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            digest.update(path.relative_to(Path(__file__).parent).as_posix().encode())
            digest.update(path.read_bytes())
    digest.update(Path(ROOT / 'experiments/perf/input_latency_probe/build_probe.py').read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apktool', type=Path, required=True)
    parser.add_argument('--apksig', type=Path, required=True)
    parser.add_argument('--keystore', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for item in (args.apktool, args.apksig, args.keystore):
        if not item.is_file():
            parser.error(f'missing pinned build input: {item}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = Path(str(args.output) + '.json')
    expected = {
        'package': PACKAGE,
        'source_sha256': source_hash(),
        'apktool_sha256': sha256(args.apktool),
        'apksig_sha256': sha256(args.apksig),
        'keystore_sha256': sha256(args.keystore),
    }
    if args.output.is_file() and receipt.is_file():
        try:
            prior = json.loads(receipt.read_text())
        except (OSError, json.JSONDecodeError):
            prior = None
        if prior and all(prior.get(k) == v for k, v in expected.items()) and \
                prior.get('apk_sha256') == sha256(args.output):
            print(json.dumps(prior, sort_keys=True))
            return 0

    source = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='aaas-storage-scan-apk-') as temp:
        work = Path(temp)
        shutil.copytree(source / 'smali', work / 'smali')
        (work / 'AndroidManifest.xml').write_bytes(binary_manifest(
            PACKAGE, target_sdk=35,
            receivers=(('.ScanReceiver', 'android.permission.DUMP'),),
            include_launcher=False,
        ))
        (work / 'apktool.yml').write_text(
            'version: 3.0.3\napkFileName: AaasStorageScan.apk\n'
            'sdkInfo:\n  minSdkVersion: 28\n  targetSdkVersion: 35\n'
            'versionInfo:\n  versionCode: 1\n  versionName: 1.0\n')
        subprocess.run(['java', '-jar', str(args.apktool), 'b', '--no-apk', str(work)],
                       check=True)
        dex = work / 'build/apk/classes.dex'
        if not dex.is_file():
            raise RuntimeError('apktool did not emit classes.dex')
        unsigned = work / 'unsigned.apk'
        with zipfile.ZipFile(unsigned, 'w') as apk:
            apk.write(work / 'AndroidManifest.xml', 'AndroidManifest.xml')
            apk.write(dex, 'classes.dex')
        signer = source.parent / 'shared_storage_probe' / 'ApkSign.java'
        subprocess.run(['javac', '-cp', str(args.apksig), '-d', str(work), str(signer)],
                       check=True)
        built = work / 'signed.apk'
        subprocess.run(['java', '-cp', f'{work}:{args.apksig}', 'ApkSign',
                        str(args.keystore), 'android', 'storage-probe',
                        str(unsigned), str(built)], check=True)
        temporary_output = args.output.with_suffix('.apk.tmp')
        shutil.copy2(built, temporary_output)
        temporary_output.replace(args.output)
    result = {**expected, 'apk_sha256': sha256(args.output)}
    temporary_receipt = receipt.with_suffix('.json.tmp')
    temporary_receipt.write_text(json.dumps(result, indent=2) + '\n')
    temporary_receipt.replace(receipt)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
