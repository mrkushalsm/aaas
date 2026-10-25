#ifndef AAAS_GPU_PRODUCER_H
#define AAAS_GPU_PRODUCER_H

#include <stdint.h>
#include <stdbool.h>

#define AAAS_PRODUCER_NUM_BUFFERS 4

typedef struct {
    int sock;
    const char *drm_node;
    bool cpu_fallback;
    uint32_t max_frames; /* 0 for infinite */
} aaas_producer_config;

/**
 * Run the GPU producer loop.
 * Renders frames asynchronously via GLES, exports acquire fences,
 * waits on release fences before reusing buffers, and sends frames to presenter.
 * Returns 0 on clean exit, non-zero on error.
 */
int aaas_run_gpu_producer(const aaas_producer_config *config);

#endif /* AAAS_GPU_PRODUCER_H */
