import argparse
import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_aaas.py'
SPEC = importlib.util.spec_from_file_location('aaas_run_aaas', SCRIPT)
RUN_AAAS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN_AAAS)


class InitialWindowGeometryTests(unittest.TestCase):
    def test_default_geometry_is_comfortable_portrait(self):
        self.assertEqual(RUN_AAAS.initial_window_size('portrait'), (420, 740))

    def test_default_landscape_swaps_phone_profile(self):
        self.assertEqual(RUN_AAAS.initial_window_size('landscape'), (740, 420))

    def test_user_requested_geometry_is_preserved(self):
        self.assertEqual(RUN_AAAS.initial_window_size('portrait', (500, 820)),
                         (500, 820))

    def test_window_size_parser_rejects_malformed_or_unsafe_values(self):
        for value in ('420', '420xabc', '20x740', '420x3000'):
            with self.subTest(value=value), self.assertRaises(
                    argparse.ArgumentTypeError):
                RUN_AAAS.parse_window_size(value)

    def test_density_bounds(self):
        self.assertEqual(RUN_AAAS.parse_display_density('240'), 240)
        for value in ('x', '71', '1001'):
            with self.subTest(value=value), self.assertRaises(
                    argparse.ArgumentTypeError):
                RUN_AAAS.parse_display_density(value)

    def test_android_source_size_is_independent_from_window_size(self):
        self.assertEqual(RUN_AAAS.initial_display_size('portrait'), (720, 1280))
        self.assertEqual(RUN_AAAS.initial_display_size('landscape'), (1280, 720))
        self.assertEqual(RUN_AAAS.initial_display_size('portrait', (960, 578)),
                         (960, 578))

    def test_display_size_parser_rejects_malformed_or_unsafe_values(self):
        self.assertEqual(RUN_AAAS.parse_display_size('720x1280'), (720, 1280))
        for value in ('720', '720xy', '20x1280', '720x3000'):
            with self.subTest(value=value), self.assertRaises(
                    argparse.ArgumentTypeError):
                RUN_AAAS.parse_display_size(value)


if __name__ == '__main__':
    unittest.main()
