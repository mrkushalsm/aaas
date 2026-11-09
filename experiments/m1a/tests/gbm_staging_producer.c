#include "wire_v2.h"

#include <drm_fourcc.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/un.h>
#include <unistd.h>

#define FRAME_WIDTH 320u
#define FRAME_HEIGHT 568u
#define FRAME_STRIDE (FRAME_WIDTH * 4u)
#define SOURCE_COUNT 2u
#define DEFAULT_FRAMES 160u
#define MAX_TEST_FRAMES 10000u

typedef struct {
    int fd;
    uint8_t *pixels;
    uint32_t id;
    bool busy;
} source_buffer;

static int connect_retry(const char *path) {
    for (unsigned attempt = 0; attempt < 100; attempt++) {
        int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
        if (fd < 0) return -1;
        struct sockaddr_un address = { .sun_family = AF_UNIX };
        if (strlen(path) >= sizeof(address.sun_path)) {
            close(fd);
            errno = ENAMETOOLONG;
            return -1;
        }
        strcpy(address.sun_path, path);
        if (connect(fd, (struct sockaddr *)&address, sizeof(address)) == 0)
            return fd;
        int saved_errno = errno;
        close(fd);
        if (saved_errno != ENOENT && saved_errno != ECONNREFUSED) {
            errno = saved_errno;
            return -1;
        }
        usleep(20000);
    }
    errno = ETIMEDOUT;
    return -1;
}

static int source_create(source_buffer *buffer, const char *name) {
    const size_t length = (size_t)FRAME_STRIDE * FRAME_HEIGHT;
    buffer->fd = memfd_create(name, MFD_CLOEXEC);
    if (buffer->fd < 0 || ftruncate(buffer->fd, (off_t)length) != 0)
        return -1;
    buffer->pixels = mmap(NULL, length, PROT_READ | PROT_WRITE, MAP_SHARED,
                          buffer->fd, 0);
    return buffer->pixels == MAP_FAILED ? -1 : 0;
}

static void source_paint(source_buffer *buffer, uint32_t frame) {
    for (uint32_t y = 0; y < FRAME_HEIGHT; y++) {
        uint32_t *row = (uint32_t *)(buffer->pixels + (size_t)y * FRAME_STRIDE);
        for (uint32_t x = 0; x < FRAME_WIDTH; x++) {
            uint8_t red = (uint8_t)(x + frame);
            uint8_t green = (uint8_t)(y + frame * 3u);
            uint8_t blue = (uint8_t)(x ^ y ^ frame);
            row[x] = 0xff000000u | ((uint32_t)red << 16) |
                     ((uint32_t)green << 8) | blue;
        }
    }
}

static int send_frame(int socket_fd, int dma_buf_fd, uint32_t generation,
                      uint32_t id) {
    aaas_v2_msg message = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_BUFFER,
        .flags = AAAS_V2_FLAG_LINEAR,
        .generation = generation,
        .id = id,
        .width = FRAME_WIDTH,
        .height = FRAME_HEIGHT,
        .format = DRM_FORMAT_XRGB8888,
        .num_planes = 1,
        .modifier = DRM_FORMAT_MOD_LINEAR,
        .stride = { FRAME_STRIDE },
    };
    return aaas_v2_send(socket_fd, &message, &dma_buf_fd, 1);
}

static unsigned source_busy_count(const source_buffer *buffers) {
    unsigned count = 0;
    for (unsigned i = 0; i < SOURCE_COUNT; i++) count += buffers[i].busy;
    return count;
}

int main(int argc, char **argv) {
    if (argc < 2 || argc > 6) {
        fprintf(stderr, "usage: %s SOCKET [FRAME_COUNT] [--probe-cap] "
                        "[--configure-delay-ms N]\n", argv[0]);
        return 2;
    }
    uint32_t frame_limit = DEFAULT_FRAMES;
    uint32_t configure_delay_ms = 0;
    bool probe_cap = false;
    for (int i = 2; i < argc; i++) {
        if (strcmp(argv[i], "--probe-cap") == 0) {
            probe_cap = true;
        } else if (strcmp(argv[i], "--configure-delay-ms") == 0 &&
                   i + 1 < argc) {
            char *end = NULL;
            unsigned long value = strtoul(argv[++i], &end, 10);
            if (!end || *end || value > 10000) return 2;
            configure_delay_ms = (uint32_t)value;
        } else {
            char *end = NULL;
            unsigned long value = strtoul(argv[i], &end, 10);
            if (!end || *end || value == 0 || value > MAX_TEST_FRAMES) return 2;
            frame_limit = (uint32_t)value;
        }
    }

    int socket_fd = connect_retry(argv[1]);
    if (socket_fd < 0) {
        perror("connect presenter");
        return 3;
    }
    struct timeval timeout = { .tv_sec = 20 };
    setsockopt(socket_fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));

    aaas_v2_msg hello = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_HELLO,
        .flags = AAAS_V2_FLAG_COPY_COMPLETE,
    };
    if (aaas_v2_send(socket_fd, &hello, NULL, 0) != 0) return 4;

    aaas_v2_msg reply = {0};
    int fds[AAAS_V2_MAX_FDS];
    unsigned nfds = 0;
    if (aaas_v2_recv(socket_fd, &reply, fds, &nfds) != 1 ||
        reply.type != AAAS_V2_RESIZE || nfds != 0 || !reply.generation ||
        !(reply.flags & AAAS_V2_FLAG_COPY_COMPLETE)) {
        fprintf(stderr, "presenter did not negotiate copy-complete staging\n");
        return 5;
    }
    if (configure_delay_ms) usleep(configure_delay_ms * 1000u);

    source_buffer sources[SOURCE_COUNT] = {0};
    for (unsigned i = 0; i < SOURCE_COUNT; i++) {
        sources[i].fd = -1;
        if (source_create(&sources[i], "aaas-gbm-stage-source") != 0) {
            perror("create source buffer");
            return 6;
        }
    }
    source_buffer cap_probe = { .fd = -1, .pixels = MAP_FAILED };
    if (probe_cap && source_create(&cap_probe, "aaas-gbm-cap-probe") != 0) {
        perror("create cap probe buffer");
        return 6;
    }

    const uint32_t cap_probe_id = frame_limit + 1;
    bool *awaiting_release = calloc((size_t)frame_limit + 2, sizeof(bool));
    if (!awaiting_release) return 7;
    uint32_t sent = 0, copy_complete = 0, actual_releases = 0;
    unsigned peak_source_inflight = 0;
    bool write_closed = false, cap_probe_sent = false, cap_probe_rejected = false;

    while (actual_releases < frame_limit) {
        for (unsigned i = 0; i < SOURCE_COUNT && sent < frame_limit; i++) {
            if (sources[i].busy) continue;
            uint32_t id = sent + 1;
            source_paint(&sources[i], id);
            if (send_frame(socket_fd, sources[i].fd, reply.generation, id) != 0) {
                perror("send frame");
                return 8;
            }
            sources[i].id = id;
            sources[i].busy = true;
            awaiting_release[id] = true;
            sent++;
            unsigned busy = source_busy_count(sources);
            if (busy > peak_source_inflight) peak_source_inflight = busy;
        }

        if (probe_cap && !cap_probe_sent && sent >= 4 &&
            source_busy_count(sources) == SOURCE_COUNT) {
            source_paint(&cap_probe, cap_probe_id);
            if (send_frame(socket_fd, cap_probe.fd, reply.generation,
                           cap_probe_id) != 0) {
                perror("send cap probe");
                return 9;
            }
            awaiting_release[cap_probe_id] = true;
            cap_probe_sent = true;
        }

        if (sent == frame_limit && !write_closed) {
            if (shutdown(socket_fd, SHUT_WR) != 0) {
                perror("shutdown producer write side");
                return 10;
            }
            write_closed = true;
        }

        struct pollfd poll_fd = { .fd = socket_fd, .events = POLLIN };
        int poll_result = poll(&poll_fd, 1, 20000);
        if (poll_result <= 0) {
            fprintf(stderr, "timeout sent=%u copy_complete=%u releases=%u\n",
                    sent, copy_complete, actual_releases);
            return 11;
        }
        nfds = 0;
        if (aaas_v2_recv(socket_fd, &reply, fds, &nfds) != 1) {
            fprintf(stderr, "presenter disconnected before release completion\n");
            return 12;
        }
        for (unsigned i = 0; i < nfds; i++) close(fds[i]);
        if (reply.type == AAAS_V2_CLOSE) break;
        if (reply.type == AAAS_V2_RESIZE) continue;

        if (cap_probe_sent && reply.id == cap_probe_id &&
            reply.type == AAAS_V2_RELEASE) {
            awaiting_release[cap_probe_id] = false;
            cap_probe_rejected = true;
            continue;
        }
        if (reply.id == 0 || reply.id > frame_limit ||
            !awaiting_release[reply.id]) {
            fprintf(stderr, "unexpected presenter response type=%u id=%u\n",
                    reply.type, reply.id);
            return 13;
        }
        source_buffer *source = NULL;
        for (unsigned i = 0; i < SOURCE_COUNT; i++) {
            if (sources[i].busy && sources[i].id == reply.id) source = &sources[i];
        }
        if (reply.type == AAAS_V2_COPY_COMPLETE) {
            if (source) source->busy = false;
            copy_complete++;
        } else if (reply.type == AAAS_V2_RELEASE) {
            if (source) source->busy = false;
            awaiting_release[reply.id] = false;
            actual_releases++;
        } else {
            fprintf(stderr, "unexpected presenter response type=%u\n", reply.type);
            return 14;
        }
    }

    printf("frames_sent=%u copy_complete=%u actual_wayland_releases=%u "
           "peak_source_inflight=%u cap_probe_sent=%s cap_probe_rejected=%s "
           "write_shutdown=%s outstanding_releases=%u\n",
           sent, copy_complete, actual_releases, peak_source_inflight,
           cap_probe_sent ? "true" : "false",
           cap_probe_rejected ? "true" : "false",
           write_closed ? "true" : "false",
           frame_limit - actual_releases);

    const size_t source_length = (size_t)FRAME_STRIDE * FRAME_HEIGHT;
    for (unsigned i = 0; i < SOURCE_COUNT; i++) {
        munmap(sources[i].pixels, source_length);
        close(sources[i].fd);
    }
    if (probe_cap) {
        munmap(cap_probe.pixels, source_length);
        close(cap_probe.fd);
    }
    free(awaiting_release);
    close(socket_fd);
    return sent == frame_limit && actual_releases == frame_limit &&
           (!probe_cap || cap_probe_rejected) ? 0 : 15;
}
