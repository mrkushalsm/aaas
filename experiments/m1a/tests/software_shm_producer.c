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
#include <sys/un.h>
#include <sys/time.h>
#include <unistd.h>

#define WIDTH 320u
#define HEIGHT 568u
#define STRIDE (WIDTH * 4u)
#define BUFFER_COUNT 2u

typedef struct {
    int fd;
    uint8_t *pixels;
    uint32_t id;
    bool busy;
} test_buffer;

static int connect_retry(const char *path) {
    for (unsigned attempt = 0; attempt < 100; attempt++) {
        int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
        if (fd < 0) return -1;
        struct sockaddr_un addr = { .sun_family = AF_UNIX };
        if (strlen(path) >= sizeof(addr.sun_path)) {
            close(fd);
            errno = ENAMETOOLONG;
            return -1;
        }
        strcpy(addr.sun_path, path);
        if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) == 0) return fd;
        int saved = errno;
        close(fd);
        if (saved != ENOENT && saved != ECONNREFUSED) {
            errno = saved;
            return -1;
        }
        usleep(20000);
    }
    errno = ETIMEDOUT;
    return -1;
}

static void paint(test_buffer *buffer, uint32_t frame) {
    for (uint32_t y = 0; y < HEIGHT; y++) {
        uint32_t *row = (uint32_t *)(buffer->pixels + (size_t)y * STRIDE);
        for (uint32_t x = 0; x < WIDTH; x++) {
            uint8_t r = (uint8_t)(x + frame);
            uint8_t g = (uint8_t)(y + frame * 3u);
            uint8_t b = (uint8_t)(x ^ y ^ frame);
            row[x] = 0xff000000u | ((uint32_t)r << 16) |
                     ((uint32_t)g << 8) | b;
        }
    }
}

static unsigned busy_count(const test_buffer *buffers) {
    unsigned count = 0;
    for (uint32_t i = 0; i < BUFFER_COUNT; i++) count += buffers[i].busy;
    return count;
}

static int send_frame(int sock, test_buffer *buffer, uint32_t generation,
                      uint32_t frame) {
    paint(buffer, frame);
    aaas_v2_msg msg = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_BUFFER,
        .flags = AAAS_V2_FLAG_LINEAR,
        .generation = generation,
        .id = buffer->id,
        .width = WIDTH,
        .height = HEIGHT,
        .format = DRM_FORMAT_ARGB8888,
        .num_planes = 1,
        .modifier = DRM_FORMAT_MOD_LINEAR,
        .stride = { STRIDE },
    };
    if (aaas_v2_send(sock, &msg, &buffer->fd, 1) != 0) return -1;
    buffer->busy = true;
    return 0;
}

int main(int argc, char **argv) {
    bool disconnect_after_send = argc == 4 &&
        strcmp(argv[3], "--disconnect-after-send") == 0;
    if ((argc != 3 && argc != 4) || (argc == 4 && !disconnect_after_send)) {
        fprintf(stderr, "usage: %s IPC_SOCKET FRAME_COUNT [--disconnect-after-send]\n", argv[0]);
        return 2;
    }
    char *end = NULL;
    unsigned long requested = strtoul(argv[2], &end, 10);
    if (!end || *end || requested == 0 || requested > 100000) return 2;
    const uint32_t frame_limit = (uint32_t)requested;
    if (disconnect_after_send && frame_limit > BUFFER_COUNT) {
        fprintf(stderr, "disconnect mode supports at most %u frames\n", BUFFER_COUNT);
        return 2;
    }

    int sock = connect_retry(argv[1]);
    if (sock < 0) {
        perror("connect presenter");
        return 3;
    }
    struct timeval timeout = { .tv_sec = 30 };
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));

    aaas_v2_msg hello = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_HELLO,
    };
    if (aaas_v2_send(sock, &hello, NULL, 0) != 0) return 4;
    aaas_v2_msg reply = {0};
    int fds[AAAS_V2_MAX_FDS];
    unsigned nfds = 0;
    if (aaas_v2_recv(sock, &reply, fds, &nfds) != 1 ||
        reply.type != AAAS_V2_RESIZE || nfds != 0 || reply.generation == 0) {
        fprintf(stderr, "invalid presenter HELLO response\n");
        return 5;
    }

    test_buffer buffers[BUFFER_COUNT] = {0};
    for (uint32_t i = 0; i < BUFFER_COUNT; i++) {
        buffers[i].id = i + 1;
        buffers[i].fd = memfd_create("aaas-shm-frame", MFD_CLOEXEC | MFD_ALLOW_SEALING);
        size_t length = (size_t)STRIDE * HEIGHT;
        if (buffers[i].fd < 0 || ftruncate(buffers[i].fd, (off_t)length) != 0) {
            perror("create test memfd");
            return 6;
        }
        buffers[i].pixels = mmap(NULL, length, PROT_READ | PROT_WRITE,
                                 MAP_SHARED, buffers[i].fd, 0);
        if (buffers[i].pixels == MAP_FAILED) {
            perror("map test memfd");
            return 7;
        }
    }

    uint32_t sent = 0, released = 0, max_in_flight = 0;
    for (uint32_t i = 0; i < BUFFER_COUNT && sent < frame_limit; i++) {
        if (send_frame(sock, &buffers[i], reply.generation, sent + 1) != 0) {
            perror("send initial frame");
            return 8;
        }
        sent++;
        if (busy_count(buffers) > max_in_flight) max_in_flight = busy_count(buffers);
    }

    if (disconnect_after_send) {
        printf("frames_sent=%u producer_disconnected=true generation=%u\n",
               sent, reply.generation);
        for (uint32_t i = 0; i < BUFFER_COUNT; i++) {
            munmap(buffers[i].pixels, (size_t)STRIDE * HEIGHT);
            close(buffers[i].fd);
        }
        close(sock);
        return sent == frame_limit ? 0 : 15;
    }

    bool producer_done = false, peer_closed = false;
    while (released < frame_limit) {
        /* Stop writing after the final frame, but keep the read side alive.
         * The presenter then detaches its surface during orderly teardown;
         * the compositor can release the last attached buffer before CLOSE. */
        if (!producer_done && sent == frame_limit &&
            released + 1 == frame_limit) {
            if (shutdown(sock, SHUT_WR) != 0) {
                perror("finish producer stream");
                return 14;
            }
            producer_done = true;
        }
        struct pollfd pfd = { .fd = sock, .events = POLLIN };
        int rc = poll(&pfd, 1, 30000);
        if (rc <= 0) {
            fprintf(stderr, "timeout waiting for compositor release\n");
            return 9;
        }
        aaas_v2_msg msg = {0};
        nfds = 0;
        int result = aaas_v2_recv(sock, &msg, fds, &nfds);
        if (result != 1) {
            fprintf(stderr, "presenter disconnected before all releases\n");
            return 10;
        }
        for (unsigned i = 0; i < nfds; i++) close(fds[i]);
        if (msg.type == AAAS_V2_CLOSE) {
            peer_closed = true;
            break;
        }
        if (msg.type != AAAS_V2_RELEASE) continue;
        test_buffer *buffer = NULL;
        for (uint32_t i = 0; i < BUFFER_COUNT; i++) {
            if (buffers[i].busy && buffers[i].id == msg.id) buffer = &buffers[i];
        }
        if (!buffer || msg.generation != reply.generation || nfds != 0) {
            fprintf(stderr, "unexpected or duplicate producer release\n");
            return 11;
        }
        buffer->busy = false;
        released++;
        if (sent < frame_limit) {
            if (send_frame(sock, buffer, reply.generation, sent + 1) != 0) {
                perror("send reused frame");
                return 12;
            }
            sent++;
            if (busy_count(buffers) > max_in_flight) max_in_flight = busy_count(buffers);
        }
    }

    unsigned outstanding = busy_count(buffers);
    printf("frames_sent=%u actual_wayland_releases=%u outstanding=%u "
           "max_in_flight=%u peer_closed=%s generation=%u\n",
           sent, released, outstanding, max_in_flight,
           peer_closed ? "true" : "false", reply.generation);
    for (uint32_t i = 0; i < BUFFER_COUNT; i++) {
        munmap(buffers[i].pixels, (size_t)STRIDE * HEIGHT);
        close(buffers[i].fd);
    }
    close(sock);
    return sent == frame_limit && released + outstanding == frame_limit &&
        outstanding <= 1 && (outstanding == 0 || peer_closed) ? 0 : 13;
}
