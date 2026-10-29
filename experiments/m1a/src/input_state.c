#include "input_state.h"

#include <stdio.h>
#include <string.h>

static int reject(char *why, size_t why_len, const char *reason) {
    if (why && why_len) {
        snprintf(why, why_len, "%s", reason);
    }
    return 0;
}

void aaas_input_state_init(aaas_input_state *state, uint64_t session_id,
                           uint32_t display_id) {
    memset(state, 0, sizeof(*state));
    state->session_id = session_id;
    state->display_id = display_id;
}

int aaas_input_state_accept(aaas_input_state *state, const aaas_input_msg *msg,
                            char *why, size_t why_len) {
    char local_why[64] = {0};
    if (aaas_input_validate(msg, state->session_id, state->display_id,
                            local_why, sizeof(local_why)) != 0) {
        return reject(why, why_len, local_why);
    }

    if (msg->type == AAAS_INPUT_HELLO) {
        if (msg->flags & AAAS_INPUT_FLAG_ACK) {
            return reject(why, why_len, "unexpected_hello_ack");
        }
        if (msg->sequence == 0) {
            return reject(why, why_len, "hello_sequence_zero");
        }
        state->display_generation = msg->display_generation;
        state->focus_generation = msg->focus_generation;
        state->sequence = msg->sequence;
        state->initialized = 1;
        return 1;
    }

    if (!state->initialized) {
        return reject(why, why_len, "not_initialized");
    }
    if (msg->sequence == 0 || msg->sequence <= state->sequence) {
        return reject(why, why_len, "stale_sequence");
    }
    if (msg->display_generation < state->display_generation) {
        return reject(why, why_len, "stale_display_generation");
    }
    if (msg->focus_generation < state->focus_generation) {
        return reject(why, why_len, "stale_focus_generation");
    }

    state->sequence = msg->sequence;
    state->display_generation = msg->display_generation;
    state->focus_generation = msg->focus_generation;
    return 1;
}
