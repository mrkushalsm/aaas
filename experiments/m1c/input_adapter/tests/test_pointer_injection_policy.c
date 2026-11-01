#include "pointer_injection_policy.h"
#include "pointer_source.h"

#include <assert.h>

int main(void) {
    assert(aaas_pointer_source_for_buttons(AAAS_BUTTON_PRIMARY) ==
           AAAS_SOURCE_TOUCHSCREEN);
    assert(aaas_pointer_tool_for_source(AAAS_SOURCE_TOUCHSCREEN) ==
           AAAS_TOOL_FINGER);
    assert(aaas_pointer_source_for_buttons(AAAS_BUTTON_SECONDARY) ==
           AAAS_SOURCE_MOUSE);
    assert(aaas_pointer_tool_for_source(AAAS_SOURCE_MOUSE) == AAAS_TOOL_MOUSE);

    assert(aaas_touch_gesture_uses_shell(AAAS_SOURCE_TOUCHSCREEN,
                                         AAAS_ACTION_DOWN));
    assert(aaas_touch_gesture_uses_shell(AAAS_SOURCE_TOUCHSCREEN,
                                         AAAS_ACTION_MOVE));
    assert(aaas_touch_gesture_uses_shell(AAAS_SOURCE_TOUCHSCREEN,
                                         AAAS_ACTION_UP));
    assert(aaas_touch_gesture_uses_shell(AAAS_SOURCE_TOUCHSCREEN,
                                         AAAS_ACTION_CANCEL));
    assert(!aaas_touch_gesture_uses_shell(AAAS_SOURCE_MOUSE, AAAS_ACTION_DOWN));
    assert(!aaas_touch_gesture_uses_shell(AAAS_SOURCE_TOUCHSCREEN,
                                         AAAS_ACTION_BUTTON_PRESS));
    assert(!aaas_touch_gesture_uses_shell(AAAS_SOURCE_TOUCHSCREEN,
                                         AAAS_ACTION_BUTTON_RELEASE));
    return 0;
}
