#!/usr/bin/env python3
"""Session-owned, UID-authenticated Android PCM bridge to pipewire-pulse."""
import argparse
import ctypes
import ctypes.util
import os
import signal
import socket
import socketserver
import stat
import struct
import sys
import threading
from pathlib import Path

MAGIC = b'AAASAU01'
VERSION = 1
PLAYBACK = 1
CAPTURE = 2
S16_LE = 1
MAX_RATE = 96000
MAX_CHANNELS = 2
MAX_BUFFER = 262144
MAX_CLIENTS = 4
HELLO = struct.Struct('<8sHHIHH')


def pcm16_summary(data):
    """Return bounded signal statistics without retaining or logging PCM."""
    if len(data) % 2:
        raise ValueError('unaligned S16LE PCM')
    count = nonzero = crossings = peak = 0
    total = total_squares = 0
    previous = None
    for (sample,) in struct.iter_unpack('<h', data):
        count += 1
        total += sample
        total_squares += sample * sample
        magnitude = abs(sample)
        peak = max(peak, magnitude)
        nonzero += magnitude != 0
        if previous is not None and ((previous < 0 <= sample) or
                                     (previous >= 0 > sample)):
            crossings += 1
        previous = sample
    mean = total / count if count else 0.0
    rms = max(0.0, total_squares / count - mean * mean) ** 0.5 if count else 0.0
    return {'frames': count, 'nonzero': nonzero, 'peak': peak,
            'rms': round(rms, 2), 'zero_crossings': crossings}


class PaSampleSpec(ctypes.Structure):
    _fields_ = [('format', ctypes.c_int), ('rate', ctypes.c_uint32),
                ('channels', ctypes.c_uint8)]


class PulseSimple:
    """Small ctypes wrapper around Pulse's synchronous API (PipeWire-compatible)."""
    def __init__(self, direction, rate, channels, device=None):
        library = ctypes.util.find_library('pulse-simple')
        if not library:
            raise RuntimeError('libpulse-simple is unavailable')
        self.lib = ctypes.CDLL(library)
        self.lib.pa_simple_new.argtypes = [ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.POINTER(PaSampleSpec), ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int)]
        self.lib.pa_simple_new.restype = ctypes.c_void_p
        self.lib.pa_simple_free.argtypes = [ctypes.c_void_p]
        self.lib.pa_simple_drain.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        self.lib.pa_simple_drain.restype = ctypes.c_int
        self.lib.pa_simple_write.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_size_t, ctypes.POINTER(ctypes.c_int)]
        self.lib.pa_simple_write.restype = ctypes.c_int
        self.lib.pa_simple_read.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.c_size_t, ctypes.POINTER(ctypes.c_int)]
        self.lib.pa_simple_read.restype = ctypes.c_int
        # Pulse sample-format enum: PA_SAMPLE_S16LE = 3.
        spec = PaSampleSpec(3, rate, channels)
        error = ctypes.c_int(0)
        selected_device = device.encode('utf-8') if device else None
        self.handle = self.lib.pa_simple_new(None, b'AaaS Android Audio', direction,
            selected_device, b'AaaS Android playback' if direction == PLAYBACK else b'AaaS Android microphone',
            ctypes.byref(spec), None, None, ctypes.byref(error))
        if not self.handle:
            raise RuntimeError(f'Pulse/PipeWire stream creation failed (code {error.value})')

    def write(self, data):
        error = ctypes.c_int(0)
        buf = ctypes.create_string_buffer(data)
        if self.lib.pa_simple_write(self.handle, buf, len(data), ctypes.byref(error)) < 0:
            raise RuntimeError(f'Pulse playback write failed (code {error.value})')

    def read(self, size):
        error = ctypes.c_int(0)
        buf = ctypes.create_string_buffer(size)
        if self.lib.pa_simple_read(self.handle, buf, size, ctypes.byref(error)) < 0:
            raise RuntimeError(f'Pulse capture read failed (code {error.value})')
        return buf.raw

    def drain(self):
        error = ctypes.c_int(0)
        if self.lib.pa_simple_drain(self.handle, ctypes.byref(error)) < 0:
            raise RuntimeError(f'Pulse playback drain failed (code {error.value})')

    def close(self):
        if self.handle:
            self.lib.pa_simple_free(self.handle)
            self.handle = None


class AudioServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False
    block_on_close = False

    def handle_error(self, request, client_address):
        # socketserver's default traceback can print arbitrary PCM buffers.
        # Treat client failures as a disconnect and never log media payloads.
        return

    def __init__(self, socket_path, expected_uid, playback_sink=None,
                 capture_source=None):
        self.expected_uid = expected_uid
        self.playback_sink = playback_sink
        self.capture_source = capture_source
        self.client_lock = threading.Lock()
        self.active_clients = 0
        self.stop_event = threading.Event()
        super().__init__(str(socket_path), AudioHandler)

    def acquire_client(self):
        with self.client_lock:
            if self.active_clients >= MAX_CLIENTS:
                return False
            self.active_clients += 1
            return True

    def release_client(self):
        with self.client_lock:
            self.active_clients = max(0, self.active_clients - 1)


class AudioHandler(socketserver.BaseRequestHandler):
    def handle(self):
        conn = self.request
        conn.settimeout(3.0)
        try:
            if not hasattr(socket, 'SO_PEERCRED'):
                return
            creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                    struct.calcsize('3i'))
            _pid, uid, _gid = struct.unpack('3i', creds)
            if uid != self.server.expected_uid:
                return
            if not self.server.acquire_client():
                return
            try:
                self._serve_stream(conn)
            finally:
                self.server.release_client()
        except (OSError, ValueError, RuntimeError) as error:
            print(f'audio client rejected ({type(error).__name__})', flush=True)
            return

    def _read_exact(self, size):
        chunks = bytearray()
        while len(chunks) < size:
            part = self.request.recv(size - len(chunks))
            if not part:
                raise OSError('peer disconnected')
            chunks.extend(part)
        return bytes(chunks)

    def _serve_stream(self, conn):
        hello = HELLO.unpack(self._read_exact(HELLO.size))
        magic, version, direction, rate, channels, fmt = hello
        if (magic != MAGIC or version != VERSION or direction not in (PLAYBACK, CAPTURE)
                or not 8000 <= rate <= MAX_RATE or not 1 <= channels <= MAX_CHANNELS
                or fmt != S16_LE):
            return
        frame_size = channels * 2
        device = (self.server.playback_sink if direction == PLAYBACK
                  else self.server.capture_source)
        pulse = PulseSimple(direction, rate, channels, device=device)
        direction_name = 'playback' if direction == PLAYBACK else 'capture'
        print(f'audio stream opened direction={direction_name} rate={rate} '
              f'channels={channels} format=S16_LE', flush=True)
        conn.settimeout(None)
        transferred = 0
        capture_stats = {'frames': 0, 'nonzero': 0, 'peak': 0,
                         'sum': 0, 'sum_squares': 0, 'crossings': 0,
                         'previous': None}
        try:
            if direction == PLAYBACK:
                pending = bytearray()
                while not self.server.stop_event.is_set():
                    data = conn.recv(min(MAX_BUFFER, 16384))
                    if not data:
                        break
                    pending.extend(data)
                    aligned = len(pending) - len(pending) % frame_size
                    if aligned:
                        pulse.write(bytes(pending[:aligned]))
                        transferred += aligned
                        del pending[:aligned]
                    if len(pending) >= frame_size:
                        raise ValueError('invalid PCM frame alignment')
                if pending and not self.server.stop_event.is_set():
                    raise ValueError('invalid PCM frame alignment')
                if not self.server.stop_event.is_set():
                    pulse.drain()
            else:
                chunk_size = max(frame_size, rate // 50 * frame_size)
                chunk_size = min(chunk_size - chunk_size % frame_size, MAX_BUFFER)
                while not self.server.stop_event.is_set():
                    data = pulse.read(chunk_size)
                    summary = pcm16_summary(data)
                    capture_stats['frames'] += summary['frames']
                    capture_stats['nonzero'] += summary['nonzero']
                    capture_stats['peak'] = max(capture_stats['peak'], summary['peak'])
                    for (sample,) in struct.iter_unpack('<h', data):
                        capture_stats['sum'] += sample
                        capture_stats['sum_squares'] += sample * sample
                        previous = capture_stats['previous']
                        if previous is not None and ((previous < 0 <= sample) or
                                                     (previous >= 0 > sample)):
                            capture_stats['crossings'] += 1
                        capture_stats['previous'] = sample
                    conn.sendall(data)
                    transferred += len(data)
        finally:
            pulse.close()
            message = (f'audio stream closed direction={direction_name} '
                       f'bytes={transferred}')
            if direction == CAPTURE:
                frames = capture_stats['frames']
                mean = capture_stats['sum'] / frames if frames else 0.0
                rms = max(0.0, capture_stats['sum_squares'] / frames - mean * mean) ** 0.5 if frames else 0.0
                message += (f' frames={frames} rms={rms:.2f} '
                            f'peak={capture_stats["peak"]} '
                            f'nonzero={capture_stats["nonzero"]} '
                            f'zero_crossings={capture_stats["crossings"]}')
            print(message, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--android-host-uid', type=int, required=True,
                        help='host-mapped UID of Android audioserver (1041 in guest)')
    parser.add_argument('--playback-sink', default=os.environ.get('AAAS_AUDIO_PLAYBACK_SINK'),
                        help='optional PipeWire/Pulse sink name (defaults to host default)')
    parser.add_argument('--capture-source', default=os.environ.get('AAAS_AUDIO_CAPTURE_SOURCE'),
                        help='optional PipeWire/Pulse source name (defaults to host default)')
    args = parser.parse_args(argv)
    if args.android_host_uid < 0:
        parser.error('Android host UID must be nonnegative')
    path = Path(args.socket)
    path.parent.mkdir(mode=0o711, parents=True, exist_ok=True)
    try:
        existing = path.lstat()
    except FileNotFoundError:
        existing = None
    if existing:
        if not stat.S_ISSOCK(existing.st_mode):
            raise RuntimeError(f'refusing to replace non-socket: {path}')
        raise RuntimeError(f'refusing to replace existing socket: {path}')
    server = AudioServer(path, args.android_host_uid, args.playback_sink,
                         args.capture_source)
    os.chmod(path, 0o666)
    print('AaaS audio bridge ready (S16_LE, bounded sessions, UID checked)', flush=True)

    def stop(_signum, _frame):
        server.stop_event.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        try:
            if stat.S_ISSOCK(path.lstat().st_mode):
                path.unlink()
        except FileNotFoundError:
            pass
        print('AaaS audio bridge stopped', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
