#include "inject_binder.h"
#include "event_id.h"
#include "mouse_event_sequence.h"

#include <cstdint>
#include <limits>
#include <optional>
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
constexpr int32_t kInjectInputEventModeWaitForFinish = 2;

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
                        int64_t down_time_ns, int64_t event_ns, uint32_t event_id,
                        int32_t display_id) {
    p.writeInt32(1);       /* pointerCount */
    p.writeInt32(1);       /* sampleCount */
    p.writeInt32(aaas_motion_event_id(event_id));
    p.writeInt32(0);       /* deviceId */
    p.writeUint32(source);
    p.writeInt32(display_id);
    std::vector<uint8_t> hmac(32, 0); /* INVALID_HMAC: never claim hardware authentication. */
    p.writeByteVector(hmac);
    const bool button_action = action == AAAS_ACTION_BUTTON_PRESS ||
            action == AAAS_ACTION_BUTTON_RELEASE;
    p.writeInt32(action);
    p.writeInt32(button_action ? (int32_t)action_button : 0);
    p.writeUint32(0);      /* flags */
    p.writeInt32(0);       /* edgeFlags */
    p.writeInt32(0);       /* metaState */
    /* Match InputShellCommand's DEFAULT_BUTTON_STATE for synthetic taps. */
    const uint32_t parcel_button_state =
            (action == AAAS_ACTION_DOWN || action == AAAS_ACTION_UP) ? 0 : button_state;
    p.writeInt32((int32_t)parcel_button_state);
    p.writeByte(0);        /* classification */
    write_identity_matrix(p); /* event transform */
    p.writeFloat(1.0f);    /* InputShellCommand.DEFAULT_PRECISION_X */
    p.writeFloat(1.0f);    /* InputShellCommand.DEFAULT_PRECISION_Y */
    /* MotionEvent.obtain() leaves optional raw cursor position invalid. */
    p.writeFloat(std::numeric_limits<float>::quiet_NaN());
    p.writeFloat(std::numeric_limits<float>::quiet_NaN());
    write_identity_matrix(p); /* raw transform */
    p.writeInt64(down_time_ns); /* downTime */
    p.writeInt32(0);        /* pointer id */
    p.writeInt32((int32_t)tool_type);
    p.writeInt64(event_ns); /* sample event time */

    uint64_t bits = 0;
    set_axis(&bits, 0); /* AMOTION_EVENT_AXIS_X from android/input.h */
    set_axis(&bits, 1); /* AMOTION_EVENT_AXIS_Y */
    set_axis(&bits, 2); /* AXIS_PRESSURE is present even when zero */
    set_axis(&bits, 3); /* InputShellCommand.DEFAULT_SIZE */
    if (vscroll != 0.0f) set_axis(&bits, 9); /* AMOTION_EVENT_AXIS_VSCROLL */
    if (hscroll != 0.0f) set_axis(&bits, 10); /* AMOTION_EVENT_AXIS_HSCROLL */
    p.writeInt64((int64_t)bits);
    p.writeFloat((float)x);
    p.writeFloat((float)y);
    p.writeFloat(pressure);
    p.writeFloat(1.0f);
    if (vscroll != 0.0f) p.writeFloat(vscroll);
    if (hscroll != 0.0f) p.writeFloat(hscroll);
    p.writeBool(false); /* PointerCoords::isResampled */
}

} /* namespace */

static int binder_transact_event(int action, int32_t x, int32_t y,
                                 uint32_t source, uint32_t tool_type,
                                 uint32_t button_state, uint32_t action_button,
                                 float pressure, float vscroll, float hscroll,
                                 int64_t event_ns, uint32_t event_id,
                                 int32_t display_id) {
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
    const bool pointer_source =
            (source & 0x00000002u) == 0x00000002u; /* SOURCE_CLASS_POINTER */
    int64_t down_time_ns = event_ns;
    const bool gesture_event = pointer_source &&
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
                       event_ns, event_id, display_id);
    const bool button_event = action == AAAS_ACTION_DOWN || action == AAAS_ACTION_UP ||
            action == AAAS_ACTION_BUTTON_PRESS || action == AAAS_ACTION_BUTTON_RELEASE;
    data.writeInt32(button_event ? kInjectInputEventModeWaitForFinish
                                 : kInjectInputEventModeWaitForResult);

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
                       int64_t event_ns, uint32_t event_id, int32_t display_id) {
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
                                       event_ns, base_event_id, display_id);
        if (rc != 0) return rc;
        g_hovering = false;
    }
    if (action == AAAS_ACTION_DOWN || action == AAAS_ACTION_UP) {
        int actions[2];
        const unsigned count = aaas_expand_mouse_button_action(
                action, action_button, actions);
        for (unsigned i = 0; i < count; ++i) {
            const int event_action = actions[i];
            uint32_t event_button_state = button_state;
            float event_pressure = pressure;
            if (event_action == AAAS_ACTION_UP) {
                event_button_state = 0;
                event_pressure = 0.0f;
            } else if (action == AAAS_ACTION_UP &&
                       event_action == AAAS_ACTION_BUTTON_RELEASE) {
                event_button_state &= ~action_button;
                event_pressure = 0.0f;
            }
            const int rc = binder_transact_event(
                    event_action, x, y, source, tool_type, event_button_state,
                    action_button, event_pressure, 0.0f, 0.0f, event_ns,
                    base_event_id + i + 1, display_id);
            if (rc != 0) {
                if (action == AAAS_ACTION_DOWN && i > 0) {
                    binder_transact_event(AAAS_ACTION_UP, x, y, source, tool_type,
                                          0, action_button, 0.0f, 0.0f, 0.0f,
                                          event_ns, base_event_id + count + 1,
                                          display_id);
                }
                return rc;
            }
        }
        if (action == AAAS_ACTION_UP) g_hovering = false;
        return 0;
    }

    int rc = binder_transact_event(action, x, y, source, tool_type,
                                   button_state, action_button, pressure,
                                   vscroll, hscroll, event_ns, base_event_id,
                                   display_id);
    if (rc == 0 && hover_transition) {
        if (action == AAAS_ACTION_HOVER_ENTER) {
            g_hovering = true;
        } else if (action == AAAS_ACTION_HOVER_EXIT) {
            g_hovering = false;
        }
    }
    return rc;
}

/* Android 16 KeyEvent.writeToParcel field order, verified against the
 * android16-release frameworks/base KeyEvent.java implementation. */
int aaas_binder_inject_key(int action, int32_t keycode, int32_t scancode,
                           int32_t meta_state, int32_t repeat_count,
                           int64_t event_ns, int64_t down_ns, int32_t display_id) {
    if (!g_input_binder) g_input_binder = new sp<IBinder>();
    if (!g_input_binder->get()) {
        sp<IServiceManager> sm = android::defaultServiceManager();
        if (!sm.get()) return -1;
        *g_input_binder = sm->checkService(String16("input"));
        if (!g_input_binder->get()) return -1;
        if ((*g_input_binder)->getInterfaceDescriptor() !=
                String16("android.hardware.input.IInputManager")) {
            g_input_binder->clear();
            return -4;
        }
    }
    if (action != 0 && action != 1) return -5;
    if (event_ns <= g_last_event_ns) event_ns = g_last_event_ns + 1;
    g_last_event_ns = event_ns;

    Parcel data, reply;
    data.writeInterfaceToken(String16("android.hardware.input.IInputManager"));
    data.writeInt32(1); /* non-null typed InputEvent */
    data.writeInt32(2); /* InputEvent.PARCEL_TOKEN_KEY_EVENT */
    data.writeInt32((int32_t)(g_next_event_id++ & 0x3fffffff)); /* mId */
    data.writeInt32(-1); /* VIRTUAL_KEYBOARD device id */
    data.writeInt32(0x00000101); /* SOURCE_KEYBOARD */
    data.writeInt32(display_id);
    data.writeInt32(-1); /* null mHmac */
    data.writeInt32(action);
    data.writeInt32(keycode);
    data.writeInt32(repeat_count);
    data.writeInt32(meta_state);
    data.writeInt32(scancode);
    data.writeInt32(0); /* flags */
    data.writeInt64(down_ns);
    data.writeInt64(event_ns);
    data.writeString16(std::optional<String16>{}); /* null mCharacters */
    data.writeInt32(kInjectInputEventModeWaitForResult);
    status_t status = (*g_input_binder)->transact(
            kInjectInputEventTransaction, data, &reply, 0);
    if (status != android::OK) { g_input_binder->clear(); return -1; }
    status_t exception = reply.readExceptionCode();
    if (exception != android::OK) return -2;
    if (!reply.readBool()) return -3;
    return 0;
}

void aaas_binder_shutdown(void) {
    delete g_input_binder;
    g_input_binder = nullptr;
    g_down_time_ns = 0;
    g_last_event_ns = 0;
    g_hovering = false;
    g_next_event_id = 1;
}
