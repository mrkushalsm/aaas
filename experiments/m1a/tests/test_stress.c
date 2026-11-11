#include "wire_v2.h"
#include "sync_util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <pthread.h>
#include <errno.h>
#include <assert.h>
#include <dirent.h>
#include <gbm.h>
#include <drm_fourcc.h>

static int open_render_node(void) {
    const char *node = getenv("AAAS_DRM_RENDER_NODE");
    if (!node || !*node) {
        fprintf(stderr, "Set AAAS_DRM_RENDER_NODE using host graphics discovery before this DRM-backed test.\n");
        return -1;
    }
    return open(node, O_RDWR | O_CLOEXEC);
}

static int count_open_fds(void) {
    DIR *d = opendir("/proc/self/fd");
    if (!d) return -1;
    int count = 0;
    struct dirent *de;
    while ((de = readdir(d)) != NULL) {
        if (de->d_name[0] != '.') count++;
    }
    closedir(d);
    return count;
}

// 1. Malformed packets & FD cleanup
static void test_malformed_packets(void) {
    int s[2];
    assert(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, s) == 0);

    // Corrupted magic
    aaas_v2_msg m = { .magic = 0x12345678, .version = AAAS_V2_VERSION, .type = AAAS_V2_HELLO };
    assert(aaas_v2_send(s[0], &m, NULL, 0) == -1);

    // Corrupted version
    m.magic = AAAS_V2_MAGIC; m.version = 1;
    assert(aaas_v2_send(s[0], &m, NULL, 0) == -1);

    // Reserved field non-zero
    m.version = AAAS_V2_VERSION; m.reserved[0] = 1;
    assert(aaas_v2_send(s[0], &m, NULL, 0) == -1);

    // Truncated raw bytes on socket
    uint32_t junk = AAAS_V2_MAGIC;
    assert(send(s[0], &junk, sizeof(junk), 0) == sizeof(junk));
    aaas_v2_msg out;
    int fds[AAAS_V2_MAX_FDS];
    unsigned nfds = 0;
    assert(aaas_v2_recv(s[1], &out, fds, &nfds) == -1);
    assert(errno == EPROTO);
    assert(nfds == 0);

    close(s[0]);
    close(s[1]);
    printf("  [PASS] test_malformed_packets\n");
}

// 2. Delayed acquire fence completion
typedef struct {
    int drm_fd;
    uint32_t syncobj;
    uint64_t point;
} delayed_signal_arg;

static void *delayed_signal_thread(void *arg) {
    delayed_signal_arg *d = (delayed_signal_arg *)arg;
    usleep(50000); // 50ms delay
    syncobj_timeline_signal(d->drm_fd, d->syncobj, d->point);
    return NULL;
}

static void test_delayed_acquire_fence(void) {
    int drm_fd = open_render_node();
    assert(drm_fd >= 0);

    uint32_t syncobj = 0;
    assert(syncobj_create_timeline(drm_fd, &syncobj) == 0);

    delayed_signal_arg d = { .drm_fd = drm_fd, .syncobj = syncobj, .point = 42 };
    pthread_t th;
    assert(pthread_create(&th, NULL, delayed_signal_thread, &d) == 0);

    // Wait on point 42: must block and succeed once signaled by thread
    assert(syncobj_timeline_wait(drm_fd, syncobj, 42, 500000000ULL) == 0);

    pthread_join(th, NULL);
    syncobj_destroy(drm_fd, syncobj);
    close(drm_fd);
    printf("  [PASS] test_delayed_acquire_fence\n");
}

// 3. Out-of-order release completion
static void test_out_of_order_release_handling(void) {
    int drm_fd = open_render_node();
    assert(drm_fd >= 0);

    // Create 3 independent release timelines for buffers 1, 2, 3
    uint32_t tl[3];
    for (int i = 0; i < 3; i++) {
        assert(syncobj_create_timeline(drm_fd, &tl[i]) == 0);
    }

    // Advance timeline 2 (buffer 3) first!
    assert(syncobj_timeline_signal(drm_fd, tl[2], 1) == 0);
    int fence_c = -1;
    assert(syncobj_timeline_export_sync_file(drm_fd, tl[2], 1, &fence_c) == 0);
    assert(fence_c >= 0);
    assert(sync_file_is_signaled(fence_c) == 1);

    // Verify buffer 1 timeline (tl[0]) and buffer 2 timeline (tl[1]) are STILL NOT SIGNALED!
    assert(syncobj_timeline_wait(drm_fd, tl[0], 1, 1000000ULL) != 0);
    assert(syncobj_timeline_wait(drm_fd, tl[1], 1, 1000000ULL) != 0);

    // Now signal buffer 1 (tl[0])
    assert(syncobj_timeline_signal(drm_fd, tl[0], 1) == 0);
    int fence_a = -1;
    assert(syncobj_timeline_export_sync_file(drm_fd, tl[0], 1, &fence_a) == 0);
    assert(fence_a >= 0);
    assert(sync_file_is_signaled(fence_a) == 1);

    // Buffer 2 (tl[1]) is still not signaled!
    assert(syncobj_timeline_wait(drm_fd, tl[1], 1, 1000000ULL) != 0);

    // Finally signal buffer 2 (tl[1])
    assert(syncobj_timeline_signal(drm_fd, tl[1], 1) == 0);
    int fence_b = -1;
    assert(syncobj_timeline_export_sync_file(drm_fd, tl[1], 1, &fence_b) == 0);
    assert(fence_b >= 0);
    assert(sync_file_is_signaled(fence_b) == 1);

    close(fence_a);
    close(fence_b);
    close(fence_c);
    for (int i = 0; i < 3; i++) syncobj_destroy(drm_fd, tl[i]);
    close(drm_fd);
    printf("  [PASS] test_out_of_order_release_handling\n");
}

// 4. File descriptor leak stress test
static void test_fd_leak_stress(void) {
    int initial_fds = count_open_fds();
    assert(initial_fds > 0);

    int s[2];
    assert(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, s) == 0);

    int drm_fd = open_render_node();
    assert(drm_fd >= 0);
    uint32_t tl = 0;
    assert(syncobj_create_timeline(drm_fd, &tl) == 0);

    // Perform 100 message sends and receives with fence FDs
    for (uint64_t i = 1; i <= 100; i++) {
        assert(syncobj_timeline_signal(drm_fd, tl, i) == 0);
        int fence_fd = -1;
        assert(syncobj_timeline_export_sync_file(drm_fd, tl, i, &fence_fd) == 0);

        aaas_v2_msg m = {
            .magic = AAAS_V2_MAGIC,
            .version = AAAS_V2_VERSION,
            .type = AAAS_V2_RELEASE,
            .flags = AAAS_V2_FLAG_RELEASE_FENCE,
            .generation = 1,
            .id = (uint32_t)i,
        };
        assert(aaas_v2_send(s[0], &m, &fence_fd, 1) == 0);
        close(fence_fd);

        aaas_v2_msg out;
        int recv_fds[AAAS_V2_MAX_FDS];
        unsigned nfds = 0;
        assert(aaas_v2_recv(s[1], &out, recv_fds, &nfds) == 1);
        assert(nfds == 1);
        close(recv_fds[0]);
    }

    syncobj_destroy(drm_fd, tl);
    close(drm_fd);
    close(s[0]);
    close(s[1]);

    int final_fds = count_open_fds();
    assert(final_fds == initial_fds);
    printf("  [PASS] test_fd_leak_stress (100 roundtrips: start_fds=%d, end_fds=%d)\n",
           initial_fds, final_fds);
}

// 5. Invalid syncobj descriptors & timeline points
static void test_invalid_syncobj_errors(void) {
    int drm_fd = open_render_node();
    assert(drm_fd >= 0);

    // Wait on non-existent handle (999999) must fail
    uint32_t bogus_handle = 999999;
    assert(syncobj_timeline_wait(drm_fd, bogus_handle, 1, 1000ULL) != 0);

    // Export non-existent handle
    int out_fd = -1;
    assert(syncobj_timeline_export_sync_file(drm_fd, bogus_handle, 1, &out_fd) != 0);

    // Import with invalid sync_file fd (-1)
    uint32_t valid_handle = 0;
    assert(syncobj_create_timeline(drm_fd, &valid_handle) == 0);
    assert(syncobj_timeline_import_sync_file(drm_fd, valid_handle, 1, -1) != 0);

    syncobj_destroy(drm_fd, valid_handle);
    close(drm_fd);
    printf("  [PASS] test_invalid_syncobj_errors\n");
}

// 6. Rapid resize generation changes
static void test_rapid_resize_generation(void) {
    int s[2];
    assert(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, s) == 0);

    for (uint32_t gen = 1; gen <= 50; gen++) {
        uint32_t w = 640 + (gen * 10) % 500;
        uint32_t h = 480 + (gen * 8) % 400;
        aaas_v2_msg m = {
            .magic = AAAS_V2_MAGIC,
            .version = AAAS_V2_VERSION,
            .type = AAAS_V2_RESIZE,
            .generation = gen,
            .width = w,
            .height = h,
        };
        assert(aaas_v2_send(s[0], &m, NULL, 0) == 0);

        aaas_v2_msg out;
        int recv_fds[AAAS_V2_MAX_FDS];
        unsigned nfds = 0;
        assert(aaas_v2_recv(s[1], &out, recv_fds, &nfds) == 1);
        assert(out.type == AAAS_V2_RESIZE);
        assert(out.generation == gen && out.width == w && out.height == h);
    }
    close(s[0]);
    close(s[1]);
    printf("  [PASS] test_rapid_resize_generation (50 generations verified)\n");
}

// 7. Duplicate buffer IDs & in-flight disconnect
static void test_disconnect_inflight(void) {
    int s[2];
    assert(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, s) == 0);

    int drm_fd = open_render_node();
    assert(drm_fd >= 0);
    struct gbm_device *gbm = gbm_create_device(drm_fd);
    assert(gbm != NULL);
    struct gbm_bo *bo = gbm_bo_create(gbm, 64, 64, GBM_FORMAT_XRGB8888, GBM_BO_USE_LINEAR);
    assert(bo != NULL);

    int dma_fd = gbm_bo_get_fd(bo);
    assert(dma_fd >= 0);

    uint32_t tl = 0;
    assert(syncobj_create_timeline(drm_fd, &tl) == 0);
    assert(syncobj_timeline_signal(drm_fd, tl, 1) == 0);
    int fence_fd = -1;
    assert(syncobj_timeline_export_sync_file(drm_fd, tl, 1, &fence_fd) == 0);

    aaas_v2_msg m = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_BUFFER,
        .flags = AAAS_V2_FLAG_EXPLICIT_SYNC,
        .generation = 1,
        .id = 100,
        .width = 64,
        .height = 64,
        .format = DRM_FORMAT_XRGB8888,
        .num_planes = 1,
        .stride = { gbm_bo_get_stride(bo) },
    };
    int send_fds[2] = { dma_fd, fence_fd };
    assert(aaas_v2_send(s[0], &m, send_fds, 2) == 0);
    close(dma_fd);
    close(fence_fd);

    // Abruptly close sender socket with buffer in-flight
    close(s[0]);

    // Receiver should receive the buffer, then detect disconnect on next read
    aaas_v2_msg out;
    int recv_fds[AAAS_V2_MAX_FDS];
    unsigned nfds = 0;
    assert(aaas_v2_recv(s[1], &out, recv_fds, &nfds) == 1);
    assert(out.id == 100);
    for (unsigned i = 0; i < nfds; i++) close(recv_fds[i]);

    // Next read returns 0 (EOF / disconnect)
    assert(aaas_v2_recv(s[1], &out, recv_fds, &nfds) == 0);

    close(s[1]);
    syncobj_destroy(drm_fd, tl);
    gbm_bo_destroy(bo);
    gbm_device_destroy(gbm);
    close(drm_fd);
    printf("  [PASS] test_disconnect_inflight\n");
}

int main(void) {
    printf("Starting M1A.1 GPU Synchronization Stress Tests...\n");
    test_malformed_packets();
    test_delayed_acquire_fence();
    test_out_of_order_release_handling();
    test_fd_leak_stress();
    test_invalid_syncobj_errors();
    test_rapid_resize_generation();
    test_disconnect_inflight();
    printf("All M1A.1 GPU Synchronization Stress Tests PASSED!\n");
    return 0;
}
