import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WaylandPresenterSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "experiments/m1a/src/gpu_presenter.c").read_text()

    def test_android_display_surface_is_declared_opaque_on_configure(self):
        helper_start = self.source.index("static void set_surface_opaque_region(")
        helper_end = self.source.index("static void xdg_surface_configure(", helper_start)
        helper = self.source[helper_start:helper_end]
        self.assertIn("wl_region_add(region, 0, 0, (int32_t)width, (int32_t)height)", helper)
        self.assertIn("wl_surface_set_opaque_region(a->surface, region)", helper)
        configure_start = self.source.index("static void xdg_surface_configure(")
        configure_end = self.source.index("static const struct xdg_surface_listener", configure_start)
        configure = self.source[configure_start:configure_end]
        self.assertIn("set_surface_opaque_region(a, w, h)", configure)

    def test_explicit_sync_release_waits_for_compositor_timeline(self):
        release_start = self.source.index("static void buffer_released(")
        release_end = self.source.index("static const struct wl_buffer_listener", release_start)
        release = self.source[release_start:release_end]
        self.assertIn("syncobj_timeline_wait", release)
        self.assertIn("buffer_release_waiting_for_timeline", release)
        self.assertIn("return;", release)
        self.assertIn("finalize_buffer_release(s,", release)
        self.assertIn("s->release_timeline_handle != 0", release)

        finalize_start = self.source.index("static void finalize_buffer_release(")
        finalize_end = release_start
        finalize = self.source[finalize_start:finalize_end]
        self.assertIn("aaas_v2_send(a->sock, &m, send_fds, nfds)", finalize)
        self.assertIn("timeline_signaled", finalize)

        timeline_start = self.source.index("static void check_release_timelines(")
        timeline_end = self.source.index("static void pres_sync_output(", timeline_start)
        timeline = self.source[timeline_start:timeline_end]
        self.assertIn("syncobj_timeline_wait", timeline)
        self.assertIn("finalize_buffer_release(s, true)", timeline)


if __name__ == "__main__":
    unittest.main()
