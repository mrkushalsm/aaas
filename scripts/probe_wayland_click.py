#!/usr/bin/env python3
"""Bounded host-side Wayland pointer test injector.

This is a disposable test harness, not the production input source.  It
creates a private uinput pointer, moves the host cursor over the AaaS window,
clicks the requested host-screen coordinate, and parks the cursor outside the
window.  The AaaS presenter still receives ordinary wl_pointer events from
KWin; no global input device is read by the AaaS code.
"""

import argparse
import ctypes
import fcntl
import json
import os
import sys
import time

EV_SYN = 0
EV_KEY = 1
EV_REL = 2
EV_ABS = 3
SYN_REPORT = 0
REL_X = 0
REL_Y = 1
ABS_X = 0
ABS_Y = 1
BTN_LEFT = 0x110
INPUT_PROP_POINTER = 0x00


def _ioc(direction, type_, nr, size):
    return (direction << 30) | (size << 16) | (ord(type_) << 8) | nr


def _io(type_, nr):
    return _ioc(0, type_, nr, 0)


def _iow(type_, nr, size):
    return _ioc(1, type_, nr, size)


class InputId(ctypes.Structure):
    _fields_ = [
        ('bustype', ctypes.c_uint16),
        ('vendor', ctypes.c_uint16),
        ('product', ctypes.c_uint16),
        ('version', ctypes.c_uint16),
    ]


class UinputSetup(ctypes.Structure):
    _fields_ = [
        ('id', InputId),
        ('name', ctypes.c_char * 80),
        ('ff_effects_max', ctypes.c_uint32),
    ]


class InputAbsInfo(ctypes.Structure):
    _fields_ = [
        ('value', ctypes.c_int32),
        ('minimum', ctypes.c_int32),
        ('maximum', ctypes.c_int32),
        ('fuzz', ctypes.c_int32),
        ('flat', ctypes.c_int32),
        ('resolution', ctypes.c_int32),
    ]


class UinputAbsSetup(ctypes.Structure):
    _fields_ = [
        ('code', ctypes.c_uint16),
        ('absinfo', InputAbsInfo),
    ]


class TimeVal(ctypes.Structure):
    _fields_ = [('tv_sec', ctypes.c_long), ('tv_usec', ctypes.c_long)]


class InputEvent(ctypes.Structure):
    _fields_ = [
        ('time', TimeVal),
        ('type', ctypes.c_uint16),
        ('code', ctypes.c_uint16),
        ('value', ctypes.c_int32),
    ]


UI_DEV_CREATE = _io('U', 1)
UI_DEV_DESTROY = _io('U', 2)
UI_DEV_SETUP = _iow('U', 3, ctypes.sizeof(UinputSetup))
UI_ABS_SETUP = _iow('U', 4, ctypes.sizeof(UinputAbsSetup))
UI_SET_EVBIT = _iow('U', 100, 4)
UI_SET_KEYBIT = _iow('U', 101, 4)
UI_SET_RELBIT = _iow('U', 102, 4)
UI_SET_ABSBIT = _iow('U', 103, 4)
UI_SET_PROPBIT = _iow('U', 110, 4)


def emit(fd, ev_type, code, value):
    ev = InputEvent()
    ev.time.tv_sec = 0
    ev.time.tv_usec = 0
    ev.type = ev_type
    ev.code = code
    ev.value = value
    os.write(fd, ctypes.string_at(ctypes.byref(ev), ctypes.sizeof(ev)))



def setup_absolute(fd, width, height, name):
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
    fcntl.ioctl(fd, UI_SET_KEYBIT, BTN_LEFT)
    fcntl.ioctl(fd, UI_SET_ABSBIT, ABS_X)
    fcntl.ioctl(fd, UI_SET_ABSBIT, ABS_Y)
    fcntl.ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_POINTER)
    for code, maximum in ((ABS_X, width - 1), (ABS_Y, height - 1)):
        axis = UinputAbsSetup()
        axis.code = code
        axis.absinfo.minimum = 0
        axis.absinfo.maximum = maximum
        fcntl.ioctl(fd, UI_ABS_SETUP, axis)
    setup = UinputSetup()
    setup.id.bustype = 0x03
    setup.id.vendor = 0x1
    setup.id.product = 0x1
    setup.id.version = 1
    setup.name = name.encode('utf-8')[:79]
    fcntl.ioctl(fd, UI_DEV_SETUP, setup)


def setup_relative(fd, name):
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
    fcntl.ioctl(fd, UI_SET_KEYBIT, BTN_LEFT)
    fcntl.ioctl(fd, UI_SET_RELBIT, REL_X)
    fcntl.ioctl(fd, UI_SET_RELBIT, REL_Y)
    fcntl.ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_POINTER)
    setup = UinputSetup()
    setup.id.bustype = 0x03
    setup.id.vendor = 0x1
    setup.id.product = 0x2
    setup.id.version = 1
    setup.name = name.encode('utf-8')[:79]
    fcntl.ioctl(fd, UI_DEV_SETUP, setup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--x', type=int, required=True, help='host screen x')
    parser.add_argument('--y', type=int, required=True, help='host screen y')
    parser.add_argument('--mode', choices=('absolute', 'relative'), default='absolute')
    parser.add_argument('--screen-width', type=int, default=1920)
    parser.add_argument('--screen-height', type=int, default=1200)
    parser.add_argument('--park-x', type=int, default=5)
    parser.add_argument('--park-y', type=int, default=5)
    parser.add_argument('--delay', type=float, default=0.25)
    parser.add_argument('--stick', action='store_true',
                        help='leave the button held while parking, testing stuck-button reconciliation')
    parser.add_argument('--no-park', action='store_true',
                        help='leave the released pointer over the target')
    args = parser.parse_args()

    if not (0 <= args.x < args.screen_width and 0 <= args.y < args.screen_height):
        parser.error('target is outside the configured host screen')
    if not (0 <= args.park_x < args.screen_width and 0 <= args.park_y < args.screen_height):
        parser.error('park point is outside the configured host screen')

    fd = os.open('/dev/uinput', os.O_RDWR | os.O_NONBLOCK)
    events = []
    name = f'aaas-m1c0-pointer-{os.getpid()}'
    try:
        if args.mode == 'absolute':
            setup_absolute(fd, args.screen_width, args.screen_height, name)
        else:
            setup_relative(fd, name)
        fcntl.ioctl(fd, UI_DEV_CREATE)
        events.append({'event': 'device_created', 'name': name, 'mode': args.mode})
        time.sleep(args.delay)

        if args.mode == 'absolute':
            emit(fd, EV_ABS, ABS_X, args.park_x)
            emit(fd, EV_ABS, ABS_Y, args.park_y)
            emit(fd, EV_SYN, SYN_REPORT, 0)
            events.append({'event': 'pointer_pre_parked', 'x': args.park_x, 'y': args.park_y})
            time.sleep(0.15)
            emit(fd, EV_ABS, ABS_X, args.x)
            emit(fd, EV_ABS, ABS_Y, args.y)
        else:
            emit(fd, EV_REL, REL_X, -32767)
            emit(fd, EV_REL, REL_Y, -32767)
            emit(fd, EV_SYN, SYN_REPORT, 0)
            time.sleep(0.1)
            emit(fd, EV_REL, REL_X, args.x)
            emit(fd, EV_REL, REL_Y, args.y)
        emit(fd, EV_SYN, SYN_REPORT, 0)
        events.append({'event': 'pointer_moved', 'x': args.x, 'y': args.y})
        time.sleep(args.delay)

        emit(fd, EV_KEY, BTN_LEFT, 1)
        emit(fd, EV_SYN, SYN_REPORT, 0)
        events.append({'event': 'button_press', 'button': BTN_LEFT})
        time.sleep(0.06)

        if args.stick:
            if args.mode == 'absolute':
                emit(fd, EV_ABS, ABS_X, args.park_x)
                emit(fd, EV_ABS, ABS_Y, args.park_y)
            else:
                emit(fd, EV_REL, REL_X, args.park_x - args.x)
                emit(fd, EV_REL, REL_Y, args.park_y - args.y)
            emit(fd, EV_SYN, SYN_REPORT, 0)
            events.append({'event': 'pointer_parked_while_held',
                           'x': args.park_x, 'y': args.park_y})
            time.sleep(args.delay)
            emit(fd, EV_KEY, BTN_LEFT, 0)
            emit(fd, EV_SYN, SYN_REPORT, 0)
            events.append({'event': 'button_release_after_leave', 'button': BTN_LEFT})
        else:
            emit(fd, EV_KEY, BTN_LEFT, 0)
            emit(fd, EV_SYN, SYN_REPORT, 0)
            events.append({'event': 'button_release', 'button': BTN_LEFT})
            time.sleep(args.delay)
            if args.no_park:
                events.append({'event': 'pointer_left_at_target', 'x': args.x, 'y': args.y})
            else:
                if args.mode == 'absolute':
                    emit(fd, EV_ABS, ABS_X, args.park_x)
                    emit(fd, EV_ABS, ABS_Y, args.park_y)
                else:
                    emit(fd, EV_REL, REL_X, args.park_x - args.x)
                    emit(fd, EV_REL, REL_Y, args.park_y - args.y)
                emit(fd, EV_SYN, SYN_REPORT, 0)
                events.append({'event': 'pointer_parked', 'x': args.park_x, 'y': args.park_y})
    finally:
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(fd)
        events.append({'event': 'device_destroyed'})
        for event in events:
            print(json.dumps(event, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
