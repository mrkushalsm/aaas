#ifndef AAAS_WINDOW_STATE_H
#define AAAS_WINDOW_STATE_H

#include <stdbool.h>
#include <stdint.h>
#include <libdecor.h>

/* xdg_toplevel state is a snapshot, and libdecor can omit it from a
 * configuration. Preserve the last published state in that case. */
static inline void aaas_window_state_update(
    bool *maximized, bool *fullscreen, bool *active, bool *suspended,
    bool has_state, enum libdecor_window_state state) {
    if (!has_state) return;
    *maximized = (state & LIBDECOR_WINDOW_STATE_MAXIMIZED) != 0;
    *fullscreen = (state & LIBDECOR_WINDOW_STATE_FULLSCREEN) != 0;
    *active = (state & LIBDECOR_WINDOW_STATE_ACTIVE) != 0;
    *suspended = (state & LIBDECOR_WINDOW_STATE_SUSPENDED) != 0;
}

#endif
