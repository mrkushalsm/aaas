#ifndef AAAS_RESIZE_SCHEDULER_H
#define AAAS_RESIZE_SCHEDULER_H

#include <stdbool.h>
#include <stdint.h>

#define AAAS_RESIZE_FAST_SETTLE_NS 60000000ULL
#define AAAS_RESIZE_SLOW_SETTLE_NS 120000000ULL
#define AAAS_RESIZE_FAST_INTERVAL_NS 80000000ULL

typedef struct {
    uint32_t width;
    uint32_t height;
    uint64_t deadline_ns;
    uint64_t settle_ns;
    uint32_t coalesced;
    bool pending;
} aaas_resize_scheduler;

static inline uint64_t aaas_resize_settle_for_interval(uint64_t interval_ns) {
    return interval_ns > 0 && interval_ns < AAAS_RESIZE_FAST_INTERVAL_NS
        ? AAAS_RESIZE_FAST_SETTLE_NS : AAAS_RESIZE_SLOW_SETTLE_NS;
}

static inline void aaas_resize_schedule(aaas_resize_scheduler *scheduler,
                                       uint32_t width, uint32_t height,
                                       uint64_t now_ns, uint64_t settle_ns) {
    if (scheduler->pending) scheduler->coalesced++;
    scheduler->width = width;
    scheduler->height = height;
    scheduler->settle_ns = settle_ns;
    scheduler->deadline_ns = now_ns + settle_ns;
    scheduler->pending = true;
}

static inline bool aaas_resize_cancel_if_equal(aaas_resize_scheduler *scheduler,
                                               uint32_t active_width,
                                               uint32_t active_height) {
    if (!scheduler->pending || scheduler->width != active_width ||
            scheduler->height != active_height) return false;
    scheduler->pending = false;
    scheduler->coalesced = 0;
    return true;
}

static inline bool aaas_resize_cancel(aaas_resize_scheduler *scheduler) {
    if (!scheduler->pending) return false;
    scheduler->pending = false;
    scheduler->coalesced = 0;
    return true;
}

static inline bool aaas_resize_take_due(aaas_resize_scheduler *scheduler,
                                        uint64_t now_ns,
                                        uint32_t *width, uint32_t *height,
                                        uint32_t *coalesced) {
    if (!scheduler->pending || now_ns < scheduler->deadline_ns) return false;
    if (width) *width = scheduler->width;
    if (height) *height = scheduler->height;
    if (coalesced) *coalesced = scheduler->coalesced;
    scheduler->pending = false;
    scheduler->coalesced = 0;
    return true;
}

#endif
