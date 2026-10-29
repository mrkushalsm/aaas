#ifndef AAAS_INPUT_INJECT_BINDER_H
#define AAAS_INPUT_INJECT_BINDER_H

/*
 * Minimal native Binder injector used by the persistent AaaS input adapter.
 *
 * This intentionally avoids pulling in the full Android input headers: it
 * writes the same MotionEvent parcel that `cmd input` uses, then calls
 * IInputManager.injectInputEvent (transaction 11) directly.
 */

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Subset of android/input.h used by the adapter. */
enum {
    AAAS_ACTION_DOWN = 0,
    AAAS_ACTION_UP = 1,
    AAAS_ACTION_MOVE = 2,
    AAAS_ACTION_CANCEL = 3,
    AAAS_ACTION_SCROLL = 8,
    AAAS_ACTION_HOVER_MOVE = 7,
    AAAS_ACTION_HOVER_ENTER = 9,
    AAAS_ACTION_HOVER_EXIT = 10,
    AAAS_ACTION_BUTTON_PRESS = 11,
    AAAS_ACTION_BUTTON_RELEASE = 12,
};

enum {
    AAAS_SOURCE_TOUCHSCREEN = 0x00001002u,
    AAAS_SOURCE_MOUSE = 0x00002002u,
    AAAS_SOURCE_TOUCHPAD = 0x0010200Au,
};

enum {
    AAAS_TOOL_UNKNOWN = 0,
    AAAS_TOOL_FINGER = 1,
    AAAS_TOOL_MOUSE = 3,
    AAAS_BUTTON_PRIMARY = 1u << 0,
    AAAS_BUTTON_SECONDARY = 1u << 1,
    AAAS_BUTTON_TERTIARY = 1u << 2,
};

/*
 * Returns 0 on success, -1 on binder failure, -2 on remote exception, -3 on
 * injected=false.  The adapter treats the latter as a recoverable failure.
 */
int aaas_binder_inject(int action, int32_t x, int32_t y,
                       uint32_t source, uint32_t tool_type,
                       uint32_t button_state, uint32_t action_button,
                       float pressure, float vscroll, float hscroll,
                       int64_t event_ns, uint32_t event_id);

/* Best effort cleanup; safe to call without a successful inject(). */
void aaas_binder_shutdown(void);

int aaas_binder_inject_key(int action, int32_t keycode, int32_t scancode,
                           int32_t meta_state, int32_t repeat_count,
                           int64_t event_ns, int64_t down_ns, int32_t display_id);

#ifdef __cplusplus
}
#endif

#endif /* AAAS_INPUT_INJECT_BINDER_H */
