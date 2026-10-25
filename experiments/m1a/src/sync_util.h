#ifndef AAAS_SYNC_UTIL_H
#define AAAS_SYNC_UTIL_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Validate that an FD is a valid Linux sync_file.
 * Returns 1 if valid sync_file, 0 otherwise.
 */
int sync_file_is_valid(int fd);

/**
 * Check if a sync_file is already signaled (non-blocking).
 * Returns 1 if signaled, 0 if still active, -1 on error.
 */
int sync_file_is_signaled(int fd);

/**
 * Wait for a sync_file to signal with timeout in milliseconds.
 * Returns 1 if signaled, 0 on timeout, -1 on error.
 */
int sync_file_wait(int fd, int timeout_ms);

/**
 * Create a new DRM syncobj timeline.
 * Returns 0 on success, -1 on error.
 */
int syncobj_create_timeline(int drm_fd, uint32_t *handle);

/**
 * Destroy a DRM syncobj.
 */
void syncobj_destroy(int drm_fd, uint32_t handle);

/**
 * Export a DRM syncobj handle to an FD (for Wayland timeline import).
 */
int syncobj_handle_to_fd(int drm_fd, uint32_t handle, int *syncobj_fd);

/**
 * Import a DRM syncobj FD into a handle.
 */
int syncobj_fd_to_handle(int drm_fd, int syncobj_fd, uint32_t *handle);

/**
 * Import a sync_file FD into a timeline syncobj at a specific point.
 * Returns 0 on success, -1 on error.
 */
int syncobj_timeline_import_sync_file(int drm_fd, uint32_t timeline,
                                     uint64_t point, int sync_file_fd);

/**
 * Export a timeline syncobj point to a sync_file FD.
 * Returns 0 on success, -1 on error.
 */
int syncobj_timeline_export_sync_file(int drm_fd, uint32_t timeline,
                                     uint64_t point, int *sync_file_fd);

/**
 * Wait on a timeline syncobj point with timeout in nanoseconds.
 * Returns 0 if signaled, ETIME on timeout, -1 on error.
 */
int syncobj_timeline_wait(int drm_fd, uint32_t timeline, uint64_t point,
                          uint64_t timeout_ns);

/**
 * Manually signal a timeline point (for testing or immediate release).
 */
int syncobj_timeline_signal(int drm_fd, uint32_t timeline, uint64_t point);

#ifdef __cplusplus
}
#endif

#endif /* AAAS_SYNC_UTIL_H */
