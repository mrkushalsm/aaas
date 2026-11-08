from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_graphics


class RenderNodeDiscoveryTests(unittest.TestCase):
    def test_selects_first_accessible_render_node_not_fixed_numeric_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'dri'
            root.mkdir()
            nodes = [root / 'renderD128', root / 'renderD131']
            for node in nodes:
                node.touch()
            with patch.object(Path, 'is_char_device', return_value=True), \
                    patch.object(aaas_graphics.os, 'access', side_effect=lambda p, mode: p.name == 'renderD131'):
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
