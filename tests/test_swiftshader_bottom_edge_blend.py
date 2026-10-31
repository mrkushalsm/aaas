import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SwiftShaderBottomEdgeBlendTests(unittest.TestCase):
    def test_draw_data_carries_color_attachment_height(self):
        patch = (ROOT / 'experiments/m1e/patches/'
                 'swiftshader_coherent_diagnostic.patch').read_text()
        self.assertIn('int colorBufferHeight[MAX_COLOR_BUFFERS];', patch)
        self.assertIn('view->getMipLevelExtent(0, VK_IMAGE_ASPECT_COLOR_BIT).height', patch)

    def test_paired_color_reads_clamp_at_odd_height_edge(self):
        patch = (ROOT / 'experiments/m1e/patches/'
                 'swiftshader_coherent_diagnostic.patch').read_text()
        self.assertIn('Int height = *Pointer<Int>(data + OFFSET(DrawData, colorBufferHeight[index]));', patch)
        self.assertGreaterEqual(patch.count('pitchB = IfThenElse(y + 1 < height, pitchB, Int(0));'), 2)
        self.assertIn('readPixel(index, cBuffer, x, y, color);', patch)
        self.assertIn('Int validRows = IfThenElse(y + 1 < height, Int(0xF), Int(0x3));', patch)
        self.assertIn('Int safeCMask = cMask & validRows;', patch)
        self.assertIn('writeColor(index, buffer, x, y, color,', patch)


if __name__ == '__main__':
    unittest.main()
