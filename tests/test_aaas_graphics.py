from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_graphics


class RenderNodeDiscoveryTests(unittest.TestCase):
    def _nodes(self, root):
        nodes = [root / 'renderD128', root / 'renderD129']
        for node in nodes:
            node.touch()
        return nodes

    def _mock_nodes(self):
        return patch.object(Path, 'is_char_device', return_value=True), \
            patch.object(aaas_graphics.os, 'access', return_value=True)

    def test_selects_wayland_compositor_main_render_node(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'dri'
            root.mkdir()
            nodes = self._nodes(root)
            with self._mock_nodes()[0], self._mock_nodes()[1], \
                    patch.object(aaas_graphics.shutil, 'which', return_value='/usr/bin/wayland-info'), \
                    patch.object(aaas_graphics.subprocess, 'run', return_value=
                                 aaas_graphics.subprocess.CompletedProcess(
                                     ['wayland-info'], 0,
                                     stdout="main device: 0xE281 (/dev/dri/card2 or "
                                           "/dev/dri/renderD129)\n", stderr='')):
                self.assertEqual(aaas_graphics.discover_render_node(root, env={}), nodes[1])

    def test_multiple_devices_fail_closed_when_compositor_device_is_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'dri'
            root.mkdir()
            self._nodes(root)
            with self._mock_nodes()[0], self._mock_nodes()[1], \
                    patch.object(aaas_graphics.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(aaas_graphics.GraphicsDeviceError,
                                            'multiple DRM render nodes'):
                    aaas_graphics.discover_render_node(root, env={})

    def test_single_available_device_is_safe_fallback_without_wayland_info(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'dri'
            root.mkdir()
            nodes = self._nodes(root)
            with patch.object(Path, 'is_char_device', return_value=True), \
                    patch.object(aaas_graphics.os, 'access',
                                 side_effect=lambda p, mode: p.name == 'renderD129'), \
                    patch.object(aaas_graphics.shutil, 'which', return_value=None):
                self.assertEqual(aaas_graphics.discover_render_node(root, env={}), nodes[1])

    def test_rejects_invalid_override_instead_of_silently_using_another_device(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'dri'
            root.mkdir()
            fallback = root / 'renderD128'
            fallback.touch()
            with patch.object(Path, 'is_char_device', return_value=True), \
                    patch.object(aaas_graphics.os, 'access', return_value=True):
                with self.assertRaisesRegex(aaas_graphics.GraphicsDeviceError,
                                            'AAAS_DRM_RENDER_NODE'):
                    aaas_graphics.discover_render_node(root,
                        env={'AAAS_DRM_RENDER_NODE': str(root / 'missing')})

    def test_no_device_is_an_explicit_error(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(aaas_graphics.GraphicsDeviceError,
                                        'no accessible DRM render node'):
                aaas_graphics.discover_render_node(td, env={})


if __name__ == '__main__':
    unittest.main()
