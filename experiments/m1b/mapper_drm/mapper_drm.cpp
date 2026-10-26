/*
 * Native DRM/DMA-BUF Mapper 5 Stable-C HAL Implementation for AaaS M1B.5
 *
 * Implements Android 16 AIMapper Stable-C ABI (Mapper 5)
 * backed by real Linux DRM dumb buffers / DMA-BUF / shared memory.
 * Freestanding implementation linking directly with Bionic libc and libcutils.
 */

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <poll.h>
#include <pthread.h>

#include <android/rect.h>
#include <cutils/native_handle.h>
#include <android/hardware/graphics/mapper/IMapper.h>

// Android Standard Metadata Types (from StandardMetadataType.aidl)
enum StandardMetadataType : int64_t {
    METADATA_INVALID = 0,
    METADATA_BUFFER_ID = 1,
    METADATA_NAME = 2,
    METADATA_WIDTH = 3,
    METADATA_HEIGHT = 4,
    METADATA_LAYER_COUNT = 5,
    METADATA_PIXEL_FORMAT_REQUESTED = 6,
    METADATA_PIXEL_FORMAT_FOURCC = 7,
    METADATA_PIXEL_FORMAT_MODIFIER = 8,
    METADATA_USAGE = 9,
    METADATA_ALLOCATION_SIZE = 10,
    METADATA_PROTECTED_CONTENT = 11,
    METADATA_COMPRESSION = 12,
    METADATA_INTERLACED = 13,
    METADATA_CHROMA_SITING = 14,
    METADATA_PLANE_LAYOUTS = 15,
    METADATA_CROP = 16,
    METADATA_DATASPACE = 17,
    METADATA_BLEND_MODE = 18,
    METADATA_SMPTE2086 = 19,
    METADATA_CTA861_3 = 20,
    METADATA_SMPTE2094_40 = 21,
    METADATA_SMPTE2094_10 = 22,
    METADATA_STRIDE = 23,
};

static const char* STANDARD_METADATA_NAME = "android.hardware.graphics.common.StandardMetadataType";

// Standard DRM FOURCC definitions
#ifndef DRM_FORMAT_ABGR8888
#define DRM_FORMAT_ABGR8888 0x34324241
#endif
#ifndef DRM_FORMAT_RGBA8888
#define DRM_FORMAT_RGBA8888 0x34324152
#endif
#ifndef DRM_FORMAT_RGBX8888
#define DRM_FORMAT_RGBX8888 0x34325852
#endif
#ifndef DRM_FORMAT_BGRA8888
#define DRM_FORMAT_BGRA8888 0x34324142
#endif
#ifndef DRM_FORMAT_XBGR8888
#define DRM_FORMAT_XBGR8888 0x34324258
#endif
#ifndef DRM_FORMAT_ARGB8888
#define DRM_FORMAT_ARGB8888 0x34325241
#endif
#ifndef DRM_FORMAT_RGB565
#define DRM_FORMAT_RGB565   0x36314752
#endif
#ifndef DRM_FORMAT_MOD_LINEAR
#define DRM_FORMAT_MOD_LINEAR 0ULL
#endif

#define AAAS_MAGIC 0x61616173
#define MAX_IMPORTED_BUFFERS 1024

struct ImportedBuffer {
    buffer_handle_t handle;
    native_handle_t* cloned_nh;
    int fd;
    uint32_t width;
    uint32_t height;
    uint32_t stride;
    int32_t format;
    uint64_t usage;
    uint64_t size;
    uint64_t buffer_id;
    int32_t dataspace;
    int32_t blend_mode;
    void* mapped_addr;
    size_t mapped_size;
    bool in_use;
};

static pthread_mutex_t g_mutex = PTHREAD_MUTEX_INITIALIZER;
static ImportedBuffer g_buffers[MAX_IMPORTED_BUFFERS];
static uint64_t g_next_id = 100;

static int parse_handle(const native_handle_t* handle, ImportedBuffer* out) {
    if (!handle || handle->numFds < 1) return -1;
    out->fd = handle->data[0];
    if (handle->numInts >= 10 && (uint32_t)handle->data[handle->numFds] == AAAS_MAGIC) {
        out->width = (uint32_t)handle->data[handle->numFds + 1];
        out->height = (uint32_t)handle->data[handle->numFds + 2];
        out->stride = (uint32_t)handle->data[handle->numFds + 3];
        out->format = handle->data[handle->numFds + 4];
        out->usage = ((uint64_t)(uint32_t)handle->data[handle->numFds + 6] << 32) |
                     (uint32_t)handle->data[handle->numFds + 5];
        out->size = (uint32_t)handle->data[handle->numFds + 7];
        out->buffer_id = ((uint64_t)(uint32_t)handle->data[handle->numFds + 9] << 32) |
                         (uint32_t)handle->data[handle->numFds + 8];
    } else {
        // Fallback default
        out->width = 1920;
        out->height = 1080;
        out->stride = 1920;
        out->format = 1; // RGBA_8888
        out->usage = 0;
        out->size = (uint64_t)out->stride * out->height * 4;
        out->buffer_id = ++g_next_id;
    }
    out->dataspace = 0;
    out->blend_mode = 1;
    out->mapped_addr = NULL;
    out->mapped_size = 0;
    return 0;
}

static uint32_t drm_fourcc_from_hal(int32_t format) {
    switch (format) {
        case 1: return DRM_FORMAT_RGBA8888;
        case 2: return DRM_FORMAT_RGBX8888;
        case 4: return DRM_FORMAT_RGB565;
        case 5: return DRM_FORMAT_BGRA8888;
        default: return DRM_FORMAT_ABGR8888;
    }
}

static void kmsg_log(const char* msg) {
    int fd = open("/dev/kmsg", O_WRONLY);
    if (fd >= 0) {
        write(fd, msg, strlen(msg));
        close(fd);
    }
}

// 1. importBuffer
static AIMapper_Error mapper_importBuffer(const native_handle_t* handle,
                                          buffer_handle_t* outBufferHandle) {
    kmsg_log("<6>[MAPPER.DRM] mapper_importBuffer called\n");
    if (!handle || !outBufferHandle) return AIMAPPER_ERROR_BAD_BUFFER;

    native_handle_t* cloned = native_handle_clone(handle);
    if (!cloned) return AIMAPPER_ERROR_NO_RESOURCES;

    ImportedBuffer buf;
    memset(&buf, 0, sizeof(buf));
    if (parse_handle(cloned, &buf) < 0) {
        native_handle_close(cloned);
        native_handle_delete(cloned);
        return AIMAPPER_ERROR_BAD_BUFFER;
    }
    buf.handle = cloned;
    buf.cloned_nh = cloned;
    buf.in_use = true;

    pthread_mutex_lock(&g_mutex);
    int slot = -1;
    for (int i = 0; i < MAX_IMPORTED_BUFFERS; i++) {
        if (!g_buffers[i].in_use) {
            slot = i;
            break;
        }
    }
    if (slot < 0) {
        pthread_mutex_unlock(&g_mutex);
        native_handle_close(cloned);
        native_handle_delete(cloned);
        return AIMAPPER_ERROR_NO_RESOURCES;
    }

    g_buffers[slot] = buf;
    pthread_mutex_unlock(&g_mutex);

    *outBufferHandle = cloned;
    return AIMAPPER_ERROR_NONE;
}

// 2. freeBuffer
static AIMapper_Error mapper_freeBuffer(buffer_handle_t buffer) {
    if (!buffer) return AIMAPPER_ERROR_BAD_BUFFER;

    native_handle_t* to_close = NULL;
    void* to_unmap = NULL;
    size_t to_unmap_sz = 0;

    pthread_mutex_lock(&g_mutex);
    for (int i = 0; i < MAX_IMPORTED_BUFFERS; i++) {
        if (g_buffers[i].in_use && g_buffers[i].handle == buffer) {
            to_close = g_buffers[i].cloned_nh;
            to_unmap = g_buffers[i].mapped_addr;
            to_unmap_sz = g_buffers[i].mapped_size;
            memset(&g_buffers[i], 0, sizeof(g_buffers[i]));
            break;
        }
    }
    pthread_mutex_unlock(&g_mutex);

    if (to_unmap) munmap(to_unmap, to_unmap_sz);
    if (to_close) {
        native_handle_close(to_close);
        native_handle_delete(to_close);
    }
    return AIMAPPER_ERROR_NONE;
}

// 3. getTransportSize
static AIMapper_Error mapper_getTransportSize(buffer_handle_t buffer,
                                              uint32_t* outNumFds,
                                              uint32_t* outNumInts) {
    if (!buffer || !outNumFds || !outNumInts) return AIMAPPER_ERROR_BAD_BUFFER;
    *outNumFds = (uint32_t)buffer->numFds;
    *outNumInts = (uint32_t)buffer->numInts;
    return AIMAPPER_ERROR_NONE;
}

// 4. lock
static AIMapper_Error mapper_lock(buffer_handle_t buffer, uint64_t cpuUsage,
                                  ARect accessRegion, int fence,
                                  void** outData) {
    (void)cpuUsage;
    (void)accessRegion;
    if (!buffer || !outData) return AIMAPPER_ERROR_BAD_BUFFER;

    if (fence >= 0) {
        struct pollfd pfd;
        pfd.fd = fence;
        pfd.events = POLLIN;
        pfd.revents = 0;
        poll(&pfd, 1, 3000);
        close(fence);
    }

    pthread_mutex_lock(&g_mutex);
    ImportedBuffer* b = NULL;
    for (int i = 0; i < MAX_IMPORTED_BUFFERS; i++) {
        if (g_buffers[i].in_use && g_buffers[i].handle == buffer) {
            b = &g_buffers[i];
            break;
        }
    }
    if (!b) {
        pthread_mutex_unlock(&g_mutex);
        return AIMAPPER_ERROR_BAD_BUFFER;
    }

    if (!b->mapped_addr) {
        size_t sz = b->size;
        if (sz == 0) sz = (size_t)b->stride * b->height * 4;
        void* ptr = mmap(NULL, sz, PROT_READ | PROT_WRITE, MAP_SHARED, b->fd, 0);
        if (ptr == MAP_FAILED) {
            pthread_mutex_unlock(&g_mutex);
            return AIMAPPER_ERROR_NO_RESOURCES;
        }
        b->mapped_addr = ptr;
        b->mapped_size = sz;
    }

    *outData = b->mapped_addr;
    pthread_mutex_unlock(&g_mutex);
    return AIMAPPER_ERROR_NONE;
}

// 5. unlock
static AIMapper_Error mapper_unlock(buffer_handle_t buffer, int* releaseFence) {
    if (!buffer || !releaseFence) return AIMAPPER_ERROR_BAD_BUFFER;
    *releaseFence = -1;
    return AIMAPPER_ERROR_NONE;
}

// 6. flushLockedBuffer
static AIMapper_Error mapper_flushLockedBuffer(buffer_handle_t buffer) {
    pthread_mutex_lock(&g_mutex);
    for (int i = 0; i < MAX_IMPORTED_BUFFERS; i++) {
        if (g_buffers[i].in_use && g_buffers[i].handle == buffer && g_buffers[i].mapped_addr) {
            msync(g_buffers[i].mapped_addr, g_buffers[i].mapped_size, MS_SYNC);
            break;
        }
    }
    pthread_mutex_unlock(&g_mutex);
    return AIMAPPER_ERROR_NONE;
}

// 7. rereadLockedBuffer
static AIMapper_Error mapper_rereadLockedBuffer(buffer_handle_t buffer) {
    (void)buffer;
    return AIMAPPER_ERROR_NONE;
}

static const uint64_t STANDARD_METADATA_NAME_LEN = 53; // strlen("android.hardware.graphics.common.StandardMetadataType")

static int32_t provide_metadata(int64_t standardMetadataType,
                                 const void* payload, size_t payloadSize,
                                 void* dest, size_t destSize) {
    size_t total_aidl = 8 + STANDARD_METADATA_NAME_LEN + 8 + payloadSize;
    if (!dest || destSize == 0) {
        return (int32_t)total_aidl;
    }
    if (destSize == payloadSize) {
        // Direct payload mode for raw/legacy callers
        memcpy(dest, payload, payloadSize);
        return (int32_t)payloadSize;
    }
    if (destSize < total_aidl) {
        return -AIMAPPER_ERROR_BAD_VALUE;
    }
    uint8_t* p = (uint8_t*)dest;
    uint64_t name_len = STANDARD_METADATA_NAME_LEN;
    memcpy(p, &name_len, 8);
    p += 8;
    memcpy(p, STANDARD_METADATA_NAME, STANDARD_METADATA_NAME_LEN);
    p += STANDARD_METADATA_NAME_LEN;
    memcpy(p, &standardMetadataType, 8);
    p += 8;
    memcpy(p, payload, payloadSize);
    return (int32_t)total_aidl;
}

// 8. getStandardMetadata
static int32_t mapper_getStandardMetadata(buffer_handle_t buffer,
                                          int64_t standardMetadataType,
                                          void* outMetadata,
                                          size_t outMetadataSize) {
    if (!buffer) return -AIMAPPER_ERROR_BAD_BUFFER;

    pthread_mutex_lock(&g_mutex);
    const ImportedBuffer* b = NULL;
    for (int i = 0; i < MAX_IMPORTED_BUFFERS; i++) {
        if (g_buffers[i].in_use && g_buffers[i].handle == buffer) {
            b = &g_buffers[i];
            break;
        }
    }
    ImportedBuffer parsed_buf;
    memset(&parsed_buf, 0, sizeof(parsed_buf));
    if (!b) {
        if (parse_handle((const native_handle_t*)buffer, &parsed_buf) == 0) {
            b = &parsed_buf;
        } else {
            pthread_mutex_unlock(&g_mutex);
            return -AIMAPPER_ERROR_BAD_BUFFER;
        }
    }

    int32_t ret = -AIMAPPER_ERROR_UNSUPPORTED;
    switch (standardMetadataType) {
        case METADATA_BUFFER_ID: {
            uint64_t val = b->buffer_id;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_NAME: {
            const char* name = "aaas_native_buffer";
            uint64_t len = strlen(name);
            uint8_t name_payload[8 + 32];
            memcpy(name_payload, &len, 8);
            memcpy(name_payload + 8, name, len);
            ret = provide_metadata(standardMetadataType, name_payload, 8 + len, outMetadata, outMetadataSize);
            break;
        }
        case METADATA_WIDTH: {
            uint64_t val = b->width;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_HEIGHT: {
            uint64_t val = b->height;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_STRIDE: {
            uint32_t val = b->stride;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_LAYER_COUNT: {
            uint64_t val = 1;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_PIXEL_FORMAT_REQUESTED: {
            int32_t val = b->format;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_PIXEL_FORMAT_FOURCC: {
            uint32_t val = drm_fourcc_from_hal(b->format);
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_PIXEL_FORMAT_MODIFIER: {
            uint64_t val = DRM_FORMAT_MOD_LINEAR;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_USAGE: {
            uint64_t val = b->usage;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_ALLOCATION_SIZE: {
            uint64_t val = b->size;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_PROTECTED_CONTENT: {
            uint64_t val = 0;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_COMPRESSION: {
            uint64_t val = 0;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_INTERLACED: {
            uint64_t val = 0;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_DATASPACE: {
            int32_t val = b->dataspace;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_PLANE_LAYOUTS: {
            int64_t layout[10];
            layout[0] = 1; // 1 plane layout
            layout[1] = 0; // 0 components in plane
            layout[2] = 0; // offsetInBytes
            layout[3] = 32; // sampleIncrementInBits
            layout[4] = (int64_t)b->stride * 4; // strideInBytes
            layout[5] = (int64_t)b->width; // widthInSamples
            layout[6] = (int64_t)b->height; // heightInSamples
            layout[7] = (int64_t)b->size; // totalSizeInBytes
            layout[8] = 1; // horizontalSubsampling
            layout[9] = 1; // verticalSubsampling
            ret = provide_metadata(standardMetadataType, layout, sizeof(layout), outMetadata, outMetadataSize);
            break;
        }
        case METADATA_BLEND_MODE: {
            int32_t val = b->blend_mode;
            ret = provide_metadata(standardMetadataType, &val, sizeof(val), outMetadata, outMetadataSize);
            break;
        }
        default:
            ret = -AIMAPPER_ERROR_UNSUPPORTED;
            break;
    }
    pthread_mutex_unlock(&g_mutex);
    return ret;
}

// 9. getMetadata
static int32_t mapper_getMetadata(buffer_handle_t buffer,
                                  AIMapper_MetadataType metadataType,
                                  void* outMetadata,
                                  size_t outMetadataSize) {
    if (metadataType.name && strcmp(metadataType.name, STANDARD_METADATA_NAME) == 0) {
        return mapper_getStandardMetadata(buffer, metadataType.value, outMetadata, outMetadataSize);
    }
    return -AIMAPPER_ERROR_UNSUPPORTED;
}

// 10. setStandardMetadata
static AIMapper_Error mapper_setStandardMetadata(buffer_handle_t buffer,
                                                 int64_t standardMetadataType,
                                                 const void* metadata,
                                                 size_t metadataSize) {
    if (!buffer || !metadata) return AIMAPPER_ERROR_BAD_BUFFER;

    pthread_mutex_lock(&g_mutex);
    ImportedBuffer* b = NULL;
    for (int i = 0; i < MAX_IMPORTED_BUFFERS; i++) {
        if (g_buffers[i].in_use && g_buffers[i].handle == buffer) {
            b = &g_buffers[i];
            break;
        }
    }
    if (!b) {
        pthread_mutex_unlock(&g_mutex);
        return AIMAPPER_ERROR_BAD_BUFFER;
    }

    AIMapper_Error err = AIMAPPER_ERROR_NONE;
    switch (standardMetadataType) {
        case METADATA_DATASPACE:
            if (metadataSize >= sizeof(int32_t)) {
                b->dataspace = *(const int32_t*)metadata;
            } else {
                err = AIMAPPER_ERROR_BAD_VALUE;
            }
            break;
        case METADATA_BLEND_MODE:
            if (metadataSize >= sizeof(int32_t)) {
                b->blend_mode = *(const int32_t*)metadata;
            } else {
                err = AIMAPPER_ERROR_BAD_VALUE;
            }
            break;
        case METADATA_SMPTE2086:
        case METADATA_CTA861_3:
        case METADATA_SMPTE2094_40:
        case METADATA_SMPTE2094_10:
            err = AIMAPPER_ERROR_NONE;
            break;
        default:
            err = AIMAPPER_ERROR_UNSUPPORTED;
            break;
    }
    pthread_mutex_unlock(&g_mutex);
    return err;
}

// 11. setMetadata
static AIMapper_Error mapper_setMetadata(buffer_handle_t buffer,
                                         AIMapper_MetadataType metadataType,
                                         const void* metadata,
                                         size_t metadataSize) {
    if (metadataType.name && strcmp(metadataType.name, STANDARD_METADATA_NAME) == 0) {
        return mapper_setStandardMetadata(buffer, metadataType.value, metadata, metadataSize);
    }
    return AIMAPPER_ERROR_UNSUPPORTED;
}

static const AIMapper_MetadataTypeDescription g_supported_types[] = {
    { { STANDARD_METADATA_NAME, METADATA_BUFFER_ID }, "BUFFER_ID", true, false },
    { { STANDARD_METADATA_NAME, METADATA_NAME }, "NAME", true, false },
    { { STANDARD_METADATA_NAME, METADATA_WIDTH }, "WIDTH", true, false },
    { { STANDARD_METADATA_NAME, METADATA_HEIGHT }, "HEIGHT", true, false },
    { { STANDARD_METADATA_NAME, METADATA_STRIDE }, "STRIDE", true, false },
    { { STANDARD_METADATA_NAME, METADATA_LAYER_COUNT }, "LAYER_COUNT", true, false },
    { { STANDARD_METADATA_NAME, METADATA_PIXEL_FORMAT_REQUESTED }, "PIXEL_FORMAT_REQUESTED", true, false },
    { { STANDARD_METADATA_NAME, METADATA_PIXEL_FORMAT_FOURCC }, "PIXEL_FORMAT_FOURCC", true, false },
    { { STANDARD_METADATA_NAME, METADATA_PIXEL_FORMAT_MODIFIER }, "PIXEL_FORMAT_MODIFIER", true, false },
    { { STANDARD_METADATA_NAME, METADATA_USAGE }, "USAGE", true, false },
    { { STANDARD_METADATA_NAME, METADATA_ALLOCATION_SIZE }, "ALLOCATION_SIZE", true, false },
    { { STANDARD_METADATA_NAME, METADATA_PROTECTED_CONTENT }, "PROTECTED_CONTENT", true, false },
    { { STANDARD_METADATA_NAME, METADATA_DATASPACE }, "DATASPACE", true, true },
    { { STANDARD_METADATA_NAME, METADATA_BLEND_MODE }, "BLEND_MODE", true, true },
    { { STANDARD_METADATA_NAME, METADATA_PLANE_LAYOUTS }, "PLANE_LAYOUTS", true, false },
};

// 12. listSupportedMetadataTypes
static AIMapper_Error mapper_listSupportedMetadataTypes(
        const AIMapper_MetadataTypeDescription** outDescriptionList,
        size_t* outNumberOfDescriptions) {
    if (!outDescriptionList || !outNumberOfDescriptions) return AIMAPPER_ERROR_UNSUPPORTED;
    *outDescriptionList = g_supported_types;
    *outNumberOfDescriptions = sizeof(g_supported_types) / sizeof(g_supported_types[0]);
    return AIMAPPER_ERROR_NONE;
}

// 13. dumpBuffer
static AIMapper_Error mapper_dumpBuffer(buffer_handle_t buffer,
                                        AIMapper_DumpBufferCallback dumpBufferCallback,
                                        void* context) {
    (void)buffer;
    (void)dumpBufferCallback;
    (void)context;
    return AIMAPPER_ERROR_NONE;
}

// 14. dumpAllBuffers
static AIMapper_Error mapper_dumpAllBuffers(AIMapper_BeginDumpBufferCallback beginDumpCallback,
                                           AIMapper_DumpBufferCallback dumpBufferCallback,
                                           void* context) {
    (void)beginDumpCallback;
    (void)dumpBufferCallback;
    (void)context;
    return AIMAPPER_ERROR_NONE;
}

// 15. getReservedRegion
static AIMapper_Error mapper_getReservedRegion(buffer_handle_t buffer,
                                               void** outReservedRegion,
                                               uint64_t* outReservedSize) {
    (void)buffer;
    (void)outReservedRegion;
    (void)outReservedSize;
    return AIMAPPER_ERROR_UNSUPPORTED;
}

// Static AIMapper instance
static AIMapper g_aimapper = {
    .version = AIMAPPER_VERSION_5,
    .v5 = {
        .importBuffer = mapper_importBuffer,
        .freeBuffer = mapper_freeBuffer,
        .getTransportSize = mapper_getTransportSize,
        .lock = mapper_lock,
        .unlock = mapper_unlock,
        .flushLockedBuffer = mapper_flushLockedBuffer,
        .rereadLockedBuffer = mapper_rereadLockedBuffer,
        .getMetadata = mapper_getMetadata,
        .getStandardMetadata = mapper_getStandardMetadata,
        .setMetadata = mapper_setMetadata,
        .setStandardMetadata = mapper_setStandardMetadata,
        .listSupportedMetadataTypes = mapper_listSupportedMetadataTypes,
        .dumpBuffer = mapper_dumpBuffer,
        .dumpAllBuffers = mapper_dumpAllBuffers,
        .getReservedRegion = mapper_getReservedRegion,
    }
};

extern "C" {

uint32_t ANDROID_HAL_MAPPER_VERSION = 5;

AIMapper_Error AIMapper_loadIMapper(AIMapper** outImplementation) {
    kmsg_log("<6>[MAPPER.DRM] AIMapper_loadIMapper called! Native DRM Mapper 5 loaded.\n");
    if (!outImplementation) return AIMAPPER_ERROR_UNSUPPORTED;
    *outImplementation = &g_aimapper;
    return AIMAPPER_ERROR_NONE;
}

}
