#!/usr/bin/env python3
"""Session-owned, UID-authenticated Android PCM bridge to pipewire-pulse."""
import argparse
import ctypes
import ctypes.util
import os
import select
import signal
import socket
import socketserver
import stat
import struct
import sys
import threading
import time
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


class PulseCapture:
    """Cancellable Pulse capture using a pumped asynchronous libpulse context.

    The simple API's ``pa_simple_read`` can wait indefinitely if its server
    vanishes. This adapter owns a nonblocking mainloop in the client worker so
    context/stream failure and session cancellation are observed while waiting
    for bounded PCM fragments.
    """
    CONTEXT_READY = 4
    CONTEXT_FAILED = 5
    CONTEXT_TERMINATED = 6
    STREAM_READY = 2
    STREAM_FAILED = 3
    STREAM_TERMINATED = 4
    NO_AUTOSPAWN = 0x0001
    ADJUST_LATENCY = 0x2000
    UINT32_MAX = 0xffffffff
    READ_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_size_t,
                                    ctypes.c_void_p)
    CONNECT_TIMEOUT = 3.0
    READ_TIMEOUT = 1.0
    POLL_INTERVAL = 0.005

    def __init__(self, rate, channels, device=None, *, stop_event=None,
                 library=None):
        library = library or ctypes.util.find_library('pulse')
        if not library:
            raise RuntimeError('libpulse is unavailable')
        self.lib = ctypes.CDLL(library)
        self.stop_event = stop_event or threading.Event()
        self.mainloop = self.context = self.stream = None
        self.pending = bytearray()
        self.data_ready = threading.Event()
        self._read_callback = self.READ_CALLBACK(self._on_readable)
        self.spec = PaSampleSpec(3, rate, channels)
        frame_size = channels * 2
        fragment_size = max(frame_size, rate // 50 * frame_size)
        self.attr = (ctypes.c_uint32 * 5)(
            min(MAX_BUFFER, fragment_size * 4),
            self.UINT32_MAX, self.UINT32_MAX, self.UINT32_MAX,
            fragment_size)
        self._bind()
        try:
            self._open(device)
        except Exception:
            self.close()
            raise

    def _bind(self):
        p = ctypes.c_void_p
        self.lib.pa_mainloop_new.restype = p
        self.lib.pa_mainloop_get_api.argtypes = [p]
        self.lib.pa_mainloop_get_api.restype = p
        self.lib.pa_mainloop_iterate.argtypes = [p, ctypes.c_int,
                                                 ctypes.POINTER(ctypes.c_int)]
        self.lib.pa_mainloop_iterate.restype = ctypes.c_int
        self.lib.pa_mainloop_free.argtypes = [p]
        self.lib.pa_context_new.argtypes = [p, ctypes.c_char_p]
        self.lib.pa_context_new.restype = p
        self.lib.pa_context_connect.argtypes = [p, ctypes.c_char_p, ctypes.c_int, p]
        self.lib.pa_context_connect.restype = ctypes.c_int
        self.lib.pa_context_get_state.argtypes = [p]
        self.lib.pa_context_get_state.restype = ctypes.c_int
        self.lib.pa_context_errno.argtypes = [p]
        self.lib.pa_context_errno.restype = ctypes.c_int
        self.lib.pa_context_disconnect.argtypes = [p]
        self.lib.pa_context_unref.argtypes = [p]
        self.lib.pa_stream_new.argtypes = [p, ctypes.c_char_p,
                                           ctypes.POINTER(PaSampleSpec), p]
        self.lib.pa_stream_new.restype = p
        self.lib.pa_stream_get_state.argtypes = [p]
        self.lib.pa_stream_get_state.restype = ctypes.c_int
        self.lib.pa_stream_connect_record.argtypes = [p, ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_int]
        self.lib.pa_stream_connect_record.restype = ctypes.c_int
        self.lib.pa_stream_set_read_callback.argtypes = [p, self.READ_CALLBACK, p]
        self.lib.pa_stream_peek.argtypes = [p, ctypes.POINTER(p),
                                            ctypes.POINTER(ctypes.c_size_t)]
        self.lib.pa_stream_peek.restype = ctypes.c_int
        self.lib.pa_stream_drop.argtypes = [p]
        self.lib.pa_stream_drop.restype = ctypes.c_int
        self.lib.pa_stream_disconnect.argtypes = [p]
        self.lib.pa_stream_unref.argtypes = [p]

    def _iterate(self):
        result = self.lib.pa_mainloop_iterate(self.mainloop, 0, None)
        if result < 0:
            raise RuntimeError('Pulse capture mainloop failed')

    def _check(self):
        if self.stop_event.is_set():
            raise RuntimeError('Pulse capture cancelled by session shutdown')
        if self.context and self.lib.pa_context_get_state(self.context) in (
                self.CONTEXT_FAILED, self.CONTEXT_TERMINATED):
            code = self.lib.pa_context_errno(self.context)
            raise RuntimeError(f'Pulse capture context disconnected (code {code})')
        if self.stream and self.lib.pa_stream_get_state(self.stream) in (
                self.STREAM_FAILED, self.STREAM_TERMINATED):
            code = self.lib.pa_context_errno(self.context)
            raise RuntimeError(f'Pulse capture stream disconnected (code {code})')

    def _on_readable(self, _stream, _available, _userdata):
        self.data_ready.set()

    def _wait_state(self, getter, ready, timeout, description):
        deadline = time.monotonic() + timeout
        while True:
            self._iterate()
            self._check()
            if getter() == ready:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(f'Pulse {description} timed out')
            time.sleep(self.POLL_INTERVAL)

    def _open(self, device):
        self.mainloop = self.lib.pa_mainloop_new()
        if not self.mainloop:
            raise RuntimeError('Pulse mainloop allocation failed')
        api = self.lib.pa_mainloop_get_api(self.mainloop)
        self.context = self.lib.pa_context_new(api, b'AaaS Android Audio')
        if not self.context:
            raise RuntimeError('Pulse context allocation failed')
        pulse_server = os.environ.get('PULSE_SERVER')
        if not pulse_server or pulse_server == 'default':
            pulse_server = None
        server_address = pulse_server.encode('utf-8') if pulse_server else None
        if self.lib.pa_context_connect(self.context, server_address,
                                       self.NO_AUTOSPAWN, None) < 0:
            code = self.lib.pa_context_errno(self.context)
            raise RuntimeError(f'Pulse capture context connect failed (code {code})')
        self._wait_state(lambda: self.lib.pa_context_get_state(self.context),
                         self.CONTEXT_READY, self.CONNECT_TIMEOUT, 'context connect')
        self.stream = self.lib.pa_stream_new(self.context,
            b'AaaS Android microphone', ctypes.byref(self.spec), None)
        if not self.stream:
            raise RuntimeError('Pulse capture stream allocation failed')
        self.lib.pa_stream_set_read_callback(self.stream, self._read_callback, None)
        selected = device.encode('utf-8') if device else None
        if self.lib.pa_stream_connect_record(self.stream, selected, self.attr,
                                              self.ADJUST_LATENCY) < 0:
            raise RuntimeError('Pulse capture stream connect failed')
        self._wait_state(lambda: self.lib.pa_stream_get_state(self.stream),
                         self.STREAM_READY, self.CONNECT_TIMEOUT, 'stream connect')

    def read(self, size):
        if not 0 < size <= MAX_BUFFER:
            raise ValueError('Pulse capture read size is out of bounds')
        deadline = time.monotonic() + self.READ_TIMEOUT
        while len(self.pending) < size:
            self._iterate()
            self._check()
            if not self.data_ready.is_set():
                if time.monotonic() >= deadline:
                    raise TimeoutError('Pulse capture produced no data before deadline')
                time.sleep(self.POLL_INTERVAL)
                continue
            self.data_ready.clear()
            data = ctypes.c_void_p()
            length = ctypes.c_size_t()
            if self.lib.pa_stream_peek(self.stream, ctypes.byref(data),
                                       ctypes.byref(length)) < 0:
                self._check()
                raise RuntimeError('Pulse capture buffer peek failed')
            if length.value:
                if length.value > MAX_BUFFER or len(self.pending) + length.value > MAX_BUFFER:
                    raise RuntimeError('Pulse capture buffer exceeded its bound')
                self.pending.extend(ctypes.string_at(data, length.value)
                                    if data.value else bytes(length.value))
                if self.lib.pa_stream_drop(self.stream) < 0:
                    self._check()
                    raise RuntimeError('Pulse capture buffer drop failed')
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError('Pulse capture produced no data before deadline')
            time.sleep(self.POLL_INTERVAL)
        result = bytes(self.pending[:size])
        del self.pending[:size]
        return result

    def close(self):
        if self.stream:
            try:
                self.lib.pa_stream_disconnect(self.stream)
            except Exception:
                pass
            self.lib.pa_stream_unref(self.stream)
            self.stream = None
        if self.context:
            self.lib.pa_context_disconnect(self.context)
            self.lib.pa_context_unref(self.context)
            self.context = None
        if self.mainloop:
            self.lib.pa_mainloop_free(self.mainloop)
            self.mainloop = None


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
        self.active_workers = 0
        self.active_sockets = set()
        self.worker_slots = threading.BoundedSemaphore(MAX_CLIENTS)
        self.stop_event = threading.Event()
        super().__init__(str(socket_path), AudioHandler)

    def process_request(self, request, client_address):
        if not self.worker_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        with self.client_lock:
            self.active_sockets.add(request)
            self.active_workers += 1
        try:
            super().process_request(request, client_address)
        except Exception:
            with self.client_lock:
                self.active_sockets.discard(request)
                self.active_workers -= 1
            self.worker_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.client_lock:
                self.active_sockets.discard(request)
                self.active_workers -= 1
            self.worker_slots.release()

    def request_stop(self):
        self.stop_event.set()
        with self.client_lock:
            clients = tuple(self.active_sockets)
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

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
            detail = str(error).replace('\n', ' ')[:160]
            print(f'audio client rejected ({type(error).__name__}): {detail}',
                  flush=True)
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
        pulse = (PulseSimple(direction, rate, channels, device=device)
                 if direction == PLAYBACK else
                 PulseCapture(rate, channels, device=device,
                              stop_event=self.server.stop_event))
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
                    readable, _, _ = select.select([conn], [], [], 0)
                    if readable:
                        if not conn.recv(1, socket.MSG_PEEK):
                            raise OSError('capture peer disconnected')
                        raise ValueError('unexpected data on capture stream')
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
    pulse_server = os.environ.get('PULSE_SERVER', 'default')
    print('AaaS audio bridge ready (S16_LE, bounded sessions, UID checked; '
          f'Pulse server={pulse_server})', flush=True)

    def stop(_signum, _frame):
        server.request_stop()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.request_stop()
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
