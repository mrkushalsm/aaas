#ifndef AAAS_POINTER_INJECTION_POLICY_H
#define AAAS_POINTER_INJECTION_POLICY_H

#include "inject_binder.h"

/* Android shell-built MotionEvents are used for touchscreen gestures in auto
 * mode. The direct Binder path remains suitable for keyboard and mouse input,
 * but a live Contacts navigation-drawer test showed that Binder-accepted
 * touchscreen events did not activate child click targets while the platform
 * InputShellCommand path did. Keep this decision source/action based so it
 * applies to every Android app and display. */
static inline int aaas_touch_gesture_uses_shell(uint32_t source, int action) {
    if (source != AAAS_SOURCE_TOUCHSCREEN) return 0;
    return action == AAAS_ACTION_DOWN || action == AAAS_ACTION_MOVE ||
            action == AAAS_ACTION_UP || action == AAAS_ACTION_CANCEL;
}

#endif
