#!/usr/bin/env python3
"""Build a session-local services.jar with nonblocking optional codec discovery."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from patch_m1e_display_content_mode import (
    ALARM_HANDLER_CLASS, ALARM_PATCH, BASE_SHA256, APKTOOL_SHA256,
    patch_alarm_fallback, patch_storage_transcoding_default, sha256,
)


def build_overlay(original, apktool, output, receipt_path, work_parent=None):
    original, apktool, output = map(Path, (original, apktool, output))
    if original.resolve() == output.resolve():
        raise ValueError('output must not replace the preserved input services JAR')
    if sha256(original) != BASE_SHA256:
        raise ValueError('services diagnostic overlay checksum mismatch')
    if sha256(apktool) != APKTOOL_SHA256:
        raise ValueError('apktool checksum mismatch')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aaas-m4-storage-services-',
                                     dir=work_parent) as temp:
        work = Path(temp)
        decoded, rebuilt = work / 'decoded', work / 'rebuilt.apk'
        subprocess.run(['java', '-jar', str(apktool), 'd', '-f', '-r',
                        str(original), '-o', str(decoded)], check=True)
        smali = decoded / 'smali/com/android/server/StorageManagerService.smali'
        if not smali.is_file():
            raise RuntimeError(f'StorageManagerService class not found: {smali}')
        smali.write_text(patch_storage_transcoding_default(smali.read_text()))
        alarm_smali = decoded / ALARM_HANDLER_CLASS
        if not alarm_smali.is_file():
            raise RuntimeError(f'AlarmHandler class not found: {alarm_smali}')
        alarm_smali.write_text(patch_alarm_fallback(alarm_smali.read_text()))
        subprocess.run(['java', '-jar', str(apktool), 'b', str(decoded),
                        '-o', str(rebuilt)], check=True)
        with zipfile.ZipFile(rebuilt) as archive:
            dex = archive.read('classes.dex')
        staged = output.with_suffix(output.suffix + '.tmp')
        try:
            with zipfile.ZipFile(original) as source, zipfile.ZipFile(staged, 'w') as target:
                if source.namelist().count('classes.dex') != 1:
                    raise RuntimeError('expected one services classes.dex entry')
                for info in source.infolist():
                    target.writestr(info, dex if info.filename == 'classes.dex'
                                    else source.read(info.filename))
            os.replace(staged, output)
        finally:
            staged.unlink(missing_ok=True)
    with zipfile.ZipFile(output) as archive:
        dex_hash = hashlib.sha256(archive.read('classes.dex')).hexdigest()
    result = {
        'input': str(original.resolve()), 'input_sha256': sha256(original),
        'output': str(output.resolve()), 'output_sha256': sha256(output),
        'classes_dex_sha256': dex_hash,
        'patched_method': 'StorageManagerService.configureTranscoding',
        'default': 'false; system property and DeviceConfig overrides preserved',
        'alarm_fallback': 'AlarmHandler delegates due alarms to deliverAlarmsLocked and reschedules',
        'alarm_handler_class': str(ALARM_HANDLER_CLASS),
        'alarm_source_patch': str(ALARM_PATCH),
        'alarm_source_patch_sha256': sha256(ALARM_PATCH),
        'apktool_sha256': sha256(apktool),
    }
    if receipt_path:
        receipt_path = Path(receipt_path)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--apktool', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--work-parent', type=Path)
    args = parser.parse_args()
    print(json.dumps(build_overlay(args.original, args.apktool, args.output,
                                   args.receipt, args.work_parent), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
