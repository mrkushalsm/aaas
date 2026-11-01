#include "resize_scheduler.h"

#include <assert.h>
#include <stdio.h>

int main(void) {
    aaas_resize_scheduler scheduler = {0};
    uint32_t width = 0, height = 0, coalesced = 0;

    aaas_resize_schedule(&scheduler, 700, 1200, 1000);
    assert(!aaas_resize_take_due(&scheduler, 1000 + AAAS_RESIZE_SETTLE_NS - 1,
                                 &width, &height, &coalesced));
    aaas_resize_schedule(&scheduler, 680, 1180, 50000000);
    aaas_resize_schedule(&scheduler, 660, 1160, 90000000);
    assert(scheduler.coalesced == 2);
    assert(!aaas_resize_take_due(&scheduler, 209000000,
                                 &width, &height, &coalesced));
    assert(aaas_resize_take_due(&scheduler, 210000000,
                                &width, &height, &coalesced));
    assert(width == 660 && height == 1160 && coalesced == 2);
    assert(!scheduler.pending);

    aaas_resize_schedule(&scheduler, 720, 1280, 300000000);
    assert(aaas_resize_cancel_if_equal(&scheduler, 720, 1280));
    assert(!scheduler.pending);
    aaas_resize_schedule(&scheduler, 800, 1200, 350000000);
    assert(aaas_resize_cancel(&scheduler));
    assert(!scheduler.pending && scheduler.coalesced == 0);

    aaas_resize_schedule(&scheduler, 960, 557, 400000000);
    assert(!aaas_resize_cancel_if_equal(&scheduler, 960, 565));
    assert(aaas_resize_take_due(&scheduler, 520000000,
                                &width, &height, &coalesced));
    assert(width == 960 && height == 557 && coalesced == 0);
    puts("resize scheduler: PASS");
    return 0;
}
