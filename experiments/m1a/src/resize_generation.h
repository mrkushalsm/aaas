#ifndef AAAS_RESIZE_GENERATION_H
#define AAAS_RESIZE_GENERATION_H

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>

/* A producer reconnect can outlive its Android display handle. Preserve the
 * last resize generation so its initial geometry is not rejected as stale. */
static inline uint32_t aaas_read_resize_generation_seed(const char *path) {
    if (!path || !path[0]) return 0;
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return 0;
    char value[64] = {0};
    ssize_t count = read(fd, value, sizeof(value) - 1);
    close(fd);
    if (count <= 0) return 0;
    char *end = NULL;
    errno = 0;
    unsigned long generation = strtoul(value, &end, 10);
    if (errno || end == value || generation >= UINT32_MAX) return 0;
    return (uint32_t)generation;
}

#endif
