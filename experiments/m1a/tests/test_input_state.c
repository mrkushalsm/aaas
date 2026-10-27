#include "input_state.h"

#include <stdio.h>
#include <string.h>

static int failures;

static aaas_input_msg base(uint16_t type, uint32_t sequence,
                           uint32_t display_generation,
                           uint32_t focus_generation) {
    aaas_input_msg m;
    memset(&m, 0, sizeof(m));
    m.magic = AAAS_INPUT_MAGIC;
    m.version = AAAS_INPUT_VERSION;
    m.type = type;
    m.length = AAAS_INPUT_MSG_SIZE;
    m.sequence = sequence;
    m.display_id = 0;
    m.display_generation = display_generation;
    m.timestamp_ns = 1000 + sequence;
    m.session_id = 0x1122334455667788ULL;
    m.x = 100;
    m.y = 200;
    m.focus_generation = focus_generation;
    return m;
}

static void expect(const char *name, aaas_input_state *state,
                   const aaas_input_msg *msg, int valid, const char *why_part) {
    char why[64] = {0};
    int rc = aaas_input_state_accept(state, msg, why, sizeof(why));
    int ok = (rc == valid) &&
             (!why_part || (why_part[0] == '\0') || strstr(why, why_part) != NULL);
    if (!ok) {
        fprintf(stderr, "FAIL %s: rc=%d why=%s expected valid=%d why~%s\n",
                name, rc, why, valid, why_part ? why_part : "");
        failures++;
    } else {
        printf("PASS %s: valid=%d why=%s\n", name, valid, why);
    }
}

int main(void) {
    aaas_input_state state;
    aaas_input_state_init(&state, 0x1122334455667788ULL);

    aaas_input_msg hello = base(AAAS_INPUT_HELLO, 1, 3, 1);
    expect("hello", &state, &hello, 1, "");

    aaas_input_msg m = base(AAAS_INPUT_MOTION, 2, 3, 1);
    expect("motion", &state, &m, 1, "");

    m = base(AAAS_INPUT_MOTION, 0, 3, 1);
    expect("sequence-zero", &state, &m, 0, "stale_sequence");

    m = base(AAAS_INPUT_MOTION, 2, 3, 1);
    expect("sequence-replay", &state, &m, 0, "stale_sequence");

    m = base(AAAS_INPUT_MOTION, 1, 3, 1);
    expect("sequence-regression", &state, &m, 0, "stale_sequence");

    m = base(AAAS_INPUT_MOTION, 3, 2, 1);
    expect("display-generation-stale", &state, &m, 0, "stale_display_generation");

    m = base(AAAS_INPUT_MOTION, 3, 4, 1);
    expect("display-generation-advance", &state, &m, 1, "");

    m = base(AAAS_INPUT_FOCUS, 4, 4, 2);
    m.state = AAAS_INPUT_FOCUS_ENTER;
    expect("focus-generation-advance", &state, &m, 1, "");

    m = base(AAAS_INPUT_FOCUS, 5, 4, 1);
    m.state = AAAS_INPUT_FOCUS_LEAVE;
    expect("focus-generation-stale", &state, &m, 0, "stale_focus_generation");

    m = base(AAAS_INPUT_MOTION, 5, 4, 3);
    m.session_id = 0x8877665544332211ULL;
    expect("session-mismatch", &state, &m, 0, "session");

    m = base(AAAS_INPUT_HELLO, 1, 3, 1);
    m.flags = AAAS_INPUT_FLAG_ACK;
    expect("unexpected-hello-ack", &state, &m, 0, "unexpected_hello_ack");

    aaas_input_state fresh;
    aaas_input_state_init(&fresh, 0x1122334455667788ULL);
    m = base(AAAS_INPUT_MOTION, 1, 3, 1);
    expect("not-initialized", &fresh, &m, 0, "not_initialized");

    aaas_input_state reconnected;
    aaas_input_state_init(&reconnected, 0x1122334455667788ULL);
    hello = base(AAAS_INPUT_HELLO, 10, 5, 4);
    expect("reconnect-hello", &reconnected, &hello, 1, "");
    m = base(AAAS_INPUT_MOTION, 1, 5, 4);
    expect("reconnect-sequence-reset", &reconnected, &m, 0, "stale_sequence");
    m = base(AAAS_INPUT_MOTION, 11, 5, 4);
    expect("reconnect-motion", &reconnected, &m, 1, "");

    if (failures) {
        fprintf(stderr, "%d input state test(s) failed\n", failures);
        return 1;
    }
    printf("all input state tests passed\n");
    return 0;
}
