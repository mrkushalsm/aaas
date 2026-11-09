#include "staging_backpressure.h"

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/eventfd.h>
#include <unistd.h>

/* This harness calls the same tracker transitions used by gpu_presenter.c.
 * Fake source slots and eventfds model resource ownership; eventfds are not
 * represented as DRM sync_files and this test does not claim GPU coverage. */
typedef struct {
    aaas_staging_tracker tracker;
    bool source_busy[2];
    int resource_fd[AAAS_STAGING_MAX_IN_FLIGHT];
    uint32_t token[AAAS_STAGING_MAX_IN_FLIGHT];
    uint32_t id[AAAS_STAGING_MAX_IN_FLIGHT];
    uint32_t generation[AAAS_STAGING_MAX_IN_FLIGHT];
    bool submitted[AAAS_STAGING_MAX_IN_FLIGHT];
    bool source_held[AAAS_STAGING_MAX_IN_FLIGHT];
    unsigned source[AAAS_STAGING_MAX_IN_FLIGHT];
    unsigned allocations;
    unsigned rejected;
    uint32_t next_id;
} model;

static void model_init(model *m) {
    *m = (model){0};
    aaas_staging_init(&m->tracker);
    m->next_id = 1;
    for (unsigned i = 0; i < AAAS_STAGING_MAX_IN_FLIGHT; i++)
        m->resource_fd[i] = -1;
}

static int find_token(const model *m, uint32_t token) {
    for (unsigned i = 0; i < AAAS_STAGING_MAX_IN_FLIGHT; i++)
        if (m->token[i] == token) return (int)i;
    return -1;
}

static uint32_t submit_frame(model *m, unsigned source, uint32_t generation) {
    assert(source < 2 && !m->source_busy[source]);
    uint32_t id = m->next_id++;
    uint32_t token = 0;
    assert(aaas_staging_reserve(&m->tracker, id, generation, &token) ==
           AAAS_STAGING_OK);
    int resource = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    assert(resource >= 0);
    assert(aaas_staging_mark_allocated(&m->tracker, token) == AAAS_STAGING_OK);
    assert(aaas_staging_mark_allocated(&m->tracker, token) ==
           AAAS_STAGING_DUPLICATE);
    aaas_staging_copy_decision decision =
        aaas_staging_copy_decide(&m->tracker, token);
    if (decision == AAAS_STAGING_COPY_EARLY) {
        assert(aaas_staging_mark_copy_complete_sent(&m->tracker, token) ==
               AAAS_STAGING_OK);
        m->source_busy[source] = false;
    } else {
        assert(decision == AAAS_STAGING_COPY_DEFER);
        m->source_busy[source] = true;
    }
    assert(aaas_staging_mark_submitted(&m->tracker, token) == AAAS_STAGING_OK);
    int entry = find_token(m, token);
    assert(entry < 0);
    for (unsigned i = 0; i < AAAS_STAGING_MAX_IN_FLIGHT; i++) {
        if (!m->token[i]) { entry = (int)i; break; }
    }
    assert(entry >= 0);
    m->token[entry] = token;
    m->id[entry] = id;
    m->generation[entry] = generation;
    m->resource_fd[entry] = resource;
    m->submitted[entry] = true;
    m->source_held[entry] = decision == AAAS_STAGING_COPY_DEFER;
    m->source[entry] = source;
    m->allocations++;
    return token;
}

static void release_frame(model *m, uint32_t token) {
    int entry = find_token(m, token);
    assert(entry >= 0 && m->submitted[entry]);
    assert(aaas_staging_release(&m->tracker, token, m->id[entry],
                                m->generation[entry]) == AAAS_STAGING_OK);
    assert(close(m->resource_fd[entry]) == 0);
    if (m->source_held[entry]) m->source_busy[m->source[entry]] = false;
    m->token[entry] = 0;
    m->id[entry] = 0;
    m->generation[entry] = 0;
    m->resource_fd[entry] = -1;
    m->submitted[entry] = false;
    m->source_held[entry] = false;
}

static void cancel_all(model *m) {
    for (unsigned i = 0; i < AAAS_STAGING_MAX_IN_FLIGHT; i++) {
        if (!m->token[i]) continue;
        assert(aaas_staging_cancel(&m->tracker, m->token[i]) == AAAS_STAGING_OK);
        assert(close(m->resource_fd[i]) == 0);
        m->token[i] = 0;
        m->resource_fd[i] = -1;
        m->source_held[i] = false;
    }
    m->source_busy[0] = m->source_busy[1] = false;
}

static void assert_empty(const model *m) {
    assert(m->tracker.active_count == 0);
    assert(m->tracker.early_credit_count == 0);
    assert(aaas_staging_source_ownership_count(&m->tracker) == 0);
    assert(aaas_staging_compositor_ownership_count(&m->tracker) == 0);
    assert(m->tracker.peak_active <= AAAS_STAGING_MAX_IN_FLIGHT);
    for (unsigned i = 0; i < AAAS_STAGING_MAX_IN_FLIGHT; i++)
        assert(m->resource_fd[i] == -1 && m->token[i] == 0);
    assert(!m->source_busy[0] && !m->source_busy[1]);
}

static void test_normal_two_source_progress(void) {
    model m; model_init(&m);
    uint32_t one = submit_frame(&m, 0, 1);
    uint32_t two = submit_frame(&m, 1, 1);
    assert(!m.source_busy[0] && !m.source_busy[1]);
    assert(aaas_staging_source_ownership_count(&m.tracker) == 0);
    assert(aaas_staging_compositor_ownership_count(&m.tracker) == 2);
    release_frame(&m, two); /* out-of-order release opens an early-copy credit */
    uint32_t three = submit_frame(&m, 0, 1);
    uint32_t four = submit_frame(&m, 1, 1);
    uint32_t five = submit_frame(&m, 0, 1);
    assert(m.source_busy[0] && m.source_busy[1]);
    assert(m.tracker.active_count == 4 && m.tracker.early_credit_count == 2);
    assert(aaas_staging_source_ownership_count(&m.tracker) == 2);
    assert(aaas_staging_compositor_ownership_count(&m.tracker) == 4);
    release_frame(&m, four); /* actual compositor release returns deferred source */
    assert(!m.source_busy[1]);
    assert(aaas_staging_source_ownership_count(&m.tracker) == 1);
    uint32_t six = submit_frame(&m, 1, 1);
    assert(m.tracker.active_count == 4);
    release_frame(&m, six);
    release_frame(&m, one);
    release_frame(&m, five);
    release_frame(&m, three);
    assert(m.tracker.deferred_copy == 3);
    assert(m.tracker.deferred_settled_by_release == 3);
    assert(m.tracker.actual_releases == 6);
    assert(m.tracker.peak_active == 4);
    assert_empty(&m);
}

static void test_stalled_releases_and_preallocation_limit(void) {
    model m; model_init(&m);
    (void)submit_frame(&m, 0, 7);
    (void)submit_frame(&m, 1, 7);
    (void)submit_frame(&m, 0, 7);
    (void)submit_frame(&m, 1, 7);
    unsigned allocated_before = m.allocations;
    uint32_t token = 0;
    assert(aaas_staging_reserve(&m.tracker, m.next_id++, 7, &token) ==
           AAAS_STAGING_LIMIT);
    assert(m.allocations == allocated_before); /* no BO after cap */
    assert(m.tracker.active_count == 4);
    release_frame(&m, m.token[2]);
    uint32_t next = submit_frame(&m, 0, 7);
    assert(next && m.tracker.active_count == 4);
    cancel_all(&m); /* bounded teardown even if remaining releases never arrive */
    assert(m.tracker.teardown_canceled == 4);
    assert(m.tracker.deferred_canceled == 2);
    assert_empty(&m);
}

static void test_duplicate_stale_and_generation_events(void) {
    model m; model_init(&m);
    uint32_t token = submit_frame(&m, 0, 3);
    int entry = find_token(&m, token);
    assert(entry >= 0);
    assert(aaas_staging_reserve(&m.tracker, m.id[entry], 3, &(uint32_t){0}) ==
           AAAS_STAGING_DUPLICATE);
    assert(aaas_staging_release(&m.tracker, token, m.id[entry], 4) ==
           AAAS_STAGING_INVALID);
    release_frame(&m, token);
    assert(aaas_staging_release(&m.tracker, token, m.id[entry], 3) ==
           AAAS_STAGING_STALE);
    assert(m.tracker.stale_or_duplicate_events >= 2);
    assert_empty(&m);
}

static void test_reject_timeout_and_abandon(void) {
    model m; model_init(&m);
    uint32_t token = 0;
    assert(aaas_staging_reserve(&m.tracker, 100, 9, &token) == AAAS_STAGING_OK);
    /* A timed-out acquire fence rejects this frame; no completion is invented. */
    assert(aaas_staging_reject(&m.tracker, token) == AAAS_STAGING_OK);
    assert(m.tracker.rejected_before_submit == 1);
    assert(m.tracker.early_copy_sent == 0);
    assert(aaas_staging_reserve(&m.tracker, 101, 9, &token) == AAAS_STAGING_OK);
    assert(aaas_staging_mark_allocation_failed(&m.tracker, token) == AAAS_STAGING_OK);
    assert(aaas_staging_mark_allocated(&m.tracker, token) ==
           AAAS_STAGING_DUPLICATE);
    assert(aaas_staging_abandon(&m.tracker, token) == AAAS_STAGING_OK);
    assert(m.tracker.allocation_failed == 1);
    assert_empty(&m);
}

static void test_initial_zero_generation(void) {
    model m; model_init(&m);
    uint32_t token = submit_frame(&m, 0, 0);
    assert(token != 0);
    release_frame(&m, token);
    assert_empty(&m);
}

static void test_disconnect_resize_and_repeated_sessions(void) {
    for (uint32_t generation = 1; generation <= 20; generation++) {
        model m; model_init(&m);
        uint32_t one = submit_frame(&m, 0, generation);
        uint32_t two = submit_frame(&m, 1, generation);
        /* Generation change does not retire old compositor-owned buffers. */
        uint32_t three = submit_frame(&m, 0, generation + 100);
        release_frame(&m, two);
        release_frame(&m, one);
        release_frame(&m, three);
        assert_empty(&m);

        uint32_t outstanding = submit_frame(&m, 0, generation + 200);
        assert(outstanding);
        cancel_all(&m); /* producer/compositor disconnect or destroyed surface */
        assert_empty(&m);
    }
}

int main(void) {
    test_normal_two_source_progress();
    test_stalled_releases_and_preallocation_limit();
    test_duplicate_stale_and_generation_events();
    test_reject_timeout_and_abandon();
    test_initial_zero_generation();
    test_disconnect_resize_and_repeated_sessions();
    puts("production staging-credit lifecycle tests passed");
    return 0;
}
