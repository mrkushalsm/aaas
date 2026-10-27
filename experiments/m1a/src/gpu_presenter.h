#ifndef AAAS_GPU_PRESENTER_H
#define AAAS_GPU_PRESENTER_H

#include <stdint.h>
#include <stdbool.h>
#include <signal.h>

typedef struct {
    int sock;
    const char *title;
    uint32_t initial_width;
    uint32_t initial_height;
    const char *drm_node;
    bool force_implicit_sync;
    uint32_t max_frames; /* 0 for infinite */
    const volatile sig_atomic_t *running; /* optional signal-driven shutdown */

    /* Optional private input channel.  -1 disables pointer forwarding. */
    int input_listen_fd;
    uint64_t input_session_id;
} aaas_presenter_config;

/**
 * Run the Wayland presenter loop with explicit DRM syncobj support.
 * Binds linux-dmabuf-v1 and linux-drm-syncobj-v1, manages surface attachments,
 * timeline acquire/release points, and returns release fences to producer.
 * Returns 0 on clean exit, non-zero on error.
 */
int aaas_run_gpu_presenter(const aaas_presenter_config *config);

#endif /* AAAS_GPU_PRESENTER_H */
