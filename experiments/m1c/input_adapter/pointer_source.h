#ifndef AAAS_INPUT_POINTER_SOURCE_H
#define AAAS_INPUT_POINTER_SOURCE_H

#include "inject_binder.h"

/* Wayland's ordinary left click is an Android virtual-display tap gesture. */
static inline uint32_t aaas_pointer_source_for_buttons(uint32_t buttons) {
    return buttons == AAAS_BUTTON_PRIMARY ? AAAS_SOURCE_TOUCHSCREEN
                                          : AAAS_SOURCE_MOUSE;
}

static inline uint32_t aaas_pointer_tool_for_source(uint32_t source) {
    return source == AAAS_SOURCE_TOUCHSCREEN ? AAAS_TOOL_FINGER : AAAS_TOOL_MOUSE;
}

#endif
