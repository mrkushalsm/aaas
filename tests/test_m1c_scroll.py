import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class M1CScrollRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = (ROOT / "experiments/m1c/input_adapter/aaas_input_adapter.c").read_text()
        cls.presenter = (ROOT / "experiments/m1a/src/gpu_presenter.c").read_text()

    def test_scroll_uses_android_framework_motion_event_builder(self):
        route = self.adapter.index("if (action == AAAS_ACTION_SCROLL)")
        binder_probe = self.adapter.index("if (g_backend == INPUT_BACKEND_AUTO &&", route)
        self.assertLess(route, binder_probe)
        self.assertIn('"scroll"', self.adapter)
        self.assertIn('"VSCROLL,%.6g"', self.adapter)
        self.assertIn('"HSCROLL,%.6g"', self.adapter)
        self.assertIn("input_source = source == AAAS_SOURCE_TOUCHPAD ? \"touchpad\" : \"mouse\"", self.adapter)

    def test_wayland_axis_sources_are_coalesced_without_double_counting(self):
        flush_start = self.presenter.index("static void input_axis_flush(")
        flush_end = self.presenter.index("static void pointer_frame(", flush_start)
        flush = self.presenter[flush_start:flush_end]
        value120 = flush.index("if ((a->axis_value120_mask & 1u)")
        discrete = flush.index("} else if ((a->axis_discrete_mask & 1u)", value120)
        smooth = flush.index("} else if (a->axis_seen_mask & 1u)", discrete)
        self.assertLess(value120, discrete)
        self.assertLess(discrete, smooth)
        self.assertIn("input_send_packet(a, AAAS_INPUT_SCROLL", flush)
        self.assertIn("input_axis_clear(a);", flush)


if __name__ == "__main__":
    unittest.main()
