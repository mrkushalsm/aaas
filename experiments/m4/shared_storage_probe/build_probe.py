#!/usr/bin/env python3
"""Build a small ordinary APK for SAF shared-storage read/write checks."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from experiments.perf.input_latency_probe.build_probe import binary_manifest

PACKAGE = 'org.aaas.storagetest'
PERMISSIONS = ()


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apktool', type=Path, required=True)
    parser.add_argument('--keystore', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--operation', choices=('create', 'open'), default='create')
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aaas-storage-apk-') as temp:
        work = Path(temp)
        smali_source = source / ('smali-open' if args.operation == 'open' else 'smali')
        shutil.copytree(smali_source, work / 'smali')
        for smali_file in (work / 'smali').rglob('*.smali'):
            text = smali_file.read_text()
            text = text.replace('org.aaas.latencyprobe', PACKAGE)
            text = text.replace('org/aaas/latencyprobe', PACKAGE.replace('.', '/'))
            smali_file.write_text(text)
        (work / 'AndroidManifest.xml').write_bytes(binary_manifest(
            PACKAGE, target_sdk=28, requested_permissions=PERMISSIONS))
        (work / 'apktool.yml').write_text(
            'version: 3.0.3\napkFileName: AaasStorageProbe.apk\n'
            'sdkInfo:\n  minSdkVersion: 28\n  targetSdkVersion: 28\n'
            'versionInfo:\n  versionCode: 1\n  versionName: 1.0\n')
        run(['java', '-jar', str(args.apktool), 'b', '--no-apk', str(work)])
        dex = work / 'build/apk/classes.dex'
        if not dex.is_file():
            raise RuntimeError('apktool did not emit classes.dex')
        unsigned = work / 'unsigned.apk'
        with zipfile.ZipFile(unsigned, 'w') as apk:
            apk.write(work / 'AndroidManifest.xml', 'AndroidManifest.xml')
            apk.write(dex, 'classes.dex')
        run(['jarsigner', '-keystore', str(args.keystore), '-storepass', 'android',
             '-keypass', 'android', '-sigalg', 'SHA256withRSA', '-digestalg',
             'SHA-256', str(unsigned), 'storage-probe'])
        shutil.copy2(unsigned, args.output)
    print(f'APK SHA-256: {hashlib.sha256(args.output.read_bytes()).hexdigest()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
