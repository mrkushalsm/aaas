import json
from io import StringIO
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaasctl


class AaasControlClientTests(unittest.TestCase):
    def test_stop_app_maps_to_runner_stop_request(self):
        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def sendall(self, payload):
                self.payload = payload

            def recv(self, _size):
                return b'{"ok":true}\n'

        connection = Connection()
        output = StringIO()
        with patch.object(aaasctl, 'active_control_socket', return_value=connection), \
                patch('sys.stdout', output):
            self.assertEqual(aaasctl.main(['stop-app', '2']), 0)
        self.assertEqual(json.loads(connection.payload), {'op': 'stop_app', 'slot': 2})

    def test_finds_only_a_connectable_session_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ipc = root / 'm1b84_session_test' / 'ipc'
            ipc.mkdir(parents=True)
            endpoint = ipc / 'aaas-control.sock'
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(endpoint))
            listener.listen(1)
            with patch.object(aaasctl, 'TMP', root):
                connection = aaasctl.active_control_socket()
            try:
                connection.sendall(b'{"op":"list"}\n')
                accepted, _ = listener.accept()
                with accepted:
                    accepted.settimeout(2)
                    self.assertEqual(accepted.recv(128), b'{"op":"list"}\n')
                    accepted.sendall(b'{"ok":true,"windows":[]}\n')
                self.assertEqual(json.loads(connection.recv(128)),
                                 {'ok': True, 'windows': []})
            finally:
                connection.close()
                listener.close()

    def test_ignores_stale_unconnectable_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            endpoint = Path(directory) / 'm1b84_session_stale' / 'ipc' / 'aaas-control.sock'
            endpoint.parent.mkdir(parents=True)
            endpoint.touch()
            with patch.object(aaasctl, 'TMP', endpoint.parents[2]):
                with self.assertRaisesRegex(RuntimeError, 'no active'):
                    aaasctl.active_control_socket()


if __name__ == '__main__':
    unittest.main()
