#include "wire_v2.h"
#include "sync_util.h"
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
#include <stdio.h>

static int is_dmabuf_fd(int fd) {
    if (fd < 0) return 0;
    struct stat st;
    if (fstat(fd, &st) < 0) return 0;
    char link[128], path[64];
    snprintf(path, sizeof(path), "/proc/self/fd/%d", fd);
    ssize_t len = readlink(path, link, sizeof(link) - 1);
    if (len < 0) return 0;
    link[len] = '\0';
    return (strncmp(link, "/dmabuf:", 8) == 0 ||
            strncmp(link, "anon_inode:[dmabuf]", 19) == 0);
}

static int validate_v2(const aaas_v2_msg *m, unsigned nfds) {
    if (m->magic != AAAS_V2_MAGIC || m->version != AAAS_V2_VERSION) {
        return 0;
    }
    if (m->reserved[0] != 0 || m->reserved[1] != 0) {
        return 0;
    }
    if (m->type < AAAS_V2_HELLO || m->type > AAAS_V2_CLOSE) {
        return 0;
    }

    switch (m->type) {
    case AAAS_V2_HELLO:
        return nfds == 0;

    case AAAS_V2_RESIZE:
        return nfds == 0 && m->generation && m->width && m->height &&
               m->width <= AAAS_V2_MAX_DIM && m->height <= AAAS_V2_MAX_DIM;

    case AAAS_V2_BUFFER: {
        if (!m->generation || !m->id || !m->width || !m->height ||
            m->width > AAAS_V2_MAX_DIM || m->height > AAAS_V2_MAX_DIM ||
            !m->format || !m->num_planes || m->num_planes > AAAS_V2_MAX_PLANES) {
            return 0;
        }
        for (uint32_t p = 0; p < m->num_planes; p++) {
            if (!m->stride[p]) return 0;
        }
        unsigned expected_fds = m->num_planes;
        if (m->flags & AAAS_V2_FLAG_EXPLICIT_SYNC) {
            expected_fds += 1; /* plane FDs + acquire fence FD */
        }
        return nfds == expected_fds;
    }

    case AAAS_V2_RELEASE: {
        if (!m->generation || !m->id) return 0;
        if (m->flags & AAAS_V2_FLAG_RELEASE_FENCE) {
            return nfds == 1; /* 1 release fence FD */
        }
        return nfds == 0;
    }

    case AAAS_V2_CLOSE:
        return nfds == 0;

    default:
        return 0;
    }
}

int aaas_v2_send(int sock, const aaas_v2_msg *msg, const int *fds, unsigned nfds) {
    if (nfds > AAAS_V2_MAX_FDS || !validate_v2(msg, nfds)) {
        errno = EINVAL;
        return -1;
    }
    struct iovec iov = {
        .iov_base = (void *)msg,
        .iov_len = sizeof(*msg)
    };
    char ctrl[CMSG_SPACE(sizeof(int) * AAAS_V2_MAX_FDS)] = {0};
    struct msghdr h = {
        .msg_iov = &iov,
        .msg_iovlen = 1
    };
    if (nfds > 0 && fds) {
        h.msg_control = ctrl;
        h.msg_controllen = CMSG_SPACE(sizeof(int) * nfds);
        struct cmsghdr *c = CMSG_FIRSTHDR(&h);
        c->cmsg_level = SOL_SOCKET;
        c->cmsg_type = SCM_RIGHTS;
        c->cmsg_len = CMSG_LEN(sizeof(int) * nfds);
        memcpy(CMSG_DATA(c), fds, sizeof(int) * nfds);
    }
    ssize_t r = sendmsg(sock, &h, MSG_NOSIGNAL);
    return r == (ssize_t)sizeof(*msg) ? 0 : -1;
}

int aaas_v2_recv(int sock, aaas_v2_msg *msg, int *fds, unsigned *nfds) {
    *nfds = 0;
    struct iovec iov = {
        .iov_base = msg,
        .iov_len = sizeof(*msg)
    };
    char ctrl[CMSG_SPACE(sizeof(int) * AAAS_V2_MAX_FDS)] = {0};
    struct msghdr h = {
        .msg_iov = &iov,
        .msg_iovlen = 1,
        .msg_control = ctrl,
        .msg_controllen = sizeof(ctrl)
    };
    ssize_t r = recvmsg(sock, &h, MSG_CMSG_CLOEXEC);
    if (r <= 0) {
        return (int)r;
    }

    // Extract any received FDs
    for (struct cmsghdr *c = CMSG_FIRSTHDR(&h); c; c = CMSG_NXTHDR(&h, c)) {
        if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SCM_RIGHTS) {
            unsigned k = (c->cmsg_len - CMSG_LEN(0)) / sizeof(int);
            int *p = (int *)CMSG_DATA(c);
            for (unsigned i = 0; i < k; i++) {
                if (*nfds < AAAS_V2_MAX_FDS) {
                    fds[(*nfds)++] = p[i];
                } else {
                    close(p[i]);
                }
            }
        }
    }

    // Header size, truncation, or protocol validation check
    if (r != (ssize_t)sizeof(*msg) || (h.msg_flags & (MSG_TRUNC | MSG_CTRUNC)) ||
        !validate_v2(msg, *nfds)) {
        for (unsigned i = 0; i < *nfds; i++) {
            close(fds[i]);
        }
        *nfds = 0;
        errno = EPROTO;
        return -1;
    }

    // Deep validation of file descriptors
    if (msg->type == AAAS_V2_BUFFER) {
        // Validate DMA-BUF FD(s)
        for (uint32_t p = 0; p < msg->num_planes; p++) {
            if (!is_dmabuf_fd(fds[p])) {
                for (unsigned i = 0; i < *nfds; i++) close(fds[i]);
                *nfds = 0;
                errno = EBADFD;
                return -1;
            }
        }
        // Validate acquire fence FD if present
        if (msg->flags & AAAS_V2_FLAG_EXPLICIT_SYNC) {
            int fence_fd = fds[msg->num_planes];
            if (!sync_file_is_valid(fence_fd)) {
                for (unsigned i = 0; i < *nfds; i++) close(fds[i]);
                *nfds = 0;
                errno = EBADFD;
                return -1;
            }
        }
    } else if (msg->type == AAAS_V2_RELEASE) {
        if (msg->flags & AAAS_V2_FLAG_RELEASE_FENCE) {
            int fence_fd = fds[0];
            if (!sync_file_is_valid(fence_fd)) {
                close(fence_fd);
                *nfds = 0;
                errno = EBADFD;
                return -1;
            }
        }
    }

    return 1;
}
