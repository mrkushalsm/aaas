#ifndef AAAS_STAGING_BACKPRESSURE_H
#define AAAS_STAGING_BACKPRESSURE_H

/* The Composer owns two reusable source buffers. Early copy-complete credits
 * must not let staged Wayland buffers grow without bound while the compositor
 * stops releasing them. */
#define AAAS_STAGING_EARLY_COPY_CREDITS 2u
#define AAAS_STAGING_MAX_IN_FLIGHT 4u

static inline int aaas_staging_can_complete_source_copy(unsigned active_slots) {
    return active_slots < AAAS_STAGING_EARLY_COPY_CREDITS;
}

static inline int aaas_staging_can_import(unsigned active_slots) {
    return active_slots < AAAS_STAGING_MAX_IN_FLIGHT;
}

#endif
