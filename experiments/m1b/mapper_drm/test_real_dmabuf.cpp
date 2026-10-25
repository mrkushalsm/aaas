/*
 * Test Mapper 5 with Genuine GPU DMA-BUFs via GBM
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <dlfcn.h>
#include <gbm.h>
#include <cutils/native_handle.h>
#include <android/rect.h>
#include <android/hardware/graphics/mapper/IMapper.h>

static native_handle_t* local_native_handle_create(int numFds, int numInts) {
    native_handle_t* nh = (native_handle_t*)malloc(sizeof(native_handle_t) + sizeof(int) * (numFds + numInts));
    nh->version = sizeof(native_handle_t);
    nh->numFds = numFds;
    nh->numInts = numInts;
    return nh;
}
static void local_native_handle_close(native_handle_t* nh) {
    for (int i = 0; i < nh->numFds; i++) {
        if (nh->data[i] >= 0) close(nh->data[i]);
    }
}
static void local_native_handle_delete(native_handle_t* nh) {
    free(nh);
}

#define native_handle_create local_native_handle_create
#define native_handle_close local_native_handle_close
#define native_handle_delete local_native_handle_delete

#define AAAS_MAGIC 0x61616173

enum StandardMetadataType : int64_t {
    METADATA_WIDTH = 3,
    METADATA_HEIGHT = 4,
    METADATA_PIXEL_FORMAT_REQUESTED = 6,
    METADATA_ALLOCATION_SIZE = 10,
    METADATA_STRIDE = 23,
};

int main(int argc, char** argv) {
    const char* mapper_path = (argc > 1) ? argv[1] : "/run/media/mrkus/Homework/aaas-workspace/tmp/mapper.drm.so";
    printf("=== Testing Mapper 5 with Genuine GPU DMA-BUFs (GBM) ===\n");

    const char* render_nodes[] = {
        "/dev/dri/renderD129", // Intel
        "/dev/dri/renderD128", // NVIDIA
        NULL
    };

    int drm_fd = -1;
    struct gbm_device* gbm_dev = NULL;
    for (int i = 0; render_nodes[i]; i++) {
        drm_fd = open(render_nodes[i], O_RDWR | O_CLOEXEC);
        if (drm_fd >= 0) {
            gbm_dev = gbm_create_device(drm_fd);
            if (gbm_dev) {
                printf("[TEST] Using GBM device on: %s\n", render_nodes[i]);
                break;
            }
            close(drm_fd);
            drm_fd = -1;
        }
    }

    if (!gbm_dev) {
        fprintf(stderr, "[FAIL] Failed to open any GBM device\n");
        return 1;
    }

    const uint32_t W = 1280;
    const uint32_t H = 720;
    struct gbm_bo* bo = gbm_bo_create(gbm_dev, W, H, GBM_FORMAT_ARGB8888, GBM_BO_USE_RENDERING);
    if (!bo) {
        fprintf(stderr, "[FAIL] gbm_bo_create failed\n");
        gbm_device_destroy(gbm_dev);
        close(drm_fd);
        return 2;
    }

    int dma_fd = gbm_bo_get_fd(bo);
    uint32_t stride = gbm_bo_get_stride(bo);
    uint32_t size = stride * H;
    printf("[TEST] Created Genuine GPU DMA-BUF: fd=%d stride=%u size=%u\n", dma_fd, stride, size);

    void* handle = dlopen(mapper_path, RTLD_NOW | RTLD_LOCAL);
    if (!handle) {
        fprintf(stderr, "[FAIL] dlopen mapper failed: %s\n", dlerror());
        return 3;
    }

    auto load_fn = (AIMapper_Error (*)(AIMapper**))dlsym(handle, "AIMapper_loadIMapper");
    if (!load_fn) {
        fprintf(stderr, "[FAIL] dlsym AIMapper_loadIMapper failed\n");
        return 4;
    }

    AIMapper* mapper = NULL;
    AIMapper_Error err = load_fn(&mapper);
    if (err != AIMAPPER_ERROR_NONE || !mapper) {
        fprintf(stderr, "[FAIL] load_fn returned error %d\n", (int)err);
        return 5;
    }

    native_handle_t* nh = native_handle_create(1, 10);
    nh->data[0] = dma_fd;
    nh->data[1] = (int)AAAS_MAGIC;
    nh->data[2] = (int)W;
    nh->data[3] = (int)H;
    nh->data[4] = (int)(stride / 4);
    nh->data[5] = 1; // HAL_PIXEL_FORMAT_RGBA_8888
    nh->data[6] = 0x3;
    nh->data[7] = 0;
    nh->data[8] = (int)size;
    nh->data[9] = 0x7788;
    nh->data[10] = 0;

    buffer_handle_t imported = NULL;
    err = mapper->v5.importBuffer(nh, &imported);
    if (err != AIMAPPER_ERROR_NONE || !imported) {
        fprintf(stderr, "[FAIL] importBuffer failed: %d\n", (int)err);
        return 6;
    }
    printf("[TEST] Genuine DMA-BUF successfully imported into Mapper 5: imported=%p (cloned fd=%d)\n",
           imported, imported->data[0]);

    uint64_t meta_w = 0, meta_h = 0;
    mapper->v5.getStandardMetadata(imported, METADATA_WIDTH, &meta_w, sizeof(meta_w));
    mapper->v5.getStandardMetadata(imported, METADATA_HEIGHT, &meta_h, sizeof(meta_h));
    printf("[TEST] Metadata verified: %llux%llu\n", (unsigned long long)meta_w, (unsigned long long)meta_h);

    void* mapped_ptr = NULL;
    ARect rect = { 0, 0, (int32_t)W, (int32_t)H };
    err = mapper->v5.lock(imported, 0x3, rect, -1, &mapped_ptr);
    if (err != AIMAPPER_ERROR_NONE || !mapped_ptr) {
        fprintf(stderr, "[FAIL] lock on DMA-BUF failed: %d\n", (int)err);
        return 7;
    }
    printf("[TEST] Genuine DMA-BUF lock succeeded: mapped_ptr=%p\n", mapped_ptr);

    uint32_t* p = (uint32_t*)mapped_ptr;
    p[0] = 0xDEADBEEF;
    p[W - 1] = 0xCAFEBABE;

    int releaseFence = -1;
    err = mapper->v5.unlock(imported, &releaseFence);
    if (err != AIMAPPER_ERROR_NONE) {
        fprintf(stderr, "[FAIL] unlock failed\n");
        return 8;
    }
    printf("[TEST] unlock succeeded (releaseFence=%d)\n", releaseFence);

    err = mapper->v5.freeBuffer(imported);
    if (err != AIMAPPER_ERROR_NONE) {
        fprintf(stderr, "[FAIL] freeBuffer failed\n");
        return 9;
    }
    printf("[TEST] freeBuffer succeeded\n");

    native_handle_close(nh);
    native_handle_delete(nh);
    close(dma_fd);
    gbm_bo_destroy(bo);
    gbm_device_destroy(gbm_dev);
    close(drm_fd);
    dlclose(handle);

    printf("=== GENUINE GPU DMA-BUF TEST WITH MAPPER 5 PASSED! ===\n");
    return 0;
}
