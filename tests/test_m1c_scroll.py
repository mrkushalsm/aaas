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
        self.assertIn('const char *input_source = "mouse";', self.adapter)
        self.assertIn('origin_source = source == AAAS_SOURCE_TOUCHPAD ? "touchpad" : "mouse"', self.adapter)

    def test_android16_input_source_precedes_display_option(self):
        start = self.adapter.index("static int inject_cmd_scroll(")
        end = self.adapter.index("static int inject_event(", start)
        builder = self.adapter[start:end]
        source = builder.index('argv[n++] = (char *)input_source;')
        display_option = builder.index('argv[n++] = (char *)"-d";')
        display = builder.index('argv[n++] = display;')
        command = builder.index('argv[n++] = (char *)"scroll";')
        self.assertLess(source, display_option)
        self.assertLess(display_option, display)
        self.assertLess(display, command)

    def test_unpressed_host_motion_does_not_inject_android_hover_stream(self):
        motion_start = self.adapter.index("case AAAS_INPUT_MOTION: {")
        hover_start = self.adapter.index("case AAAS_INPUT_HOVER: {")
        scroll_start = self.adapter.index("case AAAS_INPUT_SCROLL: {")
        motion = self.adapter[motion_start:hover_start]
        hover = self.adapter[hover_start:scroll_start]
        focus_start = self.adapter.index("case AAAS_INPUT_FOCUS: {")
        shutdown_start = self.adapter.index("case AAAS_INPUT_SHUTDOWN: {")
        focus = self.adapter[focus_start:shutdown_start]
        self.assertIn("if (st->pressed_buttons)", motion)
        self.assertNotIn("AAAS_ACTION_HOVER_", motion)
        self.assertNotIn("inject_request", hover)
        self.assertNotIn("AAAS_ACTION_HOVER_", focus)

    def test_unpressed_pointer_motion_stays_out_of_android_input_socket(self):
        presenter = (ROOT / "experiments/m1a/src/gpu_presenter.c").read_text()
        motion_start = presenter.index("static void pointer_motion(")
        motion_end = presenter.index("static void pointer_button(", motion_start)
        motion = presenter[motion_start:motion_end]

        self.assertIn("if (a->pressed_buttons)", motion)
        self.assertIn("input_send_packet(a, AAAS_INPUT_MOTION", motion)

    def test_adjacent_scroll_sources_are_coalesced_without_reordering(self):
        burst_start = self.adapter.index("static int handle_scroll_burst(")
        burst_end = self.adapter.index("static int inject_request(", burst_start)
        burst = self.adapter[burst_start:burst_end]
        self.assertIn("AAAS_INPUT_AXIS_SOURCE_FINGER", burst)
        self.assertIn("AAAS_INPUT_AXIS_SOURCE_CONTINUOUS", burst)
        self.assertIn("AAAS_INPUT_AXIS_SOURCE_WHEEL_TILT", burst)
        self.assertIn("peek.button != source", burst)
        self.assertIn("peek.display_generation != generation", burst)
        self.assertIn("peek.focus_generation != focus_generation", burst)
        self.assertIn("while (count < 128)", burst)
        self.assertIn("touchpad ? AAAS_SOURCE_TOUCHPAD : AAAS_SOURCE_MOUSE", burst)
        self.assertIn("message.type == AAAS_INPUT_SCROLL", self.adapter)
        self.assertIn("usleep(1000)", self.adapter)

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
