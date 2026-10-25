#include "sync_util.h"
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <errno.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <linux/sync_file.h>
#include <xf86drm.h>
#include <drm.h>

int sync_file_is_valid(int fd) {
    if (fd < 0) return 0;
    struct sync_file_info info = {0};
    if (ioctl(fd, SYNC_IOC_FILE_INFO, &info) < 0) {
        return 0;
    }
    return 1;
}

int sync_file_is_signaled(int fd) {
    if (fd < 0) return -1;
    struct sync_file_info info = {0};
    if (ioctl(fd, SYNC_IOC_FILE_INFO, &info) < 0) {
        return -1;
    }
    return info.status == 1 ? 1 : 0;
}

int sync_file_wait(int fd, int timeout_ms) {
    if (fd < 0) return -1;
    struct pollfd pfd = { .fd = fd, .events = POLLIN };
    int r = poll(&pfd, 1, timeout_ms);
    if (r > 0 && (pfd.revents & (POLLIN | POLLOUT))) return 1;
    if (r == 0) return 0; // timeout
    return -1; // error
}

int syncobj_create_timeline(int drm_fd, uint32_t *handle) {
    if (drm_fd < 0 || !handle) return -1;
    return drmSyncobjCreate(drm_fd, 0, handle);
}

void syncobj_destroy(int drm_fd, uint32_t handle) {
    if (drm_fd >= 0 && handle) {
        drmSyncobjDestroy(drm_fd, handle);
    }
}

int syncobj_handle_to_fd(int drm_fd, uint32_t handle, int *syncobj_fd) {
    if (drm_fd < 0 || !handle || !syncobj_fd) return -1;
    return drmSyncobjHandleToFD(drm_fd, handle, syncobj_fd);
}

int syncobj_fd_to_handle(int drm_fd, int syncobj_fd, uint32_t *handle) {
    if (drm_fd < 0 || syncobj_fd < 0 || !handle) return -1;
    return drmSyncobjFDToHandle(drm_fd, syncobj_fd, handle);
}

int syncobj_timeline_import_sync_file(int drm_fd, uint32_t timeline,
                                     uint64_t point, int sync_file_fd) {
    if (drm_fd < 0 || !timeline || sync_file_fd < 0) return -1;

    // Create a temporary binary syncobj
    uint32_t binary = 0;
    if (drmSyncobjCreate(drm_fd, 0, &binary) != 0) return -1;

    // Import the sync_file into the binary syncobj
    int r = drmSyncobjImportSyncFile(drm_fd, binary, sync_file_fd);
    if (r == 0) {
        // Transfer to the timeline at point
        r = drmSyncobjTransfer(drm_fd, timeline, point, binary, 0, 0);
    }

    drmSyncobjDestroy(drm_fd, binary);
    return r;
}

int syncobj_timeline_export_sync_file(int drm_fd, uint32_t timeline,
                                     uint64_t point, int *sync_file_fd) {
    if (drm_fd < 0 || !timeline || !sync_file_fd) return -1;

    uint32_t binary = 0;
    if (drmSyncobjCreate(drm_fd, 0, &binary) != 0) return -1;

    int r = drmSyncobjTransfer(drm_fd, binary, 0, timeline, point, 0);
    if (r == 0) {
        r = drmSyncobjExportSyncFile(drm_fd, binary, sync_file_fd);
    }

    drmSyncobjDestroy(drm_fd, binary);
    return r;
}

int syncobj_timeline_wait(int drm_fd, uint32_t timeline, uint64_t point,
                          uint64_t timeout_ns) {
    if (drm_fd < 0 || !timeline) return -1;
    uint32_t first_signaled = 0;
    uint32_t flags = DRM_SYNCOBJ_WAIT_FLAGS_WAIT_ALL | DRM_SYNCOBJ_WAIT_FLAGS_WAIT_FOR_SUBMIT;
    int64_t abs_timeout = 0;
    if (timeout_ns > 0) {
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        abs_timeout = (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec + (int64_t)timeout_ns;
    }
    return drmSyncobjTimelineWait(drm_fd, &timeline, &point, 1, abs_timeout,
                                  flags, &first_signaled);
}

int syncobj_timeline_signal(int drm_fd, uint32_t timeline, uint64_t point) {
    if (drm_fd < 0 || !timeline) return -1;
    return drmSyncobjTimelineSignal(drm_fd, &timeline, &point, 1);
}
