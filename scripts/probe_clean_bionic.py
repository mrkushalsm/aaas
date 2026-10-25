#!/usr/bin/env python3
"""Run stock Android Bionic tools from read-only SDK partitions.

No Android files are patched, copied into a writable rootfs, or preloaded.
Only the runtime APEX payload is cached in the guarded external workspace.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).parent))
import android_workspace as ws


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def bwrap_argv(system_mount, runtime_mount, command):
    return [
        'bwrap', '--unshare-user', '--unshare-pid', '--unshare-net',
        '--clearenv', '--setenv', 'PATH', '/system/bin',
        '--setenv', 'ANDROID_ROOT', '/system',
        '--ro-bind', str(system_mount), '/', '--tmpfs', '/apex',
        '--ro-bind', str(runtime_mount), '/apex/com.android.runtime',
        '--dev', '/dev', '--proc', '/proc', '--tmpfs', '/tmp',
        '/system/bin/sh', '-c', command,
    ]


def run(workspace, command, timeout):
    workspace = Path(workspace).resolve()
    ws.check(workspace, 16 << 20)
    system_image = workspace / 'tmp/partitions/system.raw.img'
    if not system_image.is_file():
        raise RuntimeError(f'missing system image: {system_image}')
    payload_path = workspace / 'tmp/clean_runtime_payload.img'
    log_path = workspace / 'logs/clean-bionic-shell.log'
    with tempfile.TemporaryDirectory(prefix='aaas-clean-bionic-') as tmp:
        system_mount = Path(tmp) / 'system'
        runtime_mount = Path(tmp) / 'runtime'
        system_mount.mkdir()
        runtime_mount.mkdir()
        mounted_system = mounted_runtime = False
        try:
            subprocess.run(['guestmount', '--ro', '-a', str(system_image),
                            '-m', '/dev/sda', str(system_mount)], check=True)
            mounted_system = True
            apex = system_mount / 'system/apex/com.android.runtime.apex'
            with zipfile.ZipFile(apex) as archive:
                payload = archive.read('apex_payload.img')
            if payload_path.exists():
                if sha256(payload_path.read_bytes()) != sha256(payload):
                    raise RuntimeError(f'conflicting cached APEX payload: {payload_path}')
            else:
                payload_path.write_bytes(payload)
            subprocess.run(['guestmount', '--ro', '-a', str(payload_path),
                            '-m', '/dev/sda', str(runtime_mount)], check=True)
            mounted_runtime = True
            argv = bwrap_argv(system_mount, runtime_mount, command)
            result = subprocess.run(argv, capture_output=True, text=True,
                                    timeout=timeout, check=False)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(result.stdout + result.stderr)
            return dict(exit_code=result.returncode, log=str(log_path),
                        system_image=str(system_image),
                        runtime_apex_sha256=sha256(payload),
                        command=command)
        finally:
            if mounted_runtime:
                subprocess.run(['guestunmount', str(runtime_mount)], check=True)
            if mounted_system:
                subprocess.run(['guestunmount', str(system_mount)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--command', default='/system/bin/toybox uname -s; /system/bin/toybox id')
    args = parser.parse_args()
    try:
        result = run(args.workspace, args.command, args.timeout)
        print(json.dumps(result, indent=2))
        return result['exit_code']
    except (ws.WorkspaceError, RuntimeError, OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, zipfile.BadZipFile) as exc:
        print(f'clean Bionic probe: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
