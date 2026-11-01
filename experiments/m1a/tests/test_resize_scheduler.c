#include "resize_scheduler.h"

#include <assert.h>
#include <stdio.h>

int main(void) {
    aaas_resize_scheduler scheduler = {0};
    uint32_t width = 0, height = 0, coalesced = 0;

    assert(aaas_resize_settle_for_interval(0) == AAAS_RESIZE_SLOW_SETTLE_NS);
    assert(aaas_resize_settle_for_interval(40000000ULL) ==
           AAAS_RESIZE_FAST_SETTLE_NS);
    assert(aaas_resize_settle_for_interval(80000000ULL) ==
           AAAS_RESIZE_SLOW_SETTLE_NS);
    assert(aaas_resize_settle_for_interval(120000000ULL) ==
           AAAS_RESIZE_SLOW_SETTLE_NS);

    const uint64_t first_ns = 1000000000ULL;
    const uint64_t last_ns = first_ns + 20000000ULL;
    aaas_resize_schedule(&scheduler, 700, 1200, first_ns,
                         AAAS_RESIZE_SLOW_SETTLE_NS);
    assert(!aaas_resize_take_due(&scheduler,
                                 first_ns + AAAS_RESIZE_SLOW_SETTLE_NS - 1,
                                 &width, &height, &coalesced));
    aaas_resize_schedule(&scheduler, 680, 1180, first_ns + 10000000ULL,
                         AAAS_RESIZE_FAST_SETTLE_NS);
    aaas_resize_schedule(&scheduler, 660, 1160, last_ns,
                         AAAS_RESIZE_FAST_SETTLE_NS);
    assert(scheduler.coalesced == 2);
    assert(!aaas_resize_take_due(&scheduler,
                                 last_ns + AAAS_RESIZE_FAST_SETTLE_NS - 1,
                                 &width, &height, &coalesced));
    assert(aaas_resize_take_due(&scheduler,
                                last_ns + AAAS_RESIZE_FAST_SETTLE_NS,
                                &width, &height, &coalesced));
    assert(width == 660 && height == 1160 && coalesced == 2);
    assert(!scheduler.pending);

    const uint64_t slow_last_ns = 1300000000ULL;
    aaas_resize_schedule(&scheduler, 500, 900, 1200000000ULL,
                         AAAS_RESIZE_SLOW_SETTLE_NS);
    aaas_resize_schedule(&scheduler, 520, 920, slow_last_ns,
                         aaas_resize_settle_for_interval(100000000ULL));
    assert(!aaas_resize_take_due(&scheduler,
                                 slow_last_ns + AAAS_RESIZE_SLOW_SETTLE_NS - 1,
                                 &width, &height, &coalesced));
    assert(aaas_resize_take_due(&scheduler,
                                slow_last_ns + AAAS_RESIZE_SLOW_SETTLE_NS,
                                &width, &height, &coalesced));
    assert(width == 520 && height == 920 && coalesced == 1);

    aaas_resize_schedule(&scheduler, 720, 1280, 2000000000ULL,
                         AAAS_RESIZE_SLOW_SETTLE_NS);
    assert(aaas_resize_cancel_if_equal(&scheduler, 720, 1280));
    assert(!scheduler.pending);
    aaas_resize_schedule(&scheduler, 800, 1200, 2100000000ULL,
                         AAAS_RESIZE_SLOW_SETTLE_NS);
    assert(aaas_resize_cancel(&scheduler));
    assert(!scheduler.pending && scheduler.coalesced == 0);

    aaas_resize_schedule(&scheduler, 960, 557, 2200000000ULL,
                         AAAS_RESIZE_SLOW_SETTLE_NS);
    assert(!aaas_resize_cancel_if_equal(&scheduler, 960, 565));
    assert(aaas_resize_take_due(&scheduler,
                                2200000000ULL + AAAS_RESIZE_SLOW_SETTLE_NS,
                                &width, &height, &coalesced));
    assert(width == 960 && height == 557 && coalesced == 0);
    puts("resize scheduler: PASS");
    return 0;
}
