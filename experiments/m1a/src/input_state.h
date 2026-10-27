#ifndef AAAS_INPUT_STATE_H
#define AAAS_INPUT_STATE_H

#include "input_v1.h"

#include <stddef.h>
#include <stdint.h>

/*
 * Receiver-side ordering state for the AaaS pointer protocol.
 *
 * The adapter accepts one HELLO per connection, then requires strictly
 * increasing sequence numbers and non-decreasing display/focus generations.
 * Sequence and generation resets are therefore scoped to a connection.
 */
typedef struct {
    uint64_t session_id;
    uint32_t display_generation;
    uint32_t focus_generation;
    uint32_t sequence;
    int initialized;
} aaas_input_state;

void aaas_input_state_init(aaas_input_state *state, uint64_t session_id);

/* Returns 1 when the message is acceptable and updates state, 0 otherwise. */
int aaas_input_state_accept(aaas_input_state *state, const aaas_input_msg *msg,
                            char *why, size_t why_len);

#endif /* AAAS_INPUT_STATE_H */
