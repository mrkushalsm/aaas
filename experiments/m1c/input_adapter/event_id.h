#ifndef AAAS_INPUT_EVENT_ID_H
#define AAAS_INPUT_EVENT_ID_H

#include <stdint.h>

/* frameworks/native IdGenerator::Source::OTHER (app-injected events). */
static inline int32_t aaas_motion_event_id(uint32_t sequence) {
    return (int32_t)(0xc0000000u | (sequence & 0x3fffffffu));
}

#endif
