#ifndef AAAS_KEYBOARD_MAP_H
#define AAAS_KEYBOARD_MAP_H

#include <stdint.h>
#include <xkbcommon/xkbcommon.h>

uint32_t aaas_android_keycode_from_keysym(xkb_keysym_t sym);
uint32_t aaas_android_meta_state(struct xkb_state *state);

#endif
