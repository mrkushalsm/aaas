#include "keyboard_map.h"

#include <stdio.h>

static int check(const char *name, uint32_t got, uint32_t want) {
    if(got!=want) { fprintf(stderr,"FAIL %s: got=%u want=%u\n",name,got,want); return 1; }
    printf("PASS %s\n",name); return 0;
}

int main(void) {
    int failed=0;
    failed+=check("letters-lowercase",aaas_android_keycode_from_keysym(XKB_KEY_a),29);
    failed+=check("letters-uppercase",aaas_android_keycode_from_keysym(XKB_KEY_Z),54);
    failed+=check("digit-zero",aaas_android_keycode_from_keysym(XKB_KEY_0),7);
    failed+=check("shifted-number",aaas_android_keycode_from_keysym(XKB_KEY_exclam),8);
    failed+=check("punctuation",aaas_android_keycode_from_keysym(XKB_KEY_quotedbl),75);
    failed+=check("back-mapping",aaas_android_keycode_from_keysym(XKB_KEY_Escape),4);
    failed+=check("delete-mapping",aaas_android_keycode_from_keysym(XKB_KEY_Delete),112);
    failed+=check("unsupported-symbol",aaas_android_keycode_from_keysym(XKB_KEY_F35),0);

    struct xkb_context *ctx=xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    struct xkb_keymap *map=ctx?xkb_keymap_new_from_names(ctx,NULL,XKB_KEYMAP_COMPILE_NO_FLAGS):NULL;
    struct xkb_state *state=map?xkb_state_new(map):NULL;
    if(!state) { fprintf(stderr,"FAIL load default XKB keymap\n"); return 1; }
    failed+=check("default-keymap-a",xkb_state_key_get_one_sym(state,38),XKB_KEY_a);
    xkb_state_update_key(state,50,XKB_KEY_DOWN);
    failed+=check("shifted-keymap-a",xkb_state_key_get_one_sym(state,38),XKB_KEY_A);
    failed+=check("shift-meta",aaas_android_meta_state(state)&1u,1u);
    xkb_state_update_key(state,50,XKB_KEY_UP);
    failed+=check("shift-release-meta",aaas_android_meta_state(state)&1u,0u);
    xkb_state_unref(state); xkb_keymap_unref(map); xkb_context_unref(ctx);
    if(failed) return 1;
    puts("all keyboard mapping tests passed");
    return 0;
}
