#!/usr/bin/env python3
"""Operator-driven nested Wayland gate; event evidence is machine checked.

The compositor command must create the supplied socket. This harness does not
assume Lipstick's still-unverified nested-server configuration.
"""
import argparse
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path


def events(path):
    out = []
    if path.exists():
        for line in path.read_text(errors='replace').splitlines():
            if line.startswith('{'):
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def validate(client_logs):
    rows = {name: events(path) for name, path in client_logs.items()}
    errors = []
    for name, records in rows.items():
        kinds = {r.get('event') for r in records}
        required_events = ('expose', 'focus_in', 'resize', 'close') if name == 'a' else ('expose', 'focus_in', 'resize')
        for required in required_events:
            if required not in kinds:
                errors.append(f'{name}: missing {required}')
        sizes = {(r.get('width'), r.get('height')) for r in records if r.get('event') == 'resize'}
        if len(sizes) < 2:
            errors.append(f'{name}: no distinct resize geometry')
    return errors


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--compositor', nargs='+', required=True)
    p.add_argument('--socket', type=Path, required=True)
    p.add_argument('--client', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--timeout', type=int, default=20)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.socket.exists():
        raise SystemExit(f'socket already exists: {args.socket}')
    children = []
    logs = {}
    try:
        with (args.output / 'compositor.log').open('w') as log:
            compositor = subprocess.Popen(args.compositor, stdout=log, stderr=subprocess.STDOUT,
                                          start_new_session=True)
            children.append(compositor)
            deadline = time.monotonic() + args.timeout
            while not args.socket.exists() and time.monotonic() < deadline:
                if compositor.poll() is not None:
                    raise RuntimeError(f'compositor exited {compositor.returncode} before socket')
                time.sleep(0.1)
            if not args.socket.exists():
                raise RuntimeError('compositor socket timeout')
            for name in ('a', 'b'):
                path = args.output / f'client-{name}.jsonl'
                env = os.environ.copy()
                env['WAYLAND_DISPLAY'] = str(args.socket)
                env['QT_QPA_PLATFORM'] = 'wayland'
                handle = path.open('w')
                child = subprocess.Popen([str(args.client), name], env=env, stdout=handle,
                                         stderr=subprocess.STDOUT, start_new_session=True)
                handle.close()
                logs[name] = path
                children.append(child)
            print('Focus each client, resize each to a different size, then close client a through the compositor. Leave b open.')
            input('Press Enter after those actions; the compositor will then be crash-tested. ')
            errors = validate(logs)
            if children[1].poll() is None:
                errors.append('client a did not exit after close')
            if children[2].poll() is not None:
                errors.append('client b exited before crash test')
            os.killpg(compositor.pid, signal.SIGKILL)
            compositor.wait(timeout=5)
            for child in children[1:]:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    errors.append(f'client {child.pid} remained after compositor crash')
            stale_socket = args.socket.exists()
            if stale_socket:
                if stat.S_ISSOCK(args.socket.stat().st_mode):
                    args.socket.unlink()
                else:
                    errors.append('socket path replaced by non-socket; refused cleanup')
            (args.output / 'verdict.json').write_text(json.dumps({'passed': not errors, 'errors': errors,
                                                                  'stale_socket_cleaned': stale_socket}, indent=2) + '\n')
            print('PASS' if not errors else 'FAIL: ' + '; '.join(errors))
            return int(bool(errors))
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == '__main__':
    sys.exit(main())
