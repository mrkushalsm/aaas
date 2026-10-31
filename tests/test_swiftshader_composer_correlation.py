import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = (Path(__file__).resolve().parents[1] /
          'scripts/correlate_swiftshader_composer_buffers.py')
SPEC = importlib.util.spec_from_file_location('swiftshader_composer_correlation', SCRIPT)
TRACE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRACE)


class BufferCorrelationTests(unittest.TestCase):
    def test_joins_only_by_allocator_identity_and_reports_generation(self):
        composer = [{
            'display': 3, 'slot': 1, 'generation': 8, 'buffer_id': 177,
            'width': 960, 'height': 565, 'stride': 960,
            'dma_dev': 7, 'dma_ino': 99,
        }]
        swiftshader = [{
            'pid': 222, 'mono_ns': 500, 'id': 40, 'buffer_id': 177,
            'dma_dev': 7, 'dma_ino': 99, 'width': 960, 'height': 565,
            'stride': 960, 'base': '0x1000',
        }]
        result = TRACE.correlate(swiftshader, composer)
        match = result['matches'][0]
        self.assertEqual(match['composer']['display'], 3)
        self.assertEqual(match['composer']['generation'], 8)
        self.assertTrue(match['stable_buffer_id_match'])
        self.assertTrue(match['fd_identity_match'])
        self.assertTrue(match['geometry_match'])

    def test_dimensions_and_fd_identity_do_not_replace_stable_id(self):
        composer = [{
            'display': 3, 'slot': 1, 'generation': 8, 'buffer_id': 177,
            'width': 960, 'height': 565, 'stride': 960,
            'dma_dev': 7, 'dma_ino': 99,
        }]
        swiftshader = [{
            'buffer_id': 178, 'dma_dev': 7, 'dma_ino': 99,
            'width': 960, 'height': 565, 'stride': 960,
        }]
        result = TRACE.correlate(swiftshader, composer)
        self.assertEqual(result['matches'], [])
        self.assertEqual(len(result['unmatched_swiftshader']), 1)

    def test_parses_runtime_records_without_inventing_missing_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            swift = root / 'swift.log'
            composer = root / 'composer.log'
            swift.write_text(
                'mono_ns=42 pid=222 tid=9 AAAS_AHB_VK_IMPORT id=4 '
                'buffer_id=177 dma_dev=7 dma_ino=99 width=960 height=565 '
                'stride=960 base=0x1000\n')
            composer.write_text(
                'virtual output frame display=3 slot=1 generation=8 '
                'buffer_id=177 width=960 height=565 stride=960 dma_dev=7 '
                'dma_ino=99 command=2\n')
            result = TRACE.correlate(TRACE.read_swiftshader(swift),
                                     TRACE.read_composer(composer))
            self.assertEqual(len(result['matches']), 1)
            self.assertTrue(result['matches'][0]['fd_identity_match'])

    def test_links_draw_attachment_memory_to_jit_and_composer_generation(self):
        events = [
            {'event': 'AAAS_JIT_ENTRY', 'address': '0xabc',
             'name': 'PixelRoutine_test', 'id': 7},
            {'event': 'AAAS_DRAW_TARGET', 'submit_id': 3, 'draw_id': 9,
             'pipeline_id': 12, 'view_id': 5, 'image_id': 6,
             'memory_id': 44, 'base': '0x1000'},
            {'event': 'AAAS_DRAW_WORK_BEGIN', 'submit_id': 3, 'draw_id': 9,
             'pipeline_id': 12, 'pixel_routine': '0xabc'},
            {'event': 'AAAS_DRAW_COMPLETE', 'submit_id': 3, 'draw_id': 9},
        ]
        imported = [{'memory_id': 44, 'buffer_id': 177, 'base': '0x1000'}]
        frames = [{'display': 101, 'slot': 0, 'generation': 24,
                   'buffer_id': 177, 'width': 960, 'height': 565,
                   'stride': 960, 'dma_dev': 7, 'dma_ino': 99}]
        result = TRACE.correlate_draw_resources(events, imported, frames)
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row['memory_id'], 44)
        self.assertEqual(row['ahardwarebuffer']['buffer_id'], 177)
        self.assertEqual(row['composer_frames'][0]['generation'], 24)
        self.assertEqual(row['jit_routine_matches'][0]['id'], 7)
        self.assertTrue(row['draw_completion_observed'])


if __name__ == '__main__':
    unittest.main()
