#ifndef AAAS_STAGING_BACKPRESSURE_H
#define AAAS_STAGING_BACKPRESSURE_H

#include <stdbool.h>
#include <stdint.h>

/* These limits bound two different resources: source buffers returned early
 * after copying, and staging BOs retained until Wayland releases them. */
#define AAAS_STAGING_EARLY_COPY_CREDITS 2u
#define AAAS_STAGING_MAX_IN_FLIGHT 4u

typedef enum {
    AAAS_STAGING_OK = 0,
    AAAS_STAGING_DEFERRED = 1,
    AAAS_STAGING_LIMIT = -1,
    AAAS_STAGING_DUPLICATE = -2,
    AAAS_STAGING_STALE = -3,
    AAAS_STAGING_INVALID = -4
} aaas_staging_result;

typedef enum {
    AAAS_STAGING_COPY_EARLY = 0,
    AAAS_STAGING_COPY_DEFER = 1,
    AAAS_STAGING_COPY_INVALID = -1
} aaas_staging_copy_decision;

typedef struct {
    uint32_t token;
    uint32_t id;
    uint32_t generation;
    bool active;
    bool allocation_attempted;
    bool allocated;
    bool copy_complete_early_pending;
    bool copy_complete_sent;
    bool copy_complete_deferred;
    bool submitted;
} aaas_staging_entry;

typedef struct {
    aaas_staging_entry entries[AAAS_STAGING_MAX_IN_FLIGHT];
    uint32_t next_token;
    unsigned active_count;
    unsigned early_credit_count;
    uint64_t reserved;
    uint64_t allocation_succeeded;
    uint64_t allocation_failed;
    uint64_t early_copy_sent;
    uint64_t deferred_copy;
    uint64_t deferred_settled_by_release;
    uint64_t deferred_canceled;
    uint64_t actual_releases;
    uint64_t rejected_before_submit;
    uint64_t teardown_canceled;
    uint64_t stale_or_duplicate_events;
    unsigned peak_active;
} aaas_staging_tracker;

static inline void aaas_staging_init(aaas_staging_tracker *tracker) {
    if (tracker) *tracker = (aaas_staging_tracker){0};
}

static inline int aaas_staging_find_token(const aaas_staging_tracker *tracker,
                                          uint32_t token) {
    if (!tracker || !token) return -1;
    for (unsigned i = 0; i < AAAS_STAGING_MAX_IN_FLIGHT; i++) {
        if (tracker->entries[i].active && tracker->entries[i].token == token)
            return (int)i;
    }
    return -1;
}

static inline uint32_t aaas_staging_next_token(aaas_staging_tracker *tracker) {
    for (uint32_t attempt = 0; attempt < AAAS_STAGING_MAX_IN_FLIGHT + 1u;
         attempt++) {
        uint32_t candidate = ++tracker->next_token;
        if (!candidate) candidate = ++tracker->next_token;
        if (aaas_staging_find_token(tracker, candidate) < 0) return candidate;
    }
    return 0;
}

/* Reserve before GBM allocation. LIMIT guarantees no additional BO is
 * allocated. The token identifies this lifetime even if ids are later reused. */
static inline aaas_staging_result aaas_staging_reserve(
        aaas_staging_tracker *tracker, uint32_t id, uint32_t generation,
        uint32_t *token_out) {
    /* Generation zero is a valid initial/unconfigured transport generation;
     * token identity still separates each allocation lifetime. */
    if (!tracker || !token_out || !id)
        return AAAS_STAGING_INVALID;
    for (unsigned i = 0; i < AAAS_STAGING_MAX_IN_FLIGHT; i++) {
        const aaas_staging_entry *entry = &tracker->entries[i];
        if (entry->active && entry->id == id &&
            entry->generation == generation) {
            tracker->stale_or_duplicate_events++;
            return AAAS_STAGING_DUPLICATE;
        }
    }
    if (tracker->active_count >= AAAS_STAGING_MAX_IN_FLIGHT)
        return AAAS_STAGING_LIMIT;
    unsigned free_index = AAAS_STAGING_MAX_IN_FLIGHT;
    for (unsigned i = 0; i < AAAS_STAGING_MAX_IN_FLIGHT; i++) {
        if (!tracker->entries[i].active) { free_index = i; break; }
    }
    if (free_index == AAAS_STAGING_MAX_IN_FLIGHT) return AAAS_STAGING_LIMIT;
    uint32_t token = aaas_staging_next_token(tracker);
    if (!token) return AAAS_STAGING_INVALID;
    tracker->entries[free_index] = (aaas_staging_entry){
        .token = token, .id = id, .generation = generation, .active = true
    };
    tracker->active_count++;
    tracker->reserved++;
    if (tracker->active_count > tracker->peak_active)
        tracker->peak_active = tracker->active_count;
    *token_out = token;
    return AAAS_STAGING_OK;
}

static inline aaas_staging_result aaas_staging_mark_allocated(
        aaas_staging_tracker *tracker, uint32_t token) {
    int index = aaas_staging_find_token(tracker, token);
    if (index < 0) return AAAS_STAGING_STALE;
    aaas_staging_entry *entry = &tracker->entries[index];
    if (entry->allocation_attempted) {
        tracker->stale_or_duplicate_events++;
        return AAAS_STAGING_DUPLICATE;
    }
    entry->allocation_attempted = true;
    entry->allocated = true;
    tracker->allocation_succeeded++;
    return AAAS_STAGING_OK;
}

static inline aaas_staging_result aaas_staging_mark_allocation_failed(
        aaas_staging_tracker *tracker, uint32_t token) {
    int index = aaas_staging_find_token(tracker, token);
    if (index < 0) return AAAS_STAGING_STALE;
    aaas_staging_entry *entry = &tracker->entries[index];
    if (entry->allocation_attempted) {
        tracker->stale_or_duplicate_events++;
        return AAAS_STAGING_DUPLICATE;
    }
    entry->allocation_attempted = true;
    tracker->allocation_failed++;
    return AAAS_STAGING_OK;
}

static inline aaas_staging_copy_decision aaas_staging_copy_decide(
        aaas_staging_tracker *tracker, uint32_t token) {
    int index = aaas_staging_find_token(tracker, token);
    if (index < 0) return AAAS_STAGING_COPY_INVALID;
    aaas_staging_entry *entry = &tracker->entries[index];
    if (entry->copy_complete_sent || entry->copy_complete_deferred ||
        entry->submitted)
        return AAAS_STAGING_COPY_INVALID;
    if (!entry->allocated) return AAAS_STAGING_COPY_INVALID;
    if (tracker->early_credit_count < AAAS_STAGING_EARLY_COPY_CREDITS) {
        entry->copy_complete_early_pending = true;
        return AAAS_STAGING_COPY_EARLY;
    }
    entry->copy_complete_deferred = true;
    tracker->deferred_copy++;
    return AAAS_STAGING_COPY_DEFER;
}

static inline aaas_staging_result aaas_staging_mark_copy_complete_sent(
        aaas_staging_tracker *tracker, uint32_t token) {
    int index = aaas_staging_find_token(tracker, token);
    if (index < 0) return AAAS_STAGING_STALE;
    aaas_staging_entry *entry = &tracker->entries[index];
    if (entry->copy_complete_sent || entry->copy_complete_deferred ||
        !entry->copy_complete_early_pending || entry->submitted ||
        tracker->early_credit_count >= AAAS_STAGING_EARLY_COPY_CREDITS) {
        tracker->stale_or_duplicate_events++;
        return AAAS_STAGING_DUPLICATE;
    }
    entry->copy_complete_early_pending = false;
    entry->copy_complete_sent = true;
    tracker->early_credit_count++;
    tracker->early_copy_sent++;
    return AAAS_STAGING_OK;
}

static inline aaas_staging_result aaas_staging_mark_submitted(
        aaas_staging_tracker *tracker, uint32_t token) {
    int index = aaas_staging_find_token(tracker, token);
    if (index < 0) return AAAS_STAGING_STALE;
    aaas_staging_entry *entry = &tracker->entries[index];
    if (entry->submitted || !entry->allocated ||
        entry->copy_complete_early_pending) {
        tracker->stale_or_duplicate_events++;
        return AAAS_STAGING_DUPLICATE;
    }
    entry->submitted = true;
    return AAAS_STAGING_OK;
}

static inline aaas_staging_result aaas_staging_release(
        aaas_staging_tracker *tracker, uint32_t token, uint32_t id,
        uint32_t generation) {
    int index = aaas_staging_find_token(tracker, token);
    if (index < 0) {
        if (tracker) tracker->stale_or_duplicate_events++;
        return AAAS_STAGING_STALE;
    }
    aaas_staging_entry *entry = &tracker->entries[index];
    if (entry->id != id || entry->generation != generation ||
        !entry->submitted) {
        tracker->stale_or_duplicate_events++;
        return AAAS_STAGING_INVALID;
    }
    if (entry->copy_complete_sent) tracker->early_credit_count--;
    if (entry->copy_complete_deferred)
        tracker->deferred_settled_by_release++;
    *entry = (aaas_staging_entry){0};
    tracker->active_count--;
    tracker->actual_releases++;
    return AAAS_STAGING_OK;
}

/* Abandoning a reservation means no staging BO became producer-visible. */
static inline aaas_staging_result aaas_staging_abandon(
        aaas_staging_tracker *tracker, uint32_t token) {
    int index = aaas_staging_find_token(tracker, token);
    if (index < 0) return AAAS_STAGING_STALE;
    aaas_staging_entry *entry = &tracker->entries[index];
    if (entry->copy_complete_sent || entry->copy_complete_deferred ||
        entry->copy_complete_early_pending || entry->submitted)
        return AAAS_STAGING_INVALID;
    *entry = (aaas_staging_entry){0};
    tracker->active_count--;
    return AAAS_STAGING_OK;
}

static inline aaas_staging_result aaas_staging_reject(
        aaas_staging_tracker *tracker, uint32_t token) {
    int index = aaas_staging_find_token(tracker, token);
    if (index < 0) return AAAS_STAGING_STALE;
    aaas_staging_entry *entry = &tracker->entries[index];
    if (entry->submitted) return AAAS_STAGING_INVALID;
    if (entry->copy_complete_sent) tracker->early_credit_count--;
    if (entry->copy_complete_deferred) tracker->deferred_canceled++;
    *entry = (aaas_staging_entry){0};
    tracker->active_count--;
    tracker->rejected_before_submit++;
    return AAAS_STAGING_OK;
}

static inline aaas_staging_result aaas_staging_cancel(
        aaas_staging_tracker *tracker, uint32_t token) {
    int index = aaas_staging_find_token(tracker, token);
    if (index < 0) return AAAS_STAGING_STALE;
    aaas_staging_entry *entry = &tracker->entries[index];
    if (entry->copy_complete_sent) tracker->early_credit_count--;
    if (entry->copy_complete_deferred) tracker->deferred_canceled++;
    *entry = (aaas_staging_entry){0};
    tracker->active_count--;
    tracker->teardown_canceled++;
    return AAAS_STAGING_OK;
}

static inline void aaas_staging_cancel_all(aaas_staging_tracker *tracker) {
    if (!tracker) return;
    for (unsigned i = 0; i < AAAS_STAGING_MAX_IN_FLIGHT; i++) {
        if (tracker->entries[i].active)
            (void)aaas_staging_cancel(tracker, tracker->entries[i].token);
    }
}

static inline unsigned aaas_staging_source_ownership_count(
        const aaas_staging_tracker *tracker) {
    if (!tracker) return 0;
    unsigned count = 0;
    for (unsigned i = 0; i < AAAS_STAGING_MAX_IN_FLIGHT; i++) {
        const aaas_staging_entry *entry = &tracker->entries[i];
        if (entry->active && !entry->copy_complete_sent) count++;
    }
    return count;
}

static inline unsigned aaas_staging_compositor_ownership_count(
        const aaas_staging_tracker *tracker) {
    if (!tracker) return 0;
    unsigned count = 0;
    for (unsigned i = 0; i < AAAS_STAGING_MAX_IN_FLIGHT; i++)
        if (tracker->entries[i].active && tracker->entries[i].submitted)
            count++;
    return count;
}

#endif
