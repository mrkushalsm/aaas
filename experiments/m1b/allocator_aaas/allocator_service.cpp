#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <drm/drm.h>

#include <atomic>
#include <memory>
#include <string>
#include <vector>

#include <android/binder_ibinder.h>
#include <android/binder_manager.h>
#include <android/binder_process.h>
#include <android/binder_auto_utils.h>

#include <aidl/android/hardware/graphics/allocator/BnAllocator.h>
#include <aidl/android/hardware/graphics/allocator/AllocationResult.h>
#include <aidl/android/hardware/graphics/allocator/BufferDescriptorInfo.h>
#include <aidl/android/hardware/common/NativeHandle.h>

extern "C" {
    void __libc_init(void* raw_args, void* onexit, int (*main_fn)(int, char**, char**), void* structors);
    int* __errno();
    int* __errno_location() {
        return __errno();
    }
    void __assert2(const char* file, int line, const char* func, const char* expr) {
        (void)file; (void)line; (void)func; (void)expr;
    }
}

int main(int argc, char** argv, char** envp);

__attribute__((naked))
extern "C" void _start() {
    __asm__ volatile (
        "xor %ebp, %ebp\n"
        "mov %rsp, %rdi\n"
        "and $-16, %rsp\n"
        "sub $48, %rsp\n"
        "movq $0, (%rsp)\n"
        "movq $0, 8(%rsp)\n"
        "movq $0, 16(%rsp)\n"
        "movq $0, 24(%rsp)\n"
        "movq $0, 32(%rsp)\n"
        "movq $0, 40(%rsp)\n"
        "xor %esi, %esi\n"
        "lea main(%rip), %rdx\n"
        "mov %rsp, %rcx\n"
        "call __libc_init\n"
        "hlt\n"
    );
}

static void kmsg_log(const char* fmt, ...) {
    char buf[512];
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (n > 0) {
        printf("%s", buf);
        fflush(stdout);
        int fd = open("/data_allocator.log", O_WRONLY | O_CREAT | O_APPEND, 0666);
        if (fd < 0) {
            fd = open("/dev/kmsg", O_WRONLY | O_APPEND);
        }
        if (fd >= 0) {
            write(fd, buf, n);
            close(fd);
        }
    }
}

#define AAAS_MAGIC 0x61616173

using namespace aidl::android::hardware::graphics::allocator;
using namespace aidl::android::hardware::common;

class AaasAllocator : public BnAllocator {
public:
    AaasAllocator() {
        kmsg_log("[AaasAllocator] Service initialized\n");
    }

    ::ndk::ScopedAStatus allocate(const std::vector<uint8_t>& in_descriptor, int32_t in_count, AllocationResult* _aidl_return) override {
        (void)in_descriptor; (void)in_count; (void)_aidl_return;
        kmsg_log("[AaasAllocator] allocate(byte[]) called (deprecated)\n");
        return ::ndk::ScopedAStatus::fromServiceSpecificError(-1);
    }

    ::ndk::ScopedAStatus allocate2(const BufferDescriptorInfo& in_descriptor, int32_t in_count, AllocationResult* _aidl_return) override {
        uint32_t width = in_descriptor.width > 0 ? (uint32_t)in_descriptor.width : 1280;
        uint32_t height = in_descriptor.height > 0 ? (uint32_t)in_descriptor.height : 720;
        uint32_t stride = (width + 31) & ~31;
        uint32_t bpp = 4; // 32-bit RGBA/RGBX
        uint32_t size = stride * height * bpp;

        kmsg_log("[AaasAllocator] allocate2: req %dx%d fmt=%d count=%d stride=%d size=%u\n",
                 width, height, (int)in_descriptor.format, in_count, stride, size);

        // Try DRM dumb buffer allocation on host GPU node first
        int drm_fd = open("/dev/dri/renderD129", O_RDWR | O_CLOEXEC);
        if (drm_fd < 0) {
            drm_fd = open("/dev/dri/renderD128", O_RDWR | O_CLOEXEC);
        }

        _aidl_return->stride = stride;
        _aidl_return->buffers.clear();

        for (int i = 0; i < in_count; i++) {
            int buffer_fd = -1;
            uint32_t actual_stride = stride;
            uint32_t actual_size = size;

            if (drm_fd >= 0) {
                // Try Intel i915 GEM create
                struct {
                    uint64_t size;
                    uint32_t handle;
                    uint32_t pad;
                } gem_create = { .size = actual_size };
                // DRM_IOCTL_I915_GEM_CREATE = 0xc010645b
                if (ioctl(drm_fd, 0xc010645b, &gem_create) == 0 && gem_create.handle > 0) {
                    struct drm_prime_handle prime = {};
                    prime.handle = gem_create.handle;
                    prime.flags = DRM_CLOEXEC | DRM_RDWR;
                    if (ioctl(drm_fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &prime) == 0) {
                        buffer_fd = prime.fd;
                        kmsg_log("[AaasAllocator] Allocated Intel i915 GPU DMA-BUF: fd=%d size=%u\n",
                                 buffer_fd, actual_size);
                    }
                }

                if (buffer_fd < 0) {
                    struct drm_mode_create_dumb create_dumb = {};
                    create_dumb.width = width;
                    create_dumb.height = height;
                    create_dumb.bpp = 32;

                    if (ioctl(drm_fd, DRM_IOCTL_MODE_CREATE_DUMB, &create_dumb) == 0) {
                        struct drm_prime_handle prime = {};
                        prime.handle = create_dumb.handle;
                        prime.flags = DRM_CLOEXEC | DRM_RDWR;
                        if (ioctl(drm_fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &prime) == 0) {
                            buffer_fd = prime.fd;
                            actual_stride = create_dumb.pitch / 4;
                            actual_size = create_dumb.size;
                            kmsg_log("[AaasAllocator] Allocated GPU DRM PRIME buffer: fd=%d pitch=%u size=%u\n",
                                     buffer_fd, create_dumb.pitch, create_dumb.size);
                        }
                    }
                }
            }

            if (buffer_fd < 0) {
                // High-fidelity fallback to Linux memfd shared memory
                buffer_fd = memfd_create("aaas_buffer", MFD_CLOEXEC | MFD_ALLOW_SEALING);
                if (buffer_fd >= 0) {
                    if (ftruncate(buffer_fd, actual_size) < 0) {
                        close(buffer_fd);
                        buffer_fd = -1;
                    } else {
                        kmsg_log("[AaasAllocator] Allocated memfd buffer: fd=%d size=%u\n",
                                 buffer_fd, actual_size);
                    }
                }
            }

            if (buffer_fd < 0) {
                kmsg_log("[AaasAllocator] ERROR: Failed to allocate backing memory\n");
                if (drm_fd >= 0) close(drm_fd);
                return ::ndk::ScopedAStatus::fromServiceSpecificError(-1);
            }

            static std::atomic<uint64_t> s_buffer_id(100);
            uint64_t buf_id = ++s_buffer_id;
            uint64_t usage = (uint64_t)in_descriptor.usage;

            NativeHandle nh;
            nh.fds.push_back(::ndk::ScopedFileDescriptor(buffer_fd));
            nh.ints.push_back((int32_t)AAAS_MAGIC);
            nh.ints.push_back((int32_t)width);
            nh.ints.push_back((int32_t)height);
            nh.ints.push_back((int32_t)actual_stride);
            nh.ints.push_back((int32_t)in_descriptor.format);
            nh.ints.push_back((int32_t)(usage & 0xFFFFFFFF));
            nh.ints.push_back((int32_t)(usage >> 32));
            nh.ints.push_back((int32_t)actual_size);
            nh.ints.push_back((int32_t)(buf_id & 0xFFFFFFFF));
            nh.ints.push_back((int32_t)(buf_id >> 32));

            _aidl_return->stride = actual_stride;
            _aidl_return->buffers.push_back(std::move(nh));
        }

        if (drm_fd >= 0) {
            close(drm_fd);
        }

        kmsg_log("[AaasAllocator] allocate2 returning %zu buffers successfully\n", _aidl_return->buffers.size());
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus isSupported(const BufferDescriptorInfo& in_descriptor, bool* _aidl_return) override {
        (void)in_descriptor;
        *_aidl_return = true;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getIMapperLibrarySuffix(std::string* _aidl_return) override {
        kmsg_log("[AaasAllocator] getIMapperLibrarySuffix() -> ranchu\n");
        *_aidl_return = "ranchu";
        return ::ndk::ScopedAStatus::ok();
    }
};

int main(int argc, char** argv, char** envp) {
    (void)argc; (void)argv; (void)envp;
    kmsg_log("============================================================\n");
    kmsg_log("=== AaaS Native AIDL Allocator Service Starting (M1B.7)  ===\n");
    kmsg_log("============================================================\n");

    auto allocator = ::ndk::SharedRefBase::make<AaasAllocator>();
    if (!allocator) {
        kmsg_log("[AaasAllocator] FATAL: Failed to allocate AaasAllocator\n");
        return 1;
    }

    const std::string instance = std::string(IAllocator::descriptor) + "/default";
    kmsg_log("[AaasAllocator] Registering service: %s\n", instance.c_str());

    binder_status_t status = AServiceManager_addService(allocator->asBinder().get(), instance.c_str());
    if (status != STATUS_OK) {
        kmsg_log("[AaasAllocator] FATAL: AServiceManager_addService failed: %d\n", status);
        return 2;
    }

    kmsg_log("[AaasAllocator] Successfully registered %s!\n", instance.c_str());

    ABinderProcess_setThreadPoolMaxThreadCount(4);
    ABinderProcess_startThreadPool();
    kmsg_log("[AaasAllocator] Binder thread pool running, joining...\n");

    ABinderProcess_joinThreadPool();
    return 0;
}
