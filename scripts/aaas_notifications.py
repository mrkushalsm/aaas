"""Bounded, session-local Android notification forwarding over session D-Bus."""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import uuid

from aaas_clipboard import app_uid_to_host_uid

MAGIC = b'AASN1\n'
MAX_FRAME = 32 * 1024
MAX_ACTIVE = 256
EVENT_RE = re.compile(r'event-[0-9a-f]{32}\.frame\Z')
PACKAGE_RE = re.compile(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+\Z')


def _b64(value: str) -> bytes:
    return base64.urlsafe_b64encode(value.encode('utf-8', errors='strict')).rstrip(b'=')


def _unb64(value: bytes) -> str:
    return base64.urlsafe_b64decode(value + b'=' * (-len(value) % 4)).decode('utf-8', errors='strict')


def encode_event(event: dict) -> bytes:
    """Encode a posted/removed notification without accepting arbitrary extras."""
    kind = event.get('type')
    if kind not in ('posted', 'removed'):
        raise ValueError('invalid notification event type')
    package = event.get('package')
    if not isinstance(package, str) or not PACKAGE_RE.fullmatch(package):
        raise ValueError('invalid notification package')
    user = event.get('user')
    key = event.get('key')
    if not isinstance(user, str) or not user.isdigit() or len(user) > 12:
        raise ValueError('invalid Android user identity')
    if not isinstance(key, str) or not key or len(key.encode('utf-8')) > 2048:
        raise ValueError('invalid Android notification key')
    values = [package, user, key]
    if kind == 'posted':
        for field, limit in (('app', 256), ('title', 1024), ('body', 8192)):
            value = event.get(field, '')
            if not isinstance(value, str) or len(value.encode('utf-8')) > limit:
                raise ValueError(f'invalid or oversized notification {field}')
            if '\x00' in value:
                raise ValueError('notification text contains NUL')
            values.append(value)
    frame = MAGIC + (b'P\n' if kind == 'posted' else b'R\n') + b'\n'.join(
        _b64(value) for value in values) + b'\n'
    if len(frame) > MAX_FRAME:
        raise ValueError('notification event exceeds frame limit')
    return frame


def decode_event(frame: bytes) -> dict:
    if not isinstance(frame, bytes) or len(frame) > MAX_FRAME or not frame.startswith(MAGIC):
        raise ValueError('invalid notification frame')
    lines = frame[len(MAGIC):].splitlines()
    if not lines or lines[0] not in (b'P', b'R'):
        raise ValueError('invalid notification frame kind')
    posted = lines[0] == b'P'
    expected = 7 if posted else 4
    if len(lines) != expected:
        raise ValueError('invalid notification frame field count')
    try:
        values = [_unb64(line) for line in lines[1:]]
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError('invalid notification frame encoding') from error
    event = {'type': 'posted' if posted else 'removed', 'package': values[0],
             'user': values[1], 'key': values[2]}
    if posted:
        event.update(zip(('app', 'title', 'body'), values[3:]))
    # Re-run the strict validator so non-canonical/oversized input is rejected.
    if encode_event(event) != frame:
        raise ValueError('non-canonical notification event')
    return event


def prepare_ipc_directory(ipc_dir: Path) -> Path:
    root = Path(ipc_dir)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('notification IPC root is unsafe')
    target = root / 'notifications'
    if target.is_symlink():
        raise ValueError('notification IPC directory is a symlink')
    target.mkdir(mode=0o1733, exist_ok=True)
    if target.stat().st_uid != os.getuid() or target.stat().st_dev != root.stat().st_dev:
        raise ValueError('notification IPC directory has unexpected ownership')
    # Match the tested Android clipboard IPC pattern: apps can create entries
    # but cannot enumerate or read other writers' frames. Sticky ownership
    # prevents removal of another UID's entry. The host gets inherited read
    # access only; the adapter still accepts frames from the listener UID only.
    target.chmod(0o1733)
    # The host desktop user is the deliberate notification destination. A
    # default ACL gives that one host UID read access to event files while
    # keeping files private from all other Android package UIDs.
    subprocess.run(['setfacl', '-m', f'd:u:{os.getuid()}:r--', str(target)], check=True)
    return target


def parse_runtime_state(value: str) -> tuple[int, bool] | None:
    fields = value.split()
    if len(fields) != 2 or fields[1] not in ('0', '1'):
        return None
    try:
        uid = int(fields[0], 10)
    except ValueError:
        return None
    if not 10000 <= uid <= 65535:
        return None
    return uid, fields[1] == '1'


def authorized_listener_uid(state: tuple[int, bool] | None) -> int | None:
    """Return the listener UID only while Android reports explicit access."""
    if state is None or not state[1]:
        return None
    return state[0]


def clear_session_events(ipc_dir: Path) -> bool:
    directory = Path(ipc_dir) / 'notifications'
    if directory.is_symlink() or not directory.is_dir():
        return False
    good = True
    for path in directory.iterdir():
        try:
            info = path.lstat()
            if stat.S_ISREG(info.st_mode) and (
                    EVENT_RE.fullmatch(path.name) or path.name.startswith('.event-')):
                path.unlink()
            else:
                good = False
        except OSError:
            good = False
    return good


def consume_frame(path: Path, expected_uid: int) -> dict:
    """Read only a regular, bounded frame created by the listener's mapped UID."""
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                 getattr(os, 'O_CLOEXEC', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid or info.st_size > MAX_FRAME:
            raise ValueError('notification frame has unsafe type, owner, or size')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            frame = stream.read(MAX_FRAME + 1)
    finally:
        os.close(fd)
    if len(frame) > MAX_FRAME:
        raise ValueError('notification frame exceeds limit')
    return decode_event(frame)


class NotificationForwarder:
    """Translate Android notification keys to this session's host notification IDs."""
    def __init__(self, notify, close, *, max_active=MAX_ACTIVE):
        self.notify = notify
        self.close = close
        self.max_active = max_active
        self.active: dict[str, tuple[int, str]] = {}
        self.by_id: dict[int, str] = {}
        self.order: list[str] = []

    @staticmethod
    def key(event: dict) -> str:
        return json.dumps([event['user'], event['package'], event['key']],
                          ensure_ascii=False, separators=(',', ':'))

    def dispatch(self, event: dict) -> int | None:
        identity = self.key(event)
        current = self.active.get(identity)
        if event['type'] == 'removed':
            if current:
                self.close(current[0])
                self.by_id.pop(current[0], None)
                del self.active[identity]
                self.order.remove(identity)
                return current[0]
            return None
        app = event['app'] or event['package']
        existing = current[0] if current else 0
        notification_id = int(self.notify(app, existing, event['title'], event['body']))
        if current:
            self.order.remove(identity)
            if current[0] != notification_id:
                self.by_id.pop(current[0], None)
        self.active[identity] = (notification_id, event['package'])
        self.by_id[notification_id] = event['package']
        self.order.append(identity)
        while len(self.order) > self.max_active:
            oldest = self.order.pop(0)
            old_id, _ = self.active.pop(oldest)
            self.by_id.pop(old_id, None)
            self.close(old_id)
        return notification_id

    def activation_package(self, notification_id: int, action_key: str) -> str | None:
        """Resolve only Plasma's default activation for an active Android notice."""
        if action_key != 'default':
            return None
        return self.by_id.get(int(notification_id))

    def close_all(self) -> None:
        for notification_id, _ in tuple(self.active.values()):
            try:
                self.close(notification_id)
            except Exception:
                pass
        self.active.clear()
        self.order.clear()


def run_bridge(directory: Path, android_uid: int) -> int:
    # D-Bus calls run from the same session user as the AaaS launcher. Files are
    # read in a mapped namespace so the normal Android app UID remains private.
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    proxy = bus.get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications')
    iface = dbus.Interface(proxy, 'org.freedesktop.Notifications')
    # Fail closed at startup if no notification service is available.
    iface.GetServerInformation()
    forwarder = NotificationForwarder(
        lambda app, replaces, title, body: int(iface.Notify(
            app, dbus.UInt32(replaces), '', title, html.escape(body),
            ['default', 'Open application'], {}, 5000)),
        lambda notification_id: iface.CloseNotification(dbus.UInt32(notification_id)))

    def notification_action(notification_id, action_key):
        try:
            package = forwarder.activation_package(int(notification_id), str(action_key))
        except (TypeError, ValueError):
            package = None
        if package is None:
            return
        # Package names were validated when the Android event was decoded.
        # Use the existing runtime control protocol, never a shell command.
        control = Path(__file__).with_name('aaasctl.py')
        try:
            subprocess.Popen(
                [sys.executable, str(control), 'launch', package],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
            print(f'notification activation requested package={package}', flush=True)
        except OSError as error:
            print(f'notification activation failed package={package} '
                  f'error={type(error).__name__}', flush=True)

    notification_owner = str(bus.get_name_owner('org.freedesktop.Notifications'))
    bus.add_match_string(
        "type='signal',sender='" + notification_owner + "',"
        "interface='org.freedesktop.Notifications',member='ActionInvoked',"
        "path='/org/freedesktop/Notifications'")

    def dispatch_notification_signal(_connection, message):
        if (message.get_type() == dbus.lowlevel.MESSAGE_TYPE_SIGNAL and
                message.get_sender() == notification_owner and
                message.get_interface() == 'org.freedesktop.Notifications' and
                message.get_member() == 'ActionInvoked' and
                message.get_path() == '/org/freedesktop/Notifications'):
            arguments = message.get_args_list()
            if len(arguments) == 2:
                notification_action(*arguments)
        return dbus.lowlevel.HANDLER_RESULT_NOT_YET_HANDLED

    bus.add_message_filter(dispatch_notification_signal)
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    directory = Path(directory)
    expected_uid = app_uid_to_host_uid(android_uid)
    print('notification D-Bus bridge ready', flush=True)
    while not stopping:
        for path in sorted(directory.iterdir()):
            if not EVENT_RE.fullmatch(path.name):
                continue
            try:
                event = consume_frame(path, expected_uid)
                notification_id = forwarder.dispatch(event)
                if event['type'] == 'posted':
                    print(f"notification forwarded package={event['package']} id={notification_id}", flush=True)
                elif notification_id is not None:
                    print(f"notification closed package={event['package']} id={notification_id}", flush=True)
            except (OSError, ValueError, dbus.DBusException) as error:
                print(f'notification frame rejected: {type(error).__name__}', flush=True)
            finally:
                try:
                    info = path.lstat()
                    # Event names are unique to this session and the directory
                    # is AaaS-owned. Remove malformed host-owned fixtures too,
                    # so one bad frame cannot cause an unbounded log loop.
                    if stat.S_ISREG(info.st_mode):
                        path.unlink()
                except OSError:
                    pass
        # dbus-python dispatches incoming signals through its registered main
        # loop; SessionBus itself does not expose read_write_dispatch on all
        # supported dbus-python versions. Iterate non-blockingly so filesystem
        # events and SIGTERM remain responsive as well.
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)
        time.sleep(.05)
    forwarder.close_all()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ipc-dir', type=Path, required=True)
    parser.add_argument('--android-uid', type=int, required=True)
    args = parser.parse_args(argv)
    if not 10000 <= args.android_uid <= 65535:
        parser.error('Android UID outside application range')
    return run_bridge(args.ipc_dir, args.android_uid)


if __name__ == '__main__':
    raise SystemExit(main())
