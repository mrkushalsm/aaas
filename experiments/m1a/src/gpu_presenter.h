#ifndef AAAS_GPU_PRESENTER_H
#define AAAS_GPU_PRESENTER_H

#include <stdint.h>
#include <stdbool.h>
#include <signal.h>

typedef struct {
    int sock;
    /* Optional listener used to accept a replacement Composer transport while
     * keeping this presenter's Wayland toplevel alive across Android resizes. */
    int producer_listen_fd;
    const char *title;
    const char *app_id;
    bool defer_map;
    uint32_t initial_width;
    uint32_t initial_height;
    uint32_t initial_display_width;
    uint32_t initial_display_height;
    uint32_t initial_generation;
    const char *drm_node;
    bool software_shm_test;
    bool test_reconnect_on_producer_close;
    bool force_implicit_sync;
    bool trace_buffer_identities;
    bool trace_staging_stages;
    bool trace_input_roi;
    uint32_t input_roi_x, input_roi_y, input_roi_width, input_roi_height;
    uint32_t max_frames; /* 0 for infinite */
    const volatile sig_atomic_t *running; /* optional signal-driven shutdown */

    /* Optional private input channel.  -1 disables pointer forwarding. */
    int input_listen_fd;
    uint64_t input_session_id;
    /* Optional file containing the Android display ID for this private output. */
    const char *input_display_id_file;
    const char *resize_request_path;
    const char *identity_request_path;
    const char *identity_ack_path;
} aaas_presenter_config;

/**
 * Run the Wayland presenter loop with explicit DRM syncobj support.
 * Binds linux-dmabuf-v1 and linux-drm-syncobj-v1, manages surface attachments,
 * timeline acquire/release points, and returns release fences to producer.
 * Returns 0 on clean exit, non-zero on error.
 */
int aaas_run_gpu_presenter(const aaas_presenter_config *config);

#endif /* AAAS_GPU_PRESENTER_H */
