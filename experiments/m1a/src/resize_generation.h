#ifndef AAAS_RESIZE_GENERATION_H
#define AAAS_RESIZE_GENERATION_H

#include <errno.h>
#include <ctype.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>

typedef struct {
    uint32_t generation;
    uint32_t width;
    uint32_t height;
} aaas_resize_resume_state;

/* A producer reconnect can outlive its Android display handle. Resume both
 * generation and the actual display size last published to the broker. */
static inline aaas_resize_resume_state aaas_read_resize_resume_state(const char *path) {
    aaas_resize_resume_state state = {0};
    if (!path || !path[0]) return state;
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return state;
    char value[64] = {0};
    ssize_t count = read(fd, value, sizeof(value) - 1);
    close(fd);
    if (count <= 0 || (size_t)count >= sizeof(value) - 1) return state;
    char *cursor = value;
    unsigned long parsed[3];
    for (size_t i = 0; i < 3; ++i) {
        while (isspace((unsigned char)*cursor)) cursor++;
        char *end = NULL;
        errno = 0;
        parsed[i] = strtoul(cursor, &end, 10);
        if (errno || end == cursor || parsed[i] > UINT32_MAX) return state;
        cursor = end;
    }
    while (isspace((unsigned char)*cursor)) cursor++;
    if (*cursor || parsed[0] >= UINT32_MAX || parsed[1] < 64 ||
        parsed[1] > 4096 || parsed[2] < 64 || parsed[2] > 4096) return state;
    state.generation = (uint32_t)parsed[0];
    state.width = (uint32_t)parsed[1];
    state.height = (uint32_t)parsed[2];
    return state;
}

#endif
