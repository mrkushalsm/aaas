#include "inject_binder.h"

#include <cstdint>
#include <limits>
#include <vector>

#include <binder/IBinder.h>
#include <binder/IServiceManager.h>
#include <binder/Parcel.h>
#include <utils/Errors.h>
#include <utils/String16.h>
#include <utils/StrongPointer.h>

using android::IBinder;
using android::IServiceManager;
using android::Parcel;
using android::sp;
using android::String16;
using android::status_t;

namespace {

constexpr uint32_t kInjectInputEventTransaction = 11;
constexpr int32_t kInjectInputEventModeWaitForResult = 1;

sp<IBinder> *g_input_binder = nullptr;
int64_t g_down_time_ns = 0;
int64_t g_last_event_ns = 0;
bool g_hovering = false;
uint32_t g_next_event_id = 1;

void set_axis(uint64_t *bits, unsigned axis) {
    *bits |= UINT64_C(1) << axis;
}

void write_identity_matrix(Parcel &p) {
    p.writeFloat(1.0f);
    p.writeFloat(0.0f);
    p.writeFloat(0.0f);
    p.writeFloat(0.0f);
    p.writeFloat(1.0f);
    p.writeFloat(0.0f);
}

void write_motion_event(Parcel &p, int action, int32_t x, int32_t y,
                        uint32_t source, uint32_t tool_type,
                        uint32_t button_state, uint32_t action_button,
                        float pressure, float vscroll, float hscroll,
                        int64_t down_time_ns, int64_t event_ns, uint32_t event_id) {
    p.writeInt32(1);       /* pointerCount */
    p.writeInt32(1);       /* sampleCount */
    p.writeInt32((int32_t)(0xc0000000u | (event_id & 0x3fffffffu)));
    p.writeInt32(0);       /* deviceId */
    p.writeUint32(source);
    p.writeInt32(0);       /* displayId */
    std::vector<uint8_t> hmac(32, 0); /* INVALID_HMAC: never claim hardware authentication. */
    p.writeByteVector(hmac);
    const bool button_action = action == AAAS_ACTION_BUTTON_PRESS ||
            action == AAAS_ACTION_BUTTON_RELEASE;
    p.writeInt32(action);
    p.writeInt32(button_action ? (int32_t)action_button : 0);
    p.writeUint32(0);      /* flags */
    p.writeInt32(0);       /* edgeFlags */
    p.writeInt32(0);       /* metaState */
    const uint32_t parcel_button_state = action == AAAS_ACTION_UP ? 0 : button_state;
    p.writeInt32((int32_t)parcel_button_state);
    p.writeByte(0);        /* classification */
    write_identity_matrix(p); /* event transform */
    p.writeFloat(0.0f);    /* injected event precision, matching Android builders */
    p.writeFloat(0.0f);
    const bool mouse_source = (source & AAAS_SOURCE_MOUSE) == AAAS_SOURCE_MOUSE;
    const float cursor_x = mouse_source ? (float)x : std::numeric_limits<float>::quiet_NaN();
    const float cursor_y = mouse_source ? (float)y : std::numeric_limits<float>::quiet_NaN();
    p.writeFloat(cursor_x); /* absolute cursor position for mouse-class sources */
    p.writeFloat(cursor_y);
    write_identity_matrix(p); /* raw transform */
    p.writeInt64(down_time_ns); /* downTime */
    p.writeInt32(0);        /* pointer id */
    p.writeInt32((int32_t)tool_type);
    p.writeInt64(event_ns); /* sample event time */

    uint64_t bits = 0;
    set_axis(&bits, 0); /* AMOTION_EVENT_AXIS_X from android/input.h */
    set_axis(&bits, 1); /* AMOTION_EVENT_AXIS_Y */
    if (pressure != 0.0f) set_axis(&bits, 2); /* AMOTION_EVENT_AXIS_PRESSURE */
    if (vscroll != 0.0f) set_axis(&bits, 9); /* AMOTION_EVENT_AXIS_VSCROLL */
    if (hscroll != 0.0f) set_axis(&bits, 10); /* AMOTION_EVENT_AXIS_HSCROLL */
    p.writeInt64((int64_t)bits);
    p.writeFloat((float)x);
    p.writeFloat((float)y);
    if (pressure != 0.0f) p.writeFloat(pressure);
    if (vscroll != 0.0f) p.writeFloat(vscroll);
    if (hscroll != 0.0f) p.writeFloat(hscroll);
    p.writeBool(false); /* PointerCoords::isResampled */
}

} /* namespace */

static int binder_transact_event(int action, int32_t x, int32_t y,
                                 uint32_t source, uint32_t tool_type,
                                 uint32_t button_state, uint32_t action_button,
                                 float pressure, float vscroll, float hscroll,
                                 int64_t event_ns, uint32_t event_id) {
    if (!g_input_binder) {
        g_input_binder = new sp<IBinder>();
    }
    if (!g_input_binder->get()) {
        sp<IServiceManager> sm = android::defaultServiceManager();
        if (!sm.get()) {
            return -1;
        }
        *g_input_binder = sm->checkService(String16("input"));
        if (!g_input_binder->get()) {
            return -1;
        }
        const String16 descriptor = (*g_input_binder)->getInterfaceDescriptor();
        if (descriptor != String16("android.hardware.input.IInputManager")) {
            g_input_binder->clear();
            return -4;
        }
    }

    if (event_ns <= g_last_event_ns) {
        event_ns = g_last_event_ns + 1;
    }
    g_last_event_ns = event_ns;
    const bool button_down = action == AAAS_ACTION_DOWN;
    const bool button_up = action == AAAS_ACTION_UP || action == AAAS_ACTION_CANCEL;
    const bool mouse_source = (source & AAAS_SOURCE_MOUSE) == AAAS_SOURCE_MOUSE;
    int64_t down_time_ns = event_ns;
    const bool gesture_event = mouse_source &&
            (action == AAAS_ACTION_DOWN || action == AAAS_ACTION_MOVE ||
             action == AAAS_ACTION_UP || action == AAAS_ACTION_CANCEL ||
             action == AAAS_ACTION_BUTTON_PRESS || action == AAAS_ACTION_BUTTON_RELEASE);
    if (button_down && g_down_time_ns == 0) {
        g_down_time_ns = event_ns;
    }
    if (gesture_event && g_down_time_ns != 0) {
        down_time_ns = g_down_time_ns;
    }

    Parcel data, reply;
    data.writeInterfaceToken(String16("android.hardware.input.IInputManager"));
    data.writeInt32(1); /* Typed-object presence. */
    data.writeInt32(1); /* MotionEvent parcel token. */
    write_motion_event(data, action, x, y, source, tool_type, button_state,
                       action_button, pressure, vscroll, hscroll, down_time_ns,
                       event_ns, event_id);
    data.writeInt32(kInjectInputEventModeWaitForResult);

    status_t status = (*g_input_binder)->transact(
            kInjectInputEventTransaction, data, &reply, 0);
    if (status != android::OK) {
        g_input_binder->clear();
        return -1;
    }
    status_t exception = reply.readExceptionCode();
    if (exception != android::OK) {
        return -2;
    }
    if (!reply.readBool()) {
        return -3;
    }
    g_last_event_ns = event_ns;
    if (button_up && g_down_time_ns == down_time_ns) {
        g_down_time_ns = 0;
    }
    return 0;
}

int aaas_binder_inject(int action, int32_t x, int32_t y,
                       uint32_t source, uint32_t tool_type,
                       uint32_t button_state, uint32_t action_button,
                       float pressure, float vscroll, float hscroll,
                       int64_t event_ns, uint32_t event_id) {
    const bool hover_transition = action == AAAS_ACTION_HOVER_ENTER ||
            action == AAAS_ACTION_HOVER_MOVE || action == AAAS_ACTION_HOVER_EXIT;
    if (action == AAAS_ACTION_HOVER_EXIT && !g_hovering) {
        return 0;
    }
    const uint32_t base_event_id = (g_next_event_id++ & 0x3fffffffu);
    (void)event_id;
    if (action == AAAS_ACTION_DOWN && g_hovering) {
        int rc = binder_transact_event(AAAS_ACTION_HOVER_EXIT, x, y, source,
                                       tool_type, 0, 0, 0.0f, 0.0f, 0.0f,
                                       event_ns, base_event_id);
        if (rc != 0) return rc;
        g_hovering = false;
    }
    if (action == AAAS_ACTION_DOWN) {
        int rc = binder_transact_event(action, x, y, source, tool_type,
                                       button_state, action_button, pressure,
                                       vscroll, hscroll, event_ns, base_event_id + 1);
        if (rc != 0) return rc;
        rc = binder_transact_event(AAAS_ACTION_BUTTON_PRESS, x, y, source,
                                   tool_type, button_state, action_button,
                                   pressure, 0.0f, 0.0f, event_ns, base_event_id + 2);
        if (rc != 0) {
            binder_transact_event(AAAS_ACTION_UP, x, y, source, tool_type,
                                  0, action_button, 0.0f, 0.0f, 0.0f,
                                  event_ns, base_event_id + 3);
            return rc;
        }
        return 0;
    }
    if (action == AAAS_ACTION_UP) {
        const uint32_t remaining_buttons = button_state & ~action_button;
        int rc = binder_transact_event(AAAS_ACTION_BUTTON_RELEASE, x, y, source,
                                       tool_type, remaining_buttons, action_button,
                                       0.0f, 0.0f, 0.0f, event_ns, base_event_id + 1);
        if (rc != 0) return rc;
        rc = binder_transact_event(action, x, y, source, tool_type,
                                   0, action_button, pressure,
                                   vscroll, hscroll, event_ns, base_event_id + 2);
        if (rc == 0) g_hovering = false;
        return rc;
    }

    int rc = binder_transact_event(action, x, y, source, tool_type,
                                   button_state, action_button, pressure,
                                   vscroll, hscroll, event_ns, base_event_id);
    if (rc == 0 && hover_transition) {
        if (action == AAAS_ACTION_HOVER_ENTER) {
            g_hovering = true;
        } else if (action == AAAS_ACTION_HOVER_EXIT) {
            g_hovering = false;
        }
    }
    return rc;
}

void aaas_binder_shutdown(void) {
    delete g_input_binder;
    g_input_binder = nullptr;
    g_down_time_ns = 0;
    g_last_event_ns = 0;
    g_hovering = false;
    g_next_event_id = 1;
}
