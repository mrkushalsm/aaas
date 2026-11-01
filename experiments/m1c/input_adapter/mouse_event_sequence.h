#ifndef AAAS_MOUSE_EVENT_SEQUENCE_H
#define AAAS_MOUSE_EVENT_SEQUENCE_H

#include "inject_binder.h"

/* Android primary clicks use ACTION_DOWN/ACTION_UP. Button-press actions are
 * reserved for additional button transitions. */
static inline unsigned aaas_expand_mouse_button_action(int action,
                                                        uint32_t action_button,
                                                        int out[2]) {
    unsigned count = 0;
    if (action == AAAS_ACTION_DOWN) {
        out[count++] = AAAS_ACTION_DOWN;
        if (action_button != AAAS_BUTTON_PRIMARY) {
            out[count++] = AAAS_ACTION_BUTTON_PRESS;
        }
    } else if (action == AAAS_ACTION_UP) {
        if (action_button != AAAS_BUTTON_PRIMARY) {
            out[count++] = AAAS_ACTION_BUTTON_RELEASE;
        }
        out[count++] = AAAS_ACTION_UP;
    } else {
        out[count++] = action;
    }
    return count;
}

#endif
