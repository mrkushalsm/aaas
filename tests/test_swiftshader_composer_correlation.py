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
    def test_memory_retirement_requires_draw_completion_and_prior_sync(self):
        events = [
            {'event': 'AAAS_AHB_VK_IMPORT', 'memory_id': 77},
            {'event': 'AAAS_DESCRIPTOR_IMAGE', 'set_id': 4, 'memory_id': 77},
            {'event': 'AAAS_DRAW_ENQUEUE', 'submit_id': 9, 'draw_id': 2,
             'set1_id': 4},
            {'event': 'AAAS_DRAW_COMPLETE', 'submit_id': 9, 'draw_id': 2},
            {'event': 'AAAS_QUEUE_RENDERER_SYNC_DONE', 'submit_id': 9},
            {'event': 'AAAS_AHB_VK_REF_RELEASE_END', 'memory_id': 77},
        ]
        result = TRACE.correlate_memory_retirement(events)
        row = result['resources'][0]
        self.assertEqual(row['classification'], 'OBSERVED_DRAW_SYNC_RELEASE_ORDER')
        self.assertEqual(row['linked_draw_count'], 1)

    def test_memory_retirement_flags_release_before_completion(self):
        events = [
            {'event': 'AAAS_AHB_VK_IMPORT', 'memory_id': 77},
            {'event': 'AAAS_DESCRIPTOR_IMAGE', 'set_id': 4, 'memory_id': 77},
            {'event': 'AAAS_DRAW_ENQUEUE', 'submit_id': 9, 'draw_id': 2,
             'set0_id': 4},
            {'event': 'AAAS_AHB_VK_REF_RELEASE_END', 'memory_id': 77},
            {'event': 'AAAS_DRAW_COMPLETE', 'submit_id': 9, 'draw_id': 2},
            {'event': 'AAAS_QUEUE_RENDERER_SYNC_DONE', 'submit_id': 9},
        ]
        row = TRACE.correlate_memory_retirement(events)['resources'][0]
        self.assertEqual(row['classification'], 'RELEASE_WITH_INCOMPLETE_DRAW')

    def test_memory_retirement_keeps_missing_release_unclassified(self):
        events = [
            {'event': 'AAAS_AHB_VK_IMPORT', 'memory_id': 77},
            {'event': 'AAAS_DESCRIPTOR_IMAGE', 'set_id': 4, 'memory_id': 77},
            {'event': 'AAAS_DRAW_ENQUEUE', 'submit_id': 9, 'draw_id': 2,
             'set1_id': 4},
            {'event': 'AAAS_DRAW_COMPLETE', 'submit_id': 9, 'draw_id': 2},
            {'event': 'AAAS_QUEUE_RENDERER_SYNC_DONE', 'submit_id': 9},
        ]
        row = TRACE.correlate_memory_retirement(events)['resources'][0]
        self.assertEqual(row['classification'], 'NO_EXPLICIT_RELEASE_OBSERVED')

    def test_read_draws_includes_descriptor_and_release_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace = Path(temporary) / 'trace.log'
            trace.write_text(
                'mono_ns=1 pid=3 AAAS_DESCRIPTOR_IMAGE set_id=4 memory_id=77\n'
                'mono_ns=2 pid=3 AAAS_AHB_VK_REF_RELEASE_END memory_id=77\n')
            self.assertEqual([e['event'] for e in TRACE.read_draws(trace)],
                             ['AAAS_DESCRIPTOR_IMAGE',
                              'AAAS_AHB_VK_REF_RELEASE_END'])

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
