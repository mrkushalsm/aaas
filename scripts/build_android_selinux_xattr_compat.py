#!/usr/bin/env python3
"""Build AaaS's narrow Android xattr and kernel-config compatibility preload."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile


SOURCE = Path(__file__).resolve().parents[1] / 'experiments/m1b/selinux_xattr_compat.c'


def _compiler(value: str | None = None) -> str:
    selected = value or os.environ.get('AAAS_ANDROID_CLANG') or 'clang'
    resolved = shutil.which(selected)
    if not resolved:
        raise RuntimeError(
            f'Android preload compiler not found: {selected}; install Clang or set '
            'AAAS_ANDROID_CLANG to an x86_64 Android-targeting Clang executable')
    return resolved


def _validate_elf(path: Path) -> None:
    data = path.read_bytes()
    if (len(data) < 64 or data[:4] != b'\x7fELF' or data[4] != 2 or
            data[5] != 1 or struct.unpack_from('<H', data, 18)[0] != 62 or
            struct.unpack_from('<H', data, 16)[0] != 3):
        raise RuntimeError('built SELinux xattr preload is not an x86_64 ELF shared object')


def build(output: Path, compiler: str | None = None) -> dict:
    output = Path(output).expanduser().absolute()
    if not SOURCE.is_file():
        raise RuntimeError(f'compatibility source is missing: {SOURCE}')
    output.parent.mkdir(parents=True, exist_ok=True)
    compiler_path = _compiler(compiler)
    fd, temporary_name = tempfile.mkstemp(prefix=f'.{output.name}.', dir=output.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        command = [compiler_path, '--target=x86_64-linux-android', '-fPIC', '-shared',
                   '-nostdlib', '-Wl,-soname,libaaas-selinux-xattr-compat.so',
                   '-Wl,--hash-style=both', '-o', str(temporary), str(SOURCE)]
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        _validate_elf(temporary)
        os.chmod(temporary, 0o755)
        os.replace(temporary, output)
    except subprocess.CalledProcessError as error:
        temporary.unlink(missing_ok=True)
        detail = (error.stderr or error.stdout or '').strip()
        raise RuntimeError(
            f'compiler exited {error.returncode}: {detail[-1600:]}') from error
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f'failed to build Android SELinux xattr preload: {error}') from error
    return {'output': str(output), 'compiler': compiler_path,
            'source': str(SOURCE), 'bytes': output.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--compiler')
    args = parser.parse_args()
    try:
        import json
        print(json.dumps(build(args.output, args.compiler), indent=2, sort_keys=True))
    except RuntimeError as error:
        parser.error(str(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
