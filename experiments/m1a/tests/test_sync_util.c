#include "sync_util.h"
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <assert.h>
#include <errno.h>

static int open_render_node(void) {
    int fd = open("/dev/dri/renderD129", O_RDWR | O_CLOEXEC);
    if (fd < 0) fd = open("/dev/dri/renderD128", O_RDWR | O_CLOEXEC);
    return fd;
}

static void test_sync_file_validation(void) {
    // 1. Invalid FDs
    assert(sync_file_is_valid(-1) == 0);
    assert(sync_file_is_valid(9999) == 0);

    // 2. Regular pipe is not a sync_file
    int p[2];
    assert(pipe(p) == 0);
    assert(sync_file_is_valid(p[0]) == 0);
    close(p[0]);
    close(p[1]);

    // 3. Genuine sync_file from DRM syncobj
    int drm_fd = open_render_node();
    assert(drm_fd >= 0);

    uint32_t syncobj = 0;
    assert(syncobj_create_timeline(drm_fd, &syncobj) == 0);
    assert(syncobj_timeline_signal(drm_fd, syncobj, 1) == 0);

    int sync_file_fd = -1;
    assert(syncobj_timeline_export_sync_file(drm_fd, syncobj, 1, &sync_file_fd) == 0);
    assert(sync_file_fd >= 0);
    assert(sync_file_is_valid(sync_file_fd) == 1);
    assert(sync_file_is_signaled(sync_file_fd) == 1);
    assert(sync_file_wait(sync_file_fd, 10) == 1);

    close(sync_file_fd);
    syncobj_destroy(drm_fd, syncobj);
    close(drm_fd);
    printf("  [PASS] test_sync_file_validation\n");
}

static void test_timeline_signal_wait(void) {
    int drm_fd = open_render_node();
    assert(drm_fd >= 0);

    uint32_t timeline = 0;
    assert(syncobj_create_timeline(drm_fd, &timeline) == 0);

    // Timeline point 1 not yet signaled: wait should timeout
    assert(syncobj_timeline_wait(drm_fd, timeline, 1, 1000000ULL) != 0);

    // Signal point 1
    assert(syncobj_timeline_signal(drm_fd, timeline, 1) == 0);

    // Wait on point 1 should now succeed immediately
    assert(syncobj_timeline_wait(drm_fd, timeline, 1, 1000000ULL) == 0);

    // Point 2 still unsignaled
    assert(syncobj_timeline_wait(drm_fd, timeline, 2, 1000000ULL) != 0);

    // Signal point 2
    assert(syncobj_timeline_signal(drm_fd, timeline, 2) == 0);
    assert(syncobj_timeline_wait(drm_fd, timeline, 2, 1000000ULL) == 0);

    syncobj_destroy(drm_fd, timeline);
    close(drm_fd);
    printf("  [PASS] test_timeline_signal_wait\n");
}

static void test_sync_file_timeline_import_export(void) {
    int drm_fd = open_render_node();
    assert(drm_fd >= 0);

    uint32_t src_timeline = 0;
    assert(syncobj_create_timeline(drm_fd, &src_timeline) == 0);
    assert(syncobj_timeline_signal(drm_fd, src_timeline, 10) == 0);

    // Export point 10 to sync_file
    int sync_file_fd = -1;
    assert(syncobj_timeline_export_sync_file(drm_fd, src_timeline, 10, &sync_file_fd) == 0);
    assert(sync_file_fd >= 0);

    // Import that sync_file into dst_timeline at point 50
    uint32_t dst_timeline = 0;
    assert(syncobj_create_timeline(drm_fd, &dst_timeline) == 0);
    assert(syncobj_timeline_import_sync_file(drm_fd, dst_timeline, 50, sync_file_fd) == 0);

    // dst_timeline point 50 should now be signaled
    assert(syncobj_timeline_wait(drm_fd, dst_timeline, 50, 1000000ULL) == 0);

    close(sync_file_fd);
    syncobj_destroy(drm_fd, src_timeline);
    syncobj_destroy(drm_fd, dst_timeline);
    close(drm_fd);
    printf("  [PASS] test_sync_file_timeline_import_export\n");
}

static void test_syncobj_fd_transfer(void) {
    int drm_fd = open_render_node();
    assert(drm_fd >= 0);

    uint32_t h1 = 0;
    assert(syncobj_create_timeline(drm_fd, &h1) == 0);

    int syncobj_fd = -1;
    assert(syncobj_handle_to_fd(drm_fd, h1, &syncobj_fd) == 0);
    assert(syncobj_fd >= 0);

    uint32_t h2 = 0;
    assert(syncobj_fd_to_handle(drm_fd, syncobj_fd, &h2) == 0);
    assert(h2 > 0);

    // Signal h1, wait on h2
    assert(syncobj_timeline_signal(drm_fd, h1, 5) == 0);
    assert(syncobj_timeline_wait(drm_fd, h2, 5, 1000000ULL) == 0);

    close(syncobj_fd);
    syncobj_destroy(drm_fd, h1);
    syncobj_destroy(drm_fd, h2);
    close(drm_fd);
    printf("  [PASS] test_syncobj_fd_transfer\n");
}

static void test_unsignaled_future_point_export(void) {
    int drm_fd = open_render_node();
    assert(drm_fd >= 0);

    uint32_t tl = 0;
    assert(syncobj_create_timeline(drm_fd, &tl) == 0);

    // Unsignaled point 99: export must fail gracefully with EINVAL (-1)
    int out_fd = -1;
    int r = syncobj_timeline_export_sync_file(drm_fd, tl, 99, &out_fd);
    assert(r != 0);
    assert(out_fd == -1);
    assert(errno == EINVAL);

    syncobj_destroy(drm_fd, tl);
    close(drm_fd);
    printf("  [PASS] test_unsignaled_future_point_export (EINVAL returned, no fabrication)\n");
}

int main(void) {
    printf("Starting Sync Utility unit tests...\n");
    test_sync_file_validation();
    test_timeline_signal_wait();
    test_sync_file_timeline_import_export();
    test_syncobj_fd_transfer();
    test_unsignaled_future_point_export();
    printf("All Sync Utility unit tests PASSED!\n");
    return 0;
}
