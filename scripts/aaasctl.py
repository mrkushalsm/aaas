#!/usr/bin/env python3
"""Control an active, foreground AaaS two-output session."""

import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

import aaas_storage

TMP = Path('/run/media/mrkus/Homework/aaas-workspace/tmp')
PACKAGE = re.compile(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+')


def active_control_socket():
    candidates = sorted(TMP.glob('m1b84_session_*/ipc/aaas-control.sock'),
                        key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.settimeout(90)
            connection.connect(str(path))
            return connection
        except OSError:
            try:
                connection.close()
            except UnboundLocalError:
                pass
    raise RuntimeError('no active AaaS app session control socket')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='operation', required=True)
    subparsers.add_parser('list', help='list active app windows')
    launch = subparsers.add_parser('launch', help='launch an installed Android package')
    launch.add_argument('package')
    close = subparsers.add_parser('close', help='close an app window by bounded slot')
    close.add_argument('slot', type=int, choices=(1, 2))
    stop_app = subparsers.add_parser('stop-app', help='stop Android app in a window slot')
    stop_app.add_argument('slot', type=int, choices=(1, 2))
    storage = subparsers.add_parser('storage', help='inspect Android shared storage')
    storage_sub = storage.add_subparsers(dest='storage_operation', required=True)
    storage_sub.add_parser(
        'path', help='print the persistent Linux path backing Android shared storage')
    storage_sub.add_parser('status', help='show the shared-storage directory state')
    storage_sub.add_parser(
        'sync', help='repair host ACL access (does not scan Android MediaStore)')
    scan = storage_sub.add_parser(
        'scan', help='ask the active Android session to index one shared media file')
    scan.add_argument('path', help='relative path under the shared Android storage root')
    clipboard = subparsers.add_parser(
        'clipboard', help='configure the opt-in Android clipboard input method')
    clipboard_sub = clipboard.add_subparsers(dest='clipboard_operation', required=True)
    clipboard_sub.add_parser(
        'setup', help='open Android input-method settings; selection stays user-controlled')
    clipboard_sub.add_parser(
        'use', help='temporarily select the AaaS IME for the active runtime session')
    clipboard_sub.add_parser(
        'restore', help='restore the input method that was active before aaasctl clipboard use')
    probe = clipboard_sub.add_parser(
        'probe', help='launch a controlled clipboard acceptance text-field probe')
    probe.add_argument('mode', choices=('android-copy', 'host-paste'))
    subparsers.add_parser('stop', help='stop the shared AaaS runtime')
    args = parser.parse_args(argv)

    if args.operation == 'storage':
        path = aaas_storage.backing_path()
        media_root = aaas_storage.media_root_path()
        if args.storage_operation == 'path':
            print(path)
            return 0
        if args.storage_operation == 'scan':
            try:
                scanned_path = aaas_storage.validate_media_scan_path(args.path, path)
                relative = scanned_path.relative_to(path.resolve(strict=True)).as_posix()
                connection = active_control_socket()
                with connection:
                    connection.sendall(json.dumps(
                        {'op': 'storage_scan', 'path': relative},
                        separators=(',', ':')).encode('utf-8') + b'\n')
                    response = connection.recv(4097)
                if len(response) > 4096:
                    raise RuntimeError('session returned an oversized response')
                result = json.loads(response.decode('utf-8'))
                print(json.dumps(result, indent=2))
                return 0 if result.get('ok') else 1
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                print(f'aaasctl: MediaStore scan failed: {error}', file=sys.stderr)
                return 1
        try:
            if args.storage_operation == 'sync':
                aaas_storage.ensure_host_access(media_root)
                aaas_storage.ensure_host_access(path)
            acl = aaas_storage._acl_entries(path)
            media_acl = aaas_storage._acl_entries(media_root)
            host_uid = os.getuid()
            acl_ready = {
                f'user:{host_uid}:rwx', f'default:user:{host_uid}:rwx'
            }.issubset(set(acl)) and {
                f'user:{host_uid}:rwx', f'default:user:{host_uid}:rwx'
            }.issubset(set(media_acl))
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            print(f'aaasctl: shared-storage access check failed: {error}',
                  file=sys.stderr)
            return 1
        result = {
            'path': str(path),
            'exists': path.is_dir() and not path.is_symlink(),
            'media_root': str(media_root),
            'media_root_exists': media_root.is_dir() and not media_root.is_symlink(),
            'mount_mode': 'direct persistent directory',
            'owner_uid': path.stat().st_uid if path.exists() else None,
            'host_acl_ready': acl_ready,
            'host_accessible': (
                media_root.is_dir() and os.access(media_root, os.R_OK | os.W_OK | os.X_OK)
                and path.is_dir() and os.access(path, os.R_OK | os.W_OK | os.X_OK)
            ),
        }
        print(json.dumps(result, indent=2))
        if args.storage_operation == 'sync' and acl_ready:
            print('AaaS shared-storage host ACLs are synchronized; '
                  'Android MediaStore was not scanned.')
        return 0 if (result['exists'] and result['media_root_exists']
                     and acl_ready and result['host_accessible']) else 1

    if args.operation == 'launch' and not PACKAGE.fullmatch(args.package):
        parser.error('package must be a dotted Android application ID')
    clipboard_ops = {'setup': 'clipboard_setup', 'use': 'clipboard_ime_use',
                     'restore': 'clipboard_ime_restore', 'probe': 'clipboard_probe'}
    request = {'op': clipboard_ops[args.clipboard_operation]
               if args.operation == 'clipboard' else args.operation}
    if args.operation == 'clipboard' and args.clipboard_operation == 'probe':
        request['mode'] = args.mode
    if args.operation == 'launch':
        request['package'] = args.package
    elif args.operation in ('close', 'stop-app'):
        request['slot'] = args.slot
        if args.operation == 'stop-app':
            request['op'] = 'stop_app'
    try:
        connection = active_control_socket()
        with connection:
            connection.sendall(json.dumps(request, separators=(',', ':')).encode('utf-8')
                                + b'\n')
            response = connection.recv(4097)
        if len(response) > 4096:
            raise RuntimeError('session returned an oversized response')
        result = json.loads(response.decode('utf-8'))
        print(json.dumps(result, indent=2))
        return 0 if result.get('ok') else 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f'aaasctl: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
