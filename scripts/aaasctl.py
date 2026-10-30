#!/usr/bin/env python3
"""Control an active, foreground AaaS two-output session."""

import argparse
import json
from pathlib import Path
import re
import socket
import sys

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
    subparsers.add_parser('stop', help='stop the shared AaaS runtime')
    args = parser.parse_args(argv)

    if args.operation == 'launch' and not PACKAGE.fullmatch(args.package):
        parser.error('package must be a dotted Android application ID')
    request = {'op': args.operation}
    if args.operation == 'launch':
        request['package'] = args.package
    elif args.operation == 'close':
        request['slot'] = args.slot
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
