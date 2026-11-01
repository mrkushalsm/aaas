#include "window_state.h"

#include <assert.h>
#include <stdio.h>

int main(void) {
    bool maximized = false;
    bool fullscreen = false;
    bool active = false;
    bool suspended = false;

    aaas_window_state_update(&maximized, &fullscreen, &active, &suspended,
                             true, LIBDECOR_WINDOW_STATE_ACTIVE |
                                   LIBDECOR_WINDOW_STATE_MAXIMIZED);
    assert(maximized && !fullscreen && active && !suspended);

    aaas_window_state_update(&maximized, &fullscreen, &active, &suspended,
                             true, LIBDECOR_WINDOW_STATE_FULLSCREEN |
                                   LIBDECOR_WINDOW_STATE_ACTIVE);
    assert(!maximized && fullscreen && active && !suspended);

    aaas_window_state_update(&maximized, &fullscreen, &active, &suspended,
                             true, LIBDECOR_WINDOW_STATE_SUSPENDED);
    assert(!maximized && !fullscreen && !active && suspended);

    /* A configure without state must preserve the last published snapshot. */
    aaas_window_state_update(&maximized, &fullscreen, &active, &suspended,
                             false, LIBDECOR_WINDOW_STATE_NONE);
    assert(!maximized && !fullscreen && !active && suspended);
    puts("window configure state tests passed");
    return 0;
}
