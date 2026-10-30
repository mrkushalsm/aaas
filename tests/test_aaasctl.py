import json
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
