#include "keyboard_map.h"

uint32_t aaas_android_keycode_from_keysym(xkb_keysym_t sym) {
    if (sym >= XKB_KEY_a && sym <= XKB_KEY_z) return 29u + (sym-XKB_KEY_a);
    if (sym >= XKB_KEY_A && sym <= XKB_KEY_Z) return 29u + (sym-XKB_KEY_A);
    if (sym >= XKB_KEY_1 && sym <= XKB_KEY_9) return 8u + (sym-XKB_KEY_1);
    if (sym == XKB_KEY_0) return 7;
    switch (sym) {
    case XKB_KEY_Return: case XKB_KEY_KP_Enter: return 66;
    case XKB_KEY_BackSpace: return 67;
    case XKB_KEY_Tab: case XKB_KEY_ISO_Left_Tab: return 61;
    case XKB_KEY_space: return 62;
    case XKB_KEY_Escape: return 4;
    case XKB_KEY_Delete: return 112;
    case XKB_KEY_Left: return 21; case XKB_KEY_Right: return 22;
    case XKB_KEY_Up: return 19; case XKB_KEY_Down: return 20;
    case XKB_KEY_Home: return 122; case XKB_KEY_End: return 123;
    case XKB_KEY_Page_Up: return 92; case XKB_KEY_Page_Down: return 93;
    case XKB_KEY_Shift_L: return 59; case XKB_KEY_Shift_R: return 60;
    case XKB_KEY_Control_L: return 113; case XKB_KEY_Control_R: return 114;
    case XKB_KEY_Alt_L: return 57; case XKB_KEY_Alt_R: return 58;
    case XKB_KEY_Caps_Lock: return 115;
    case XKB_KEY_Super_L: return 117; case XKB_KEY_Super_R: return 118;
    case XKB_KEY_comma: case XKB_KEY_less: return 55;
    case XKB_KEY_period: case XKB_KEY_greater: return 56;
    case XKB_KEY_exclam: return 8; case XKB_KEY_numbersign: return 10;
    case XKB_KEY_dollar: return 11; case XKB_KEY_percent: return 12;
    case XKB_KEY_asciicircum: return 13; case XKB_KEY_ampersand: return 14;
    case XKB_KEY_asterisk: return 15; case XKB_KEY_parenleft: return 16;
    case XKB_KEY_parenright: return 7;
    case XKB_KEY_grave: case XKB_KEY_asciitilde: return 68;
    case XKB_KEY_minus: case XKB_KEY_underscore: return 69;
    case XKB_KEY_equal: case XKB_KEY_plus: return 70;
    case XKB_KEY_bracketleft: case XKB_KEY_braceleft: return 71;
    case XKB_KEY_bracketright: case XKB_KEY_braceright: return 72;
    case XKB_KEY_backslash: case XKB_KEY_bar: return 73;
    case XKB_KEY_semicolon: case XKB_KEY_colon: return 74;
    case XKB_KEY_apostrophe: case XKB_KEY_quotedbl: return 75;
    case XKB_KEY_slash: case XKB_KEY_question: return 76;
    case XKB_KEY_at: return 9;
    default: return 0;
    }
}

uint32_t aaas_android_meta_state(struct xkb_state *state) {
    if (!state) return 0;
    uint32_t m=0;
    if (xkb_state_mod_name_is_active(state,XKB_MOD_NAME_SHIFT,XKB_STATE_MODS_EFFECTIVE)>0) m|=1;
    if (xkb_state_mod_name_is_active(state,XKB_MOD_NAME_ALT,XKB_STATE_MODS_EFFECTIVE)>0) m|=2;
    if (xkb_state_mod_name_is_active(state,XKB_MOD_NAME_CTRL,XKB_STATE_MODS_EFFECTIVE)>0) m|=0x1000;
    if (xkb_state_mod_name_is_active(state,"Mod4",XKB_STATE_MODS_EFFECTIVE)>0) m|=0x10000;
    if (xkb_state_mod_name_is_active(state,XKB_MOD_NAME_CAPS,XKB_STATE_MODS_EFFECTIVE)>0) m|=0x100000;
    if (xkb_state_mod_name_is_active(state,"Mod2",XKB_STATE_MODS_EFFECTIVE)>0) m|=0x200000;
    return m;
}
