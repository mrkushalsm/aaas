#!/usr/bin/env python3
"""Extract the stock audio framework binaries from the selected system image.

The system image is only mounted read-only. Extracted files are session overlay
inputs; the Android image and rootfs are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

sys_path = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(sys_path))
import android_workspace as workspace_guard


FILES = {
    'audioserver': ('system/bin/audioserver', 'DYN'),
    'libaudiohal.so': ('system/lib64/libaudiohal.so', 'DYN'),
}
MANIFEST = 'manifest.json'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def elf_type(path: Path) -> str:
    result = subprocess.run(['readelf', '-h', str(path)], check=True,
                            capture_output=True, text=True).stdout
    if 'Advanced Micro Devices X86-64' not in result:
        raise RuntimeError(f'{path.name} is not an x86_64 ELF')
    for line in result.splitlines():
        if line.strip().startswith('Type:'):
            return line.split(':', 1)[1].strip().split()[0]
    raise RuntimeError(f'ELF type missing from {path.name}')


def validate_outputs(output_dir: Path, source_hash: str) -> dict | None:
    manifest_path = output_dir / MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('schema_version') != 1 or manifest.get('system_image_sha256') != source_hash:
            return None
        entries = manifest.get('files', {})
        for name in FILES:
            path = output_dir / name
            if not path.is_file() or sha256_file(path) != entries[name]['sha256']:
                return None
            if elf_type(path) != 'DYN':
                return None
        return manifest
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.CalledProcessError):
        return None


def extract(system_image: Path, output_dir: Path, workspace: Path) -> dict:
    system_image = system_image.resolve(strict=True)
    output_dir = output_dir.resolve()
    workspace = workspace.resolve(strict=True)
    workspace_guard.check(workspace, 8 << 20)
    source_hash = sha256_file(system_image)
    existing = validate_outputs(output_dir, source_hash)
    if existing is not None:
        return existing

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aaas-audio-system-') as temp:
        mount = Path(temp) / 'system'
        mount.mkdir()
        mounted = False
        try:
            subprocess.run(['guestmount', '--ro', '-a', str(system_image),
                            '-m', '/dev/sda', str(mount)], check=True)
            mounted = True
            staged = {}
            for name, (relative, expected_type) in FILES.items():
                source = mount / relative
                if not source.is_file() or elf_type(source) != expected_type:
                    raise RuntimeError(f'expected Android x86_64 ELF at {relative}')
                target = Path(temp) / name
                shutil.copyfile(source, target)
                os.chmod(target, 0o755 if name == 'audioserver' else 0o644)
                staged[name] = target
        finally:
            if mounted:
                subprocess.run(['guestunmount', str(mount)], check=True)

        files = {}
        for name, staged_path in staged.items():
            destination = output_dir / name
            temp_destination = output_dir / (name + '.new')
            shutil.copyfile(staged_path, temp_destination)
            os.chmod(temp_destination, staged_path.stat().st_mode & 0o777)
            os.replace(temp_destination, destination)
            files[name] = {'sha256': sha256_file(destination),
                           'source_path': FILES[name][0],
                           'elf_type': elf_type(destination)}
        manifest = {'schema_version': 1, 'system_image_sha256': source_hash,
                    'files': files}
        manifest_path = output_dir / (MANIFEST + '.new')
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        os.replace(manifest_path, output_dir / MANIFEST)
    workspace_guard.check(workspace)
    verified = validate_outputs(output_dir, source_hash)
    if verified is None:
        raise RuntimeError('extracted audio overlay validation failed')
    return verified


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--system-image', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(extract(args.system_image, args.output_dir, args.workspace), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
