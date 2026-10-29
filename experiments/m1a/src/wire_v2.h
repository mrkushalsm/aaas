#ifndef AAAS_WIRE_V2_H
#define AAAS_WIRE_V2_H

#include <stdint.h>
#include <stddef.h>

#define AAAS_V2_MAGIC 0x53414141u /* 'AAAS' */
#define AAAS_V2_VERSION 2u
#define AAAS_V2_MAX_FDS 4
#define AAAS_V2_MAX_DIM 8192u
#define AAAS_V2_MAX_PLANES 4

enum {
    AAAS_V2_HELLO   = 1,
    AAAS_V2_RESIZE  = 2,
    AAAS_V2_BUFFER  = 3,
    AAAS_V2_RELEASE = 4,
    AAAS_V2_CLOSE   = 5,
    /* Producer may reuse its source after the presenter has copied it into
     * presenter-owned storage; the Wayland buffer remains in flight. */
    AAAS_V2_COPY_COMPLETE = 6,
};

enum {
    AAAS_V2_FLAG_EXPLICIT_SYNC = (1 << 0), /* Buffer has acquire fence FD attached */
    AAAS_V2_FLAG_RELEASE_FENCE = (1 << 1), /* Release message has release fence FD attached */
    AAAS_V2_FLAG_LINEAR        = (1 << 2), /* Buffer uses linear memory layout */
    AAAS_V2_FLAG_COPY_COMPLETE = (1 << 3), /* HELLO/RESIZE capability */
};

typedef struct {
    uint32_t magic;           /* AAAS_V2_MAGIC */
    uint32_t version;         /* AAAS_V2_VERSION */
    uint32_t type;            /* AAAS_V2_* enum */
    uint32_t flags;           /* AAAS_V2_FLAG_* bitmask */
    uint32_t generation;      /* Window configure generation */
    uint32_t id;              /* Stable Buffer ID (1..N) */
    uint32_t width;           /* Width in pixels */
    uint32_t height;          /* Height in pixels */
    uint32_t format;          /* DRM fourcc format */
    uint32_t num_planes;      /* Number of planes (1..4) */
    uint64_t modifier;        /* DRM format modifier */
    uint32_t offset[AAAS_V2_MAX_PLANES]; /* Plane byte offsets */
    uint32_t stride[AAAS_V2_MAX_PLANES]; /* Plane pitch / strides */
    uint64_t timestamp_ns;    /* Monotonic timestamp in nanoseconds */
    uint32_t reserved[2];     /* Explicit zero padding for future extensions */
} __attribute__((packed)) aaas_v2_msg;

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Send an aaas_v2_msg along with optional file descriptors.
 * Does not close passed fds.
 * Returns 0 on success, -1 on error (errno set).
 */
int aaas_v2_send(int sock, const aaas_v2_msg *msg, const int *fds, unsigned nfds);

/**
 * Receive an aaas_v2_msg and any passed file descriptors.
 * On error, any received file descriptors are closed automatically and *nfds set to 0.
 * On success, the caller takes ownership of *nfds file descriptors in fds[].
 * Returns 1 on success, 0 on peer disconnect, -1 on error (errno set).
 */
int aaas_v2_recv(int sock, aaas_v2_msg *msg, int *fds, unsigned *nfds);

#ifdef __cplusplus
}
#endif

#endif /* AAAS_WIRE_V2_H */
