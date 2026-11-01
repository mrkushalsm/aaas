import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WaylandPresenterSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "experiments/m1a/src/gpu_presenter.c").read_text()

    def test_android_display_surface_is_declared_opaque_on_configure(self):
        helper_start = self.source.index("static void set_surface_opaque_region(")
        helper_end = self.source.index("static bool apply_window_configure(", helper_start)
        helper = self.source[helper_start:helper_end]
        self.assertIn("wl_region_add(region, 0, 0, (int32_t)width, (int32_t)height)", helper)
        self.assertIn("wl_surface_set_opaque_region(a->surface, region)", helper)
        configure_start = self.source.index("static void decor_configure(")
        configure_end = self.source.index("static void decor_close(", configure_start)
        configure = self.source[configure_start:configure_end]
        self.assertIn("apply_window_configure(a, w, h", configure)
        self.assertIn("libdecor_frame_commit(frame, decor_state, configuration)", configure)

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

    def test_teardown_distinguishes_release_from_invalidated_ownership(self):
        drain_start = self.source.index("static void drain_wayland_buffers(")
        drain_end = self.source.index("static void pres_sync_output(", drain_start)
        drain = self.source[drain_start:drain_end]
        self.assertIn("1500000000ULL", drain)
        self.assertIn("wl_surface_attach(a->surface, NULL", drain)
        self.assertIn("check_release_timelines(a)", drain)
        self.assertIn('"buffer_teardown_invalidated"', drain)
        self.assertIn("a->teardown_invalidated++", drain)
        self.assertNotIn("a->released++", drain)

        teardown = self.source.index("drain_wayland_buffers(&app)")
        close_message = self.source.index(".type = AAAS_V2_CLOSE", teardown)
        self.assertLess(teardown, close_message)

    def test_input_teardown_destroys_keyboard_before_releasing_xkb_state(self):
        teardown_start = self.source.index("static void input_teardown(")
        teardown_end = self.source.index("int aaas_run_gpu_presenter(", teardown_start)
        teardown = self.source[teardown_start:teardown_end]
        self.assertLess(teardown.index("destroy_keyboard(a)"),
                        teardown.index("xkb_state_unref(a->xkb_state)"))
        self.assertIn("a->xkb_state = NULL", teardown)
        self.assertIn("a->xkb_keymap = NULL", teardown)
        run = self.source[teardown_end:]
        self.assertIn("input_teardown(&app);\n    drain_wayland_buffers(&app);", run)

    def test_resize_keeps_wayland_surface_geometry_during_android_rebuild(self):
        configure_start = self.source.index("static void decor_configure(")
        configure_end = self.source.index("static void decor_close(", configure_start)
        configure = self.source[configure_start:configure_end]
        geometry = self.source[self.source.index("static bool apply_window_configure("):
                               self.source.index("static void request_android_resize(")]
        self.assertIn("wp_viewport_set_destination(a->viewport", geometry)
        self.assertIn("libdecor_frame_commit(frame, decor_state, configuration)", configure)
        self.assertLess(configure.index("libdecor_frame_commit"),
                        configure.index("schedule_android_resize"))
        self.assertNotIn("request_android_resize", configure)
        self.assertIn("aaas_resize_take_due", self.source)
        self.assertIn("flush_scheduled_android_resize(&app)", self.source)
        self.assertIn('strcmp(iface, "wp_viewporter")', self.source)

    def test_libdecor_owns_one_xdg_role_and_uses_standard_window_state(self):
        self.assertIn("libdecor_decorate(app.decor_context, app.surface", self.source)
        self.assertNotIn("xdg_wm_base_get_xdg_surface", self.source)
        self.assertIn("aaas_window_state_update", self.source)
        self.assertIn("libdecor_frame_set_fullscreen", self.source)
        self.assertIn("LIBDECOR_ACTION_MINIMIZE", self.source)
        self.assertIn("libdecor_frame_unref(app.decor_frame)", self.source)
        self.assertGreaterEqual(self.source.count("libdecor_get_fd("), 3)
        self.assertIn("libdecor_dispatch(app.decor_context, 0)", self.source)
        makefile = (ROOT / "experiments/m1a/Makefile").read_text()
        self.assertIn("PRESENTER_PKGS = $(PKGS) libdecor-0", makefile)

    def test_resize_records_android_source_buffer_dimensions(self):
        self.assertIn('log_presenter_event("source_frame_dimensions"', self.source)
        self.assertIn('matches_configure', self.source)
        self.assertIn('last_source_frame_w', self.source)
        self.assertIn('last_source_frame_config_gen', self.source)


if __name__ == "__main__":
    unittest.main()
