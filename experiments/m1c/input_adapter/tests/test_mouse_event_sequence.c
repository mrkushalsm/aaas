#include "mouse_event_sequence.h"
#include "event_id.h"
#include "pointer_source.h"
#include "pointer_injection_policy.h"

#include <assert.h>

static void expect(int action, uint32_t button, const int *expected,
                   unsigned expected_count) {
    int actual[2] = { -1, -1 };
    unsigned count = aaas_expand_mouse_button_action(action, button, actual);
    assert(count == expected_count);
    for (unsigned i = 0; i < count; ++i) assert(actual[i] == expected[i]);
}

int main(void) {
    assert((uint32_t)aaas_motion_event_id(1) == 0xc0000001u);
    assert((uint32_t)aaas_motion_event_id(0x40000001u) == 0xc0000001u);
    assert(aaas_pointer_source_for_buttons(AAAS_BUTTON_PRIMARY) == AAAS_SOURCE_TOUCHSCREEN);
    assert(aaas_pointer_tool_for_source(AAAS_SOURCE_TOUCHSCREEN) == AAAS_TOOL_FINGER);
    assert(aaas_pointer_source_for_buttons(AAAS_BUTTON_SECONDARY) == AAAS_SOURCE_MOUSE);
    assert(aaas_touch_gesture_uses_shell(AAAS_SOURCE_TOUCHSCREEN, AAAS_ACTION_DOWN));
    assert(aaas_touch_gesture_uses_shell(AAAS_SOURCE_TOUCHSCREEN, AAAS_ACTION_MOVE));
    assert(aaas_touch_gesture_uses_shell(AAAS_SOURCE_TOUCHSCREEN, AAAS_ACTION_UP));
    assert(aaas_touch_gesture_uses_shell(AAAS_SOURCE_TOUCHSCREEN, AAAS_ACTION_CANCEL));
    assert(!aaas_touch_gesture_uses_shell(AAAS_SOURCE_MOUSE, AAAS_ACTION_DOWN));
    assert(!aaas_touch_gesture_uses_shell(AAAS_SOURCE_TOUCHSCREEN,
                                          AAAS_ACTION_BUTTON_PRESS));
    const int primary_down[] = { AAAS_ACTION_DOWN };
    const int primary_up[] = { AAAS_ACTION_UP };
    const int secondary_down[] = { AAAS_ACTION_DOWN, AAAS_ACTION_BUTTON_PRESS };
    const int secondary_up[] = { AAAS_ACTION_BUTTON_RELEASE, AAAS_ACTION_UP };
    const int extra_press[] = { AAAS_ACTION_BUTTON_PRESS };

    expect(AAAS_ACTION_DOWN, AAAS_BUTTON_PRIMARY, primary_down, 1);
    expect(AAAS_ACTION_UP, AAAS_BUTTON_PRIMARY, primary_up, 1);
    expect(AAAS_ACTION_DOWN, AAAS_BUTTON_SECONDARY, secondary_down, 2);
    expect(AAAS_ACTION_UP, AAAS_BUTTON_SECONDARY, secondary_up, 2);
    expect(AAAS_ACTION_BUTTON_PRESS, AAAS_BUTTON_SECONDARY, extra_press, 1);
    return 0;
}
