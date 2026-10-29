#include "wire_v2.h"
#include "sync_util.h"
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/socket.h>
#include <fcntl.h>
#include <assert.h>
#include <errno.h>
#include <drm_fourcc.h>
#include <gbm.h>

static int open_render_node(void) {
    int fd = open("/dev/dri/renderD129", O_RDWR | O_CLOEXEC);
    if (fd < 0) fd = open("/dev/dri/renderD128", O_RDWR | O_CLOEXEC);
    return fd;
}

static void test_hello_roundtrip(int s[2]) {
    aaas_v2_msg m = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_HELLO,
    };
    assert(aaas_v2_send(s[0], &m, NULL, 0) == 0);

    aaas_v2_msg out = {0};
    int fds[AAAS_V2_MAX_FDS];
    unsigned nfds = 0;
    assert(aaas_v2_recv(s[1], &out, fds, &nfds) == 1);
    assert(out.type == AAAS_V2_HELLO);
    assert(nfds == 0);
    printf("  [PASS] test_hello_roundtrip\n");
}

static void test_copy_complete_roundtrip(int s[2]) {
    aaas_v2_msg m = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_COPY_COMPLETE,
        .generation = 7,
        .id = 123,
    };
    assert(aaas_v2_send(s[0], &m, NULL, 0) == 0);

    aaas_v2_msg out = {0};
    int fds[AAAS_V2_MAX_FDS];
    unsigned nfds = 0;
    assert(aaas_v2_recv(s[1], &out, fds, &nfds) == 1);
    assert(out.type == AAAS_V2_COPY_COMPLETE);
    assert(out.generation == m.generation && out.id == m.id);
    assert(nfds == 0);

    m.id = 0;
    assert(aaas_v2_send(s[0], &m, NULL, 0) == -1);
    assert(errno == EINVAL);
    m.id = 123;
    int pipefds[2];
    assert(pipe(pipefds) == 0);
    assert(aaas_v2_send(s[0], &m, &pipefds[0], 1) == -1);
    assert(errno == EINVAL);
    close(pipefds[0]);
    close(pipefds[1]);
    printf("  [PASS] test_copy_complete_roundtrip\n");
}

static void test_resize_validation(int s[2]) {
    aaas_v2_msg m = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_RESIZE,
        .generation = 1,
        .width = 1280,
        .height = 720,
    };
    assert(aaas_v2_send(s[0], &m, NULL, 0) == 0);

    aaas_v2_msg out = {0};
    int fds[AAAS_V2_MAX_FDS];
    unsigned nfds = 0;
    assert(aaas_v2_recv(s[1], &out, fds, &nfds) == 1);
    assert(out.width == 1280 && out.height == 720 && out.generation == 1);

    // Oversized dimension must fail
    m.width = 99999;
    assert(aaas_v2_send(s[0], &m, NULL, 0) == -1);
    assert(errno == EINVAL);
    printf("  [PASS] test_resize_validation\n");
}

static void test_invalid_version_rejection(int s[2]) {
    aaas_v2_msg m = {
        .magic = AAAS_V2_MAGIC,
        .version = 999, /* Invalid */
        .type = AAAS_V2_HELLO,
    };
    assert(aaas_v2_send(s[0], &m, NULL, 0) == -1);
    assert(errno == EINVAL);
    printf("  [PASS] test_invalid_version_rejection\n");
}

static void test_buffer_transfer_with_sync(int s[2]) {
    int drm_fd = open_render_node();
    assert(drm_fd >= 0);
    struct gbm_device *gbm = gbm_create_device(drm_fd);
    assert(gbm != NULL);

    struct gbm_bo *bo = gbm_bo_create(gbm, 64, 64, GBM_FORMAT_XRGB8888, GBM_BO_USE_LINEAR);
    assert(bo != NULL);
    int dma_fd = gbm_bo_get_fd(bo);
    assert(dma_fd >= 0);

    // Create a dummy signaled sync_file
    uint32_t syncobj = 0;
    assert(syncobj_create_timeline(drm_fd, &syncobj) == 0);
    assert(syncobj_timeline_signal(drm_fd, syncobj, 1) == 0);
    int fence_fd = -1;
    assert(syncobj_timeline_export_sync_file(drm_fd, syncobj, 1, &fence_fd) == 0);
    assert(fence_fd >= 0);
    assert(sync_file_is_valid(fence_fd) == 1);

    aaas_v2_msg m = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_BUFFER,
        .flags = AAAS_V2_FLAG_EXPLICIT_SYNC,
        .generation = 1,
        .id = 42,
        .width = 64,
        .height = 64,
        .format = DRM_FORMAT_XRGB8888,
        .num_planes = 1,
        .modifier = gbm_bo_get_modifier(bo),
        .offset = {0},
        .stride = {gbm_bo_get_stride(bo)},
    };
    int send_fds[2] = {dma_fd, fence_fd};
    assert(aaas_v2_send(s[0], &m, send_fds, 2) == 0);

    aaas_v2_msg out = {0};
    int recv_fds[AAAS_V2_MAX_FDS];
    unsigned nfds = 0;
    assert(aaas_v2_recv(s[1], &out, recv_fds, &nfds) == 1);
    assert(out.id == 42 && out.generation == 1);
    assert(out.flags & AAAS_V2_FLAG_EXPLICIT_SYNC);
    assert(nfds == 2);
    assert(recv_fds[0] >= 0);
    assert(recv_fds[1] >= 0);
    assert(sync_file_is_valid(recv_fds[1]) == 1);

    close(recv_fds[0]);
    close(recv_fds[1]);
    close(dma_fd);
    close(fence_fd);
    syncobj_destroy(drm_fd, syncobj);
    gbm_bo_destroy(bo);
    gbm_device_destroy(gbm);
    close(drm_fd);
    printf("  [PASS] test_buffer_transfer_with_sync\n");
}

static void test_release_with_fence(int s[2]) {
    int drm_fd = open_render_node();
    assert(drm_fd >= 0);
    uint32_t syncobj = 0;
    assert(syncobj_create_timeline(drm_fd, &syncobj) == 0);
    assert(syncobj_timeline_signal(drm_fd, syncobj, 1) == 0);
    int fence_fd = -1;
    assert(syncobj_timeline_export_sync_file(drm_fd, syncobj, 1, &fence_fd) == 0);
    assert(fence_fd >= 0);

    aaas_v2_msg m = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_RELEASE,
        .flags = AAAS_V2_FLAG_RELEASE_FENCE,
        .generation = 1,
        .id = 42,
    };
    assert(aaas_v2_send(s[0], &m, &fence_fd, 1) == 0);

    aaas_v2_msg out = {0};
    int recv_fds[AAAS_V2_MAX_FDS];
    unsigned nfds = 0;
    assert(aaas_v2_recv(s[1], &out, recv_fds, &nfds) == 1);
    assert(out.type == AAAS_V2_RELEASE);
    assert(out.id == 42);
    assert(nfds == 1);
    assert(sync_file_is_valid(recv_fds[0]) == 1);

    close(recv_fds[0]);
    close(fence_fd);
    syncobj_destroy(drm_fd, syncobj);
    close(drm_fd);
    printf("  [PASS] test_release_with_fence\n");
}

static void test_bad_fd_cleanup(int s[2]) {
    // Send a regular pipe FD instead of a sync_file with AAAS_V2_RELEASE
    int pipefds[2];
    assert(pipe(pipefds) == 0);

    aaas_v2_msg m = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_RELEASE,
        .flags = AAAS_V2_FLAG_RELEASE_FENCE,
        .generation = 1,
        .id = 10,
    };
    assert(aaas_v2_send(s[0], &m, &pipefds[0], 1) == 0);

    aaas_v2_msg out = {0};
    int recv_fds[AAAS_V2_MAX_FDS];
    unsigned nfds = 0;
    // Receiver must reject because pipefds[0] is not a valid sync_file!
    assert(aaas_v2_recv(s[1], &out, recv_fds, &nfds) == -1);
    assert(errno == EBADFD);
    assert(nfds == 0);

    close(pipefds[0]);
    close(pipefds[1]);
    printf("  [PASS] test_bad_fd_cleanup\n");
}

int main(void) {
    printf("Starting Wire Protocol v2 unit tests...\n");
    int s[2];
    assert(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, s) == 0);

    test_hello_roundtrip(s);
    test_copy_complete_roundtrip(s);
    test_resize_validation(s);
    test_invalid_version_rejection(s);
    test_buffer_transfer_with_sync(s);
    test_release_with_fence(s);
    test_bad_fd_cleanup(s);

    close(s[0]);
    close(s[1]);
    printf("All Wire Protocol v2 unit tests PASSED!\n");
    return 0;
}
