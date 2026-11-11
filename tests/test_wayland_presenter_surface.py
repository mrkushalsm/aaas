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

    def test_implicit_sync_fallback_waits_for_producer_acquire_fence(self):
        wait_start = self.source.index(
            "if (acquire_fence_fd >= 0 &&\n        (!a->syncobj_surface || !a->acquire_timeline))")
        import_start = self.source.index(
            "// The opt-in test backend imports a memfd through core wl_shm.", wait_start)
        fallback = self.source[wait_start:import_start]
        self.assertIn("wait_for_acquire_fence(a, acquire_fence_fd, 2000)", fallback)
        self.assertIn('"implicit_acquire_wait_failed"', fallback)
        self.assertIn('"implicit_acquire_wait_complete"', fallback)
        self.assertIn('"implicit_acquire_timeout"', fallback)
        self.assertIn("m.flags &= ~AAAS_V2_FLAG_EXPLICIT_SYNC", fallback)
        self.assertLess(fallback.index("wait_for_acquire_fence("),
                        fallback.index("implicit_acquire_wait_complete"))
        params_start = self.source.index(
            "params = zwp_linux_dmabuf_v1_create_params", import_start)
        self.assertLess(import_start, params_start)

    def test_staged_buffers_bound_early_copy_credit_and_imports(self):
        policy = (ROOT / "experiments/m1a/src/staging_backpressure.h").read_text()
        native_test = (ROOT / "experiments/m1a/tests/test_staging_backpressure.c").read_text()
        self.assertIn("#define AAAS_STAGING_EARLY_COPY_CREDITS 2u", policy)
        self.assertIn("#define AAAS_STAGING_MAX_IN_FLIGHT 4u", policy)
        self.assertIn("aaas_staging_reserve(", policy)
        self.assertIn("aaas_staging_copy_decide(", policy)
        self.assertIn("aaas_staging_release(", policy)
        self.assertIn("aaas_staging_cancel(", policy)

        start = self.source.index("static void handle_incoming_buffer(")
        end = self.source.index("static void ", start + len("static void handle_incoming_buffer("))
        handler = self.source[start:end]
        self.assertIn("aaas_staging_reserve(", handler)
        self.assertIn("aaas_staging_mark_allocated(", handler)
        self.assertIn("aaas_staging_copy_decide(", handler)
        self.assertIn("aaas_staging_mark_submitted(", handler)
        self.assertIn('"staged_backpressure_limit"', handler)
        self.assertIn('"source_copy_complete_deferred_until_release"', handler)
        self.assertLess(handler.index("aaas_staging_reserve("),
                        handler.index("gbm_bo_create("))
        self.assertLess(handler.index("duplicate_inflight_buffer"),
                        handler.index("staged_backpressure_limit"))
        self.assertIn("actual_releases", self.source)
        self.assertIn("aaas_staging_release(", self.source)
        self.assertIn("aaas_staging_cancel(", self.source)
        self.assertIn("release_frame(&m, four)", native_test)
        self.assertIn("test_stalled_releases_and_preallocation_limit", native_test)
        self.assertIn("cancel_all(&m)", native_test)

    def test_composer_frames_wait_for_the_initial_xdg_configure(self):
        self.assertIn("bool producer_hello_received;", self.source)
        hello = self.source.index("if (m.type == AAAS_V2_HELLO)")
        hello_end = self.source.index("if (m.type != AAAS_V2_BUFFER)", hello)
        self.assertIn("a->producer_hello_received = true;", self.source[hello:hello_end])
        poll_start = self.source.index("struct pollfd p[5] = {")
        poll_end = self.source.index("};", poll_start)
        poll_fds = self.source[poll_start:poll_end]
        self.assertIn("(!app.producer_hello_received || app.configured)", poll_fds)
        self.assertNotIn("if (!a->configured && a->w && a->h)", self.source)

    def test_gbm_staging_integration_producer_models_source_and_release_ownership(self):
        producer = (ROOT / "experiments/m1a/tests/gbm_staging_producer.c").read_text()
        makefile = (ROOT / "experiments/m1a/Makefile").read_text()
        self.assertIn("AAAS_V2_FLAG_COPY_COMPLETE", producer)
        self.assertIn("SOURCE_COUNT 2u", producer)
        self.assertIn("source_busy_count(sources) == SOURCE_COUNT", producer)
        self.assertIn("--probe-cap", producer)
        self.assertIn("actual_wayland_releases", producer)
        self.assertIn("gbm-staging-producer", makefile)

    def test_acquire_fence_wait_pumps_wayland_and_input_events(self):
        start = self.source.index("static int wait_for_acquire_fence(")
        end = self.source.index("static void check_release_timelines(", start)
        wait = self.source[start:end]
        self.assertIn("poll(p, n, wait_ms)", wait)
        self.assertIn("wl_display_flush(a->display)", wait)
        self.assertIn("wayland_events |= POLLOUT", wait)
        self.assertIn("libdecor_dispatch(a->decor_context, 0)", wait)
        self.assertIn("input_adapter_read(a)", wait)
        self.assertIn("input_adapter_accept(a)", wait)
        self.assertIn("check_release_timelines(a)", wait)
        self.assertIn("flush_scheduled_android_resize(a)", wait)
        self.assertIn("ETIMEDOUT", wait)
        self.assertIn("ECANCELED", wait)
        self.assertIn("POLLHUP | POLLERR | POLLNVAL", wait)

    def test_software_shm_backend_is_explicit_and_keeps_dmabuf_default(self):
        self.assertIn("--software-shm-test", (ROOT / "experiments/m1a/src/wayland_host_presenter.c").read_text())
        self.assertIn("app.software_shm_test ? !app.shm : !app.dmabuf", self.source)
        self.assertIn("wl_shm_pool_create_buffer", self.source)
        self.assertIn("if (!a->software_shm_test) {\n        params = zwp_linux_dmabuf_v1_create_params", self.source)
        self.assertIn("!is_memfd", self.source)

    def test_software_shm_teardown_does_not_destroy_absent_dmabuf_proxy(self):
        self.assertIn("if (app.dmabuf) zwp_linux_dmabuf_v1_destroy(app.dmabuf);",
                      self.source)

    def test_isolated_software_harness_masks_host_graphics_devices(self):
        harness = (ROOT / "scripts/test_software_presenter.py").read_text()
        self.assertIn('"--renderer=pixman"', harness)
        self.assertIn('"--tmpfs", "/dev/dri"', harness)
        self.assertIn('"--new-session", "--clearenv"', harness)
        self.assertIn("producer_env = {", harness)
        self.assertIn('"active_kde_socket_passed": False', harness)
        self.assertIn('"presenter_namespace_dev_dri_exposed": False', harness)
        self.assertIn("linux-dmabuf import or GPU synchronization", harness)

    def test_software_producer_waits_for_real_release_before_buffer_reuse(self):
        producer = (ROOT / "experiments/m1a/tests/software_shm_producer.c").read_text()
        self.assertIn("#define BUFFER_COUNT 2u", producer)
        self.assertIn("msg.type != AAAS_V2_RELEASE", producer)
        self.assertIn("buffer->busy = false", producer)
        self.assertIn("max_in_flight=%u", producer)

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

    def test_presenter_reconnect_resumes_broker_resize_generation(self):
        host = (ROOT / "experiments/m1a/src/wayland_host_presenter.c").read_text()
        gpu = (ROOT / "experiments/m1a/src/gpu_presenter.h").read_text()
        self.assertIn("aaas_read_resize_resume_state(resize_request_path)", host)
        helper = (ROOT / "experiments/m1a/src/resize_generation.h").read_text()
        self.assertIn("O_NOFOLLOW", helper)
        self.assertIn("cfg.initial_display_width = resume.width", host)
        self.assertIn("cfg.initial_display_height = resume.height", host)
        self.assertIn("cfg.initial_width = resume.width", host)
        self.assertIn("cfg.initial_height = resume.height", host)
        native_test = (ROOT / "experiments/m1a/tests/test_resize_generation.c").read_text()
        self.assertIn("state.generation == 2 && state.width == 493", native_test)
        self.assertIn("symlink(path, link_path)", native_test)
        self.assertIn("uint32_t initial_generation;", gpu)
        self.assertIn(".gen = config->initial_generation", self.source)

    def test_composer_resize_reconnect_keeps_existing_wayland_toplevel(self):
        host = (ROOT / "experiments/m1a/src/wayland_host_presenter.c").read_text()
        header = (ROOT / "experiments/m1a/src/gpu_presenter.h").read_text()
        self.assertIn(".producer_listen_fd = server_sock", host)
        self.assertIn("int producer_listen_fd;", header)
        reconnect_start = self.source.index(
            "static void producer_disconnected(presenter_app *a) {")
        reconnect_end = self.source.index("static void handle_incoming_buffer(", reconnect_start)
        reconnect = self.source[reconnect_start:reconnect_end]
        self.assertIn("a->awaiting_resize_reconnect", reconnect)
        self.assertIn("producer_disconnected_waiting_for_resize_reconnect", reconnect)
        self.assertNotIn("drain_wayland_buffers", reconnect)
        self.assertIn("producer_reconnected_same_wayland_window", reconnect)
        self.assertIn(".fd = app.producer_listen_fd", self.source)
        self.assertIn("producer_accept_reconnect(&app)", self.source)
        self.assertIn("s->producer_epoch == a->producer_epoch", self.source)
        receive_start = self.source.index("static void handle_incoming_buffer(")
        receive_end = self.source.index("static void ", receive_start + 1)
        receive = self.source[receive_start:receive_end]
        for reset_errno in ("ECONNRESET", "ENOTCONN", "EPIPE"):
            self.assertIn(reset_errno, receive)
        self.assertIn('"invalid_message"', receive)
        self.assertIn("--test-reconnect-on-producer-close", host)

    def test_software_harness_exercises_two_producer_generations_one_window(self):
        harness = (ROOT / "scripts/test_software_presenter.py").read_text()
        producer = (ROOT / "experiments/m1a/tests/software_shm_producer.c").read_text()
        self.assertIn("--resize-reconnect", harness)
        self.assertIn("same_wayland_toplevel", harness)
        self.assertIn("producer_generations", harness)
        self.assertIn("--disconnect-after-send", producer)


if __name__ == "__main__":
    unittest.main()
