#include "input_v1.h"

#include <stdio.h>
#include <string.h>

static int failures;

static aaas_input_msg base(uint16_t type) {
    aaas_input_msg m;
    memset(&m, 0, sizeof(m));
    m.magic = AAAS_INPUT_MAGIC;
    m.version = AAAS_INPUT_VERSION;
    m.type = type;
    m.length = AAAS_INPUT_MSG_SIZE;
    m.sequence = 7;
    m.display_id = 0;
    m.display_generation = 3;
    m.timestamp_ns = 123456789;
    m.session_id = 0x1122334455667788ULL;
    m.x = 310;
    m.y = 393;
    m.focus_generation = 2;
    return m;
}

static void expect_valid(const char *name, const aaas_input_msg *m, int valid) {
    char why[64] = {0};
    int rc = aaas_input_validate(m, 0x1122334455667788ULL, 0, why, sizeof(why));
    if ((rc == 0) != valid) {
        fprintf(stderr, "FAIL %s: rc=%d why=%s expected valid=%d\n", name, rc, why, valid);
        failures++;
    } else {
        printf("PASS %s: valid=%d\n", name, valid);
    }
}

static void expect_keyboard_valid(const char *name, const aaas_input_keyboard_msg *m, int valid) {
    char why[64]={0};
    int rc=aaas_input_keyboard_validate(m,0x1122334455667788ULL,0,why,sizeof(why));
    if((rc==0)!=valid) { fprintf(stderr,"FAIL %s: %s\n",name,why); failures++; }
    else printf("PASS %s: valid=%d\n",name,valid);
}

int main(void) {
    aaas_input_msg m = base(AAAS_INPUT_HELLO);
    m.x = 1280;
    m.y = 720;
    expect_valid("hello", &m, 1);

    m.flags = AAAS_INPUT_FLAG_ACK;
    expect_valid("hello-ack", &m, 1);
    m.flags = AAAS_INPUT_FLAG_ACK | AAAS_INPUT_FLAG_KEYBOARD_V2;
    expect_valid("hello-ack-keyboard-v2", &m, 1);
    m.flags = AAAS_INPUT_FLAG_KEYBOARD_V2;
    expect_valid("keyboard-capability-without-ack", &m, 0);

    aaas_input_msg wire, roundtrip;
    aaas_input_to_wire(&wire, &m);
    aaas_input_from_wire(&roundtrip, &wire);
    if (memcmp(&m, &roundtrip, sizeof(m)) != 0) {
        fprintf(stderr, "FAIL endian roundtrip\n");
        failures++;
    } else {
        printf("PASS endian roundtrip\n");
    }

    aaas_input_keyboard_msg key={
        .magic=AAAS_INPUT_MAGIC,.version=AAAS_INPUT_KEYBOARD_VERSION,
        .type=AAAS_INPUT_KEY,.length=AAAS_INPUT_KEYBOARD_MSG_SIZE,.sequence=8,
        .display_id=0,.display_generation=3,.timestamp_ns=123456789,
        .session_id=0x1122334455667788ULL,.focus_generation=3,.evdev_key=30,
        .android_keycode=29,.state=AAAS_INPUT_KEY_PRESSED,.meta_state=1,
        .keysym='A',.unicode_scalar='A'};
    expect_keyboard_valid("keyboard-down",&key,1);
    aaas_input_keyboard_msg kw,kr;
    aaas_input_keyboard_to_wire(&kw,&key); aaas_input_keyboard_from_wire(&kr,&kw);
    if(memcmp(&key,&kr,sizeof(key))) { fprintf(stderr,"FAIL keyboard endian roundtrip\n"); failures++; }
    else puts("PASS keyboard endian roundtrip");
    key.unicode_scalar=0xd800; expect_keyboard_valid("keyboard-invalid-surrogate",&key,0);
    key.unicode_scalar='A'; key.type=AAAS_INPUT_KEYBOARD_FOCUS;
    key.state=AAAS_INPUT_FOCUS_ENTER; key.evdev_key=0; key.android_keycode=0;
    key.meta_state=0; key.keysym=0; key.unicode_scalar=0;
    expect_keyboard_valid("keyboard-focus-enter",&key,1);

    m = base(AAAS_INPUT_FOCUS);
    m.state = AAAS_INPUT_FOCUS_ENTER;
    expect_valid("focus-enter", &m, 1);
    m.state = AAAS_INPUT_FOCUS_LEAVE;
    expect_valid("focus-leave", &m, 1);
    m.state = 2;
    expect_valid("focus-bad-state", &m, 0);

    m = base(AAAS_INPUT_MOTION);
    expect_valid("motion", &m, 1);

    m = base(AAAS_INPUT_BUTTON);
    m.button = AAAS_INPUT_BUTTON_LEFT;
    m.state = AAAS_INPUT_BUTTON_PRESSED;
    expect_valid("button-left-press", &m, 1);
    m.state = AAAS_INPUT_BUTTON_RELEASED;
    expect_valid("button-left-release", &m, 1);
    m.button = 0x999;
    expect_valid("button-unsupported", &m, 0);

    m = base(AAAS_INPUT_HOVER);
    expect_valid("hover", &m, 1);
    m.state = 1;
    expect_valid("hover-with-state", &m, 0);

    m = base(AAAS_INPUT_SCROLL);
    m.state = 60;
    expect_valid("scroll-smooth", &m, 1);
    m.flags = AAAS_INPUT_FLAG_AXIS_VALUE120;
    expect_valid("scroll-value120", &m, 1);
    m.reserved = 0xffff;
    expect_valid("scroll-horizontal", &m, 1);
    m.button = 4;
    expect_valid("scroll-bad-source", &m, 0);

    m = base(AAAS_INPUT_SCROLL);
    expect_valid("scroll-empty", &m, 0);

    m = base(AAAS_INPUT_AXIS_STOP);
    m.button = AAAS_INPUT_AXIS_VERTICAL | AAAS_INPUT_AXIS_HORIZONTAL;
    expect_valid("axis-stop", &m, 1);
    m.button = 5;
    expect_valid("axis-stop-bad-mask", &m, 0);
    m = base(AAAS_INPUT_AXIS_STOP);
    m.state = 1;
    expect_valid("axis-stop-with-state", &m, 0);

    m = base(AAAS_INPUT_SHUTDOWN);
    expect_valid("shutdown", &m, 1);

    m = base(AAAS_INPUT_MOTION);
    m.magic = 0;
    expect_valid("bad-magic", &m, 0);
    m = base(AAAS_INPUT_MOTION);
    m.version = 2;
    expect_valid("bad-version", &m, 0);
    m = base(AAAS_INPUT_MOTION);
    m.length = 1;
    expect_valid("bad-length", &m, 0);
    m = base(AAAS_INPUT_MOTION);
    m.session_id = 1;
    expect_valid("stale-session", &m, 0);
    m = base(AAAS_INPUT_MOTION);
    m.display_id = 1;
    expect_valid("wrong-display", &m, 0);
    m = base(AAAS_INPUT_MOTION);
    m.x = -1;
    expect_valid("negative-coordinate", &m, 0);
    m = base(AAAS_INPUT_MOTION);
    m.y = AAAS_INPUT_MAX_DIM;
    expect_valid("oversize-coordinate", &m, 0);
    m = base(AAAS_INPUT_MOTION);
    m.display_generation = 0;
    expect_valid("missing-display-generation", &m, 0);
    m = base(AAAS_INPUT_MOTION);
    m.flags = 2;
    expect_valid("bad-flags", &m, 0);
    m = base(AAAS_INPUT_MOTION);
    m.reserved = 1;
    expect_valid("bad-reserved", &m, 0);
    m = base(AAAS_INPUT_MOTION);
    m.flags = AAAS_INPUT_FLAG_ACK;
    expect_valid("ack-on-motion", &m, 0);

    if (failures) {
        fprintf(stderr, "%d input protocol test(s) failed\n", failures);
        return 1;
    }
    printf("all input protocol tests passed\n");
    return 0;
}
