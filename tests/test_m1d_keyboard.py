import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class M1DKeyboardSourceContractTests(unittest.TestCase):
    def test_keyboard_protocol_is_separate_from_pointer_v1(self):
        header = (ROOT / "experiments/m1a/src/input_v1.h").read_text()
        self.assertIn("AAAS_INPUT_VERSION 1u", header)
        self.assertIn("AAAS_INPUT_KEYBOARD_VERSION 2u", header)
        self.assertIn("sizeof(aaas_input_keyboard_msg)", header)
        self.assertIn("AAAS_INPUT_FLAG_KEYBOARD_V2", header)

    def test_wayland_xkb_and_focus_path_is_surface_scoped(self):
        presenter = (ROOT / "experiments/m1a/src/gpu_presenter.c").read_text()
        self.assertIn("wl_seat_get_keyboard", presenter)
        self.assertIn("wl_keyboard_add_listener", presenter)
        self.assertIn("xkb_keymap_new_from_string", presenter)
        self.assertIn("surface==a->surface", presenter)
        self.assertIn("keyboard_send_focus(a,AAAS_INPUT_FOCUS_LEAVE)", presenter)

    def test_android_16_keyevent_parcel_field_order(self):
        source = (ROOT / "experiments/m1c/input_adapter/inject_binder.cpp").read_text()
        start = source.index("int aaas_binder_inject_key(")
        end = source.index("void aaas_binder_shutdown", start)
        body = source[start:end]
        parcel_start = body.index("data.writeInterfaceToken")
        parcel_end = body.index("data.writeInt32(kInjectInputEventModeWaitForResult)")
        parcel = body[parcel_start:parcel_end]
        fields = [
            "data.writeInt32(1)", "data.writeInt32(2)", "mId",
            "data.writeInt32(-1)", "VIRTUAL_KEYBOARD", "SOURCE_KEYBOARD",
            "display_id", "data.writeInt32(-1)",
            "data.writeInt32(action)",
            "data.writeInt32(keycode)", "data.writeInt32(repeat_count)",
            "data.writeInt32(meta_state)", "data.writeInt32(scancode)",
            "data.writeInt32(0)", "data.writeInt64(down_ns)",
            "data.writeInt64(event_ns)", "writeString16(std::optional<String16>{})",
        ]
        offsets = []
        cursor = -1
        for token in fields:
            cursor = parcel.index(token, cursor + 1)
            offsets.append(cursor)
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn("kInjectInputEventTransaction", body)

    def test_typed_key_injection_stays_in_persistent_adapter(self):
        adapter = (ROOT / "experiments/m1c/input_adapter/aaas_input_adapter.c").read_text()
        self.assertIn("handle_keyboard_message(&st,&packet.keyboard)", adapter)
        self.assertIn("aaas_binder_inject_key", adapter)
        self.assertIn("keyboard_focus_leave", adapter)
        self.assertIn("for(uint32_t k=0;k<768;k++)", adapter)

    def test_android_event_target_display_is_adapter_scoped(self):
        adapter = (ROOT / "experiments/m1c/input_adapter/aaas_input_adapter.c").read_text()
        binder = (ROOT / "experiments/m1c/input_adapter/inject_binder.cpp").read_text()
        self.assertIn("g_android_display_id = display_id", adapter)
        self.assertNotIn("This adapter only supports the AaaS display 0", adapter)
        self.assertIn("g_android_display_id);", adapter)
        self.assertIn("p.writeInt32(display_id);", binder)
        self.assertIn('argv[n++] = (char *)"-d"', adapter)

    def test_presenter_negotiates_android_display_from_broker_file(self):
        cli = (ROOT / "experiments/m1a/src/wayland_host_presenter.c").read_text()
        presenter = (ROOT / "experiments/m1a/src/gpu_presenter.c").read_text()
        self.assertIn("--input-display-id-file", cli)
        self.assertIn("fopen(a->input_display_id_file", presenter)
        self.assertIn(".display_id = a->input_display_id", presenter)
        self.assertIn("a->input_session_id, a->input_display_id", presenter)


if __name__ == "__main__":
    unittest.main()
