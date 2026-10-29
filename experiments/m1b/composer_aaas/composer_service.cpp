#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <stdarg.h>
#include <sys/mman.h>
#include <sys/ioctl.h>

#include <atomic>
#include <chrono>
#include <memory>
#include <string>
#include <thread>
#include <vector>
#include <set>
#include <mutex>

#include <android/binder_ibinder.h>
#include <android/binder_manager.h>
#include <android/binder_process.h>
#include <android/binder_auto_utils.h>

#include <aidl/android/hardware/graphics/composer3/BnComposer.h>
#include <aidl/android/hardware/graphics/composer3/BnComposerClient.h>
#include <aidl/android/hardware/graphics/composer3/IComposerCallback.h>
#include <aidl/android/hardware/graphics/composer3/PresentOrValidate.h>
#include <aidl/android/hardware/graphics/composer3/PresentFence.h>
#include <aidl/android/hardware/graphics/composer3/CommandError.h>
#include <aidl/android/hardware/graphics/composer3/ReleaseFences.h>
#include <aidl/android/hardware/graphics/composer3/ChangedCompositionTypes.h>
#include <aidl/android/hardware/graphics/composer3/ChangedCompositionLayer.h>
#include <aidl/android/hardware/graphics/composer3/DisplayRequest.h>
#include <aidl/android/hardware/graphics/common/DisplayHotplugEvent.h>
#include <aidl/android/hardware/graphics/composer3/DisplayConnectionType.h>
#include <aidl/android/hardware/graphics/common/Transform.h>
#include <aidl/android/hardware/graphics/common/PixelFormat.h>
#include <aidl/android/hardware/graphics/composer3/Composition.h>

#include "aaas_transport.h"

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
        int fd = open("/data_composer.log", O_WRONLY | O_CREAT | O_APPEND, 0666);
        if (fd < 0) {
            fd = open("/dev/kmsg", O_WRONLY | O_APPEND);
        }
        if (fd >= 0) {
            write(fd, buf, n);
            close(fd);
        }
    }
}

using namespace aidl::android::hardware::graphics::composer3;
using namespace aidl::android::hardware::graphics::common;

static const std::vector<uint8_t> kAaasEdid = {
    0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x00, 0x04, 0x43, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00,
    0x01, 0x24, 0x01, 0x03, 0x80, 0x1e, 0x11, 0x78, 0x0a, 0xee, 0x91, 0xa3, 0x54, 0x4c, 0x99, 0x26,
    0x0f, 0x50, 0x54, 0x00, 0x00, 0x00, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01,
    0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0xf9, 0x1c, 0x00, 0x72, 0x51, 0xd0, 0x1e, 0x20, 0x6e, 0x28,
    0x55, 0x00, 0xc4, 0x8e, 0x21, 0x00, 0x00, 0x1e, 0x00, 0x00, 0x00, 0xfc, 0x00, 0x41, 0x61, 0x61,
    0x53, 0x20, 0x44, 0x69, 0x73, 0x70, 0x6c, 0x61, 0x79, 0x0a, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x10,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x4b
};

struct ClientTargetSlot {
    int dma_fd = -1;
    int acquire_fence = -1;
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t stride = 0;
    uint32_t format = 0;
    bool has_handle = false;
};

class AaasComposerClient : public IComposerClientDefault {
public:
    AaasComposerClient()
        : mNextLayerId(1), mCurrentClientTargetSlot(-1),
          mNeedsValidation(true), mVsyncEnabled(false), mRunning(true) {
        kmsg_log("[AaasComposerClient] Instance created (M1B.7)\n");
    }

    ~AaasComposerClient() override {
        kmsg_log("[AaasComposerClient] Instance destroyed\n");
        mRunning = false;
        if (mVsyncThread.joinable()) {
            mVsyncThread.join();
        }
    }

    ::ndk::ScopedAStatus registerCallback(const std::shared_ptr<IComposerCallback>& in_callback) override {
        kmsg_log("[AaasComposerClient] registerCallback invoked\n");
        mCallback = in_callback;

        if (mCallback) {
            kmsg_log("[AaasComposerClient] Emitting synchronous onHotplugEvent(display=1, CONNECTED)\n");
            mCallback->onHotplugEvent(1, DisplayHotplugEvent::CONNECTED);
        }

        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getDisplayConfigs(int64_t in_display, std::vector<int32_t>* _aidl_return) override {
        kmsg_log("[AaasComposerClient] getDisplayConfigs(display=%ld)\n", (long)in_display);
        _aidl_return->push_back(1);
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getActiveConfig(int64_t in_display, int32_t* _aidl_return) override {
        kmsg_log("[AaasComposerClient] getActiveConfig(display=%ld)\n", (long)in_display);
        *_aidl_return = 1;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getDisplayConfigurations(int64_t in_display, int32_t in_maxFrameIntervalNs, std::vector<DisplayConfiguration>* _aidl_return) override {
        (void)in_maxFrameIntervalNs;
        kmsg_log("[AaasComposerClient] getDisplayConfigurations(display=%ld) -> 1280x720@60Hz\n", (long)in_display);
        DisplayConfiguration cfg;
        cfg.configId = 1;
        cfg.width = 1280;
        cfg.height = 720;
        cfg.vsyncPeriod = 16666666;
        _aidl_return->push_back(cfg);
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getDisplayConnectionType(int64_t in_display, DisplayConnectionType* _aidl_return) override {
        kmsg_log("[AaasComposerClient] getDisplayConnectionType(display=%ld) -> INTERNAL\n", (long)in_display);
        *_aidl_return = DisplayConnectionType::INTERNAL;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getDisplayIdentificationData(int64_t in_display, DisplayIdentification* _aidl_return) override {
        kmsg_log("[AaasComposerClient] getDisplayIdentificationData(display=%ld) -> port=1, edid=128B\n", (long)in_display);
        _aidl_return->port = 1;
        _aidl_return->data = kAaasEdid;
        _aidl_return->screenPartStatus = ScreenPartStatus::ORIGINAL;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getDisplayPhysicalOrientation(int64_t in_display, Transform* _aidl_return) override {
        (void)in_display;
        *_aidl_return = Transform::NONE;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getDisplayVsyncPeriod(int64_t in_display, int32_t* _aidl_return) override {
        (void)in_display;
        *_aidl_return = 16666666;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getColorModes(int64_t in_display, std::vector<ColorMode>* _aidl_return) override {
        (void)in_display;
        _aidl_return->push_back(ColorMode::NATIVE);
        _aidl_return->push_back(ColorMode::SRGB);
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getRenderIntents(int64_t in_display, ColorMode in_mode, std::vector<RenderIntent>* _aidl_return) override {
        (void)in_display; (void)in_mode;
        _aidl_return->push_back(RenderIntent::COLORIMETRIC);
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getDisplayCapabilities(int64_t in_display, std::vector<DisplayCapability>* _aidl_return) override {
        (void)in_display;
        _aidl_return->clear();
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getHdrCapabilities(int64_t in_display, HdrCapabilities* _aidl_return) override {
        (void)in_display;
        _aidl_return->maxLuminance = 500.0f;
        _aidl_return->maxAverageLuminance = 300.0f;
        _aidl_return->minLuminance = 0.0f;
        _aidl_return->types = {};
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getHdrConversionCapabilities(std::vector<HdrConversionCapability>* _aidl_return) override {
        _aidl_return->clear();
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getSupportedContentTypes(int64_t in_display, std::vector<ContentType>* _aidl_return) override {
        (void)in_display;
        _aidl_return->clear();
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getPerFrameMetadataKeys(int64_t in_display, std::vector<PerFrameMetadataKey>* _aidl_return) override {
        (void)in_display;
        _aidl_return->clear();
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus setClientTargetSlotCount(int64_t in_display, int32_t in_clientTargetSlotCount) override {
        kmsg_log("[AaasComposerClient] setClientTargetSlotCount(display=%ld, count=%d)\n", (long)in_display, in_clientTargetSlotCount);
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus setColorMode(int64_t in_display, ColorMode in_mode, RenderIntent in_intent) override {
        (void)in_display; (void)in_mode; (void)in_intent;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus setPowerMode(int64_t in_display, PowerMode in_mode) override {
        kmsg_log("[AaasComposerClient] setPowerMode(display=%ld, mode=%d)\n", (long)in_display, (int)in_mode);
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus setVsyncEnabled(int64_t in_display, bool in_enabled) override {
        kmsg_log("[AaasComposerClient] setVsyncEnabled(display=%ld, enabled=%d)\n", (long)in_display, in_enabled ? 1 : 0);
        mVsyncEnabled = in_enabled;

        if (in_enabled && !mVsyncThreadRunning.exchange(true)) {
            if (mVsyncThread.joinable()) {
                mVsyncThread.join();
            }
            mVsyncThread = std::thread([this]() {
                vsyncLoop();
            });
        }

        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus createLayer(int64_t in_display, int32_t in_bufferSlotCount, int64_t* _aidl_return) override {
        (void)in_display; (void)in_bufferSlotCount;
        int64_t layerId = mNextLayerId++;
        {
            std::lock_guard<std::mutex> lock(mLayerLock);
            mActiveLayers.insert(layerId);
        }
        mNeedsValidation = true;
        kmsg_log("[AaasComposerClient] createLayer(display=%ld, slotCount=%d) -> layerId=%ld\n",
                 (long)in_display, in_bufferSlotCount, (long)layerId);
        *_aidl_return = layerId;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus destroyLayer(int64_t in_display, int64_t in_layer) override {
        (void)in_display;
        {
            std::lock_guard<std::mutex> lock(mLayerLock);
            mActiveLayers.erase(in_layer);
        }
        mNeedsValidation = true;
        kmsg_log("[AaasComposerClient] destroyLayer(display=%ld, layerId=%ld)\n", (long)in_display, (long)in_layer);
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus executeCommands(const std::vector<DisplayCommand>& in_commands, std::vector<CommandResultPayload>* _aidl_return) override {
        kmsg_log("[AaasComposerClient] executeCommands: count=%zu\n", in_commands.size());
        size_t command_index = 0;
        for (const auto& cmd : in_commands) {
            kmsg_log("  [cmd] display=%lld val=%d accept=%d pres=%d presOrVal=%d ct=%d layers=%zu\n",
                     (long long)cmd.display, cmd.validateDisplay, cmd.acceptDisplayChanges,
                     cmd.presentDisplay, cmd.presentOrValidateDisplay, cmd.clientTarget.has_value(),
                     cmd.layers.size());
            for (const auto& l : cmd.layers) {
                int slot = l.buffer.has_value() ? l.buffer->slot : -1;
                int has_h = l.buffer.has_value() && l.buffer->handle.has_value();
                int fd = -1;
                if (has_h && !l.buffer->handle->fds.empty()) {
                    fd = l.buffer->handle->fds[0].get();
                }
                kmsg_log("    [layer] id=%lld buf=%d slot=%d has_h=%d fd=%d\n",
                         (long long)l.layer, l.buffer.has_value(), slot, has_h, fd);
                if (fd >= 0 && l.buffer->handle->ints.size() >= 8 && (uint32_t)l.buffer->handle->ints[0] == 0x61616173) {
                    uint32_t w = (uint32_t)l.buffer->handle->ints[1];
                    uint32_t h = (uint32_t)l.buffer->handle->ints[2];
                    uint32_t str = (uint32_t)l.buffer->handle->ints[3];
                    uint32_t sz = (uint32_t)l.buffer->handle->ints[7];
                    void* ptr = mmap(NULL, sz, PROT_READ, MAP_SHARED, fd, 0);
                    if (ptr != MAP_FAILED) {
                        const uint8_t* u = (const uint8_t*)ptr;
                        uint8_t min_v = 255, max_v = 0;
                        size_t non_zero = 0;
                        for (size_t i = 0; i < sz; i++) {
                            if (u[i] < min_v) min_v = u[i];
                            if (u[i] > max_v) max_v = u[i];
                            if (u[i] != 0) non_zero++;
                        }
                        kmsg_log("      [layer %lld buffer] %dx%d stride=%d sz=%u min=%u max=%u non_zero=%zu\n",
                                 (long long)l.layer, w, h, str, sz, min_v, max_v, non_zero);
                        munmap(ptr, sz);
                    }
                }
            }
            // 1. Process client target if provided
            if (cmd.clientTarget.has_value()) {
                const auto& ct = *cmd.clientTarget;
                int32_t slot = ct.buffer.slot;
                int acq_fence = ct.buffer.fence.get();

                if (slot >= 0 && slot < 64) {
                    if (mSlots[slot].acquire_fence >= 0) {
                        close(mSlots[slot].acquire_fence);
                        mSlots[slot].acquire_fence = -1;
                    }
                    if (acq_fence >= 0) {
                        mSlots[slot].acquire_fence = dup(acq_fence);
                    }

                    if (ct.buffer.handle.has_value()) {
                        const auto& nh = *ct.buffer.handle;
                        mSlots[slot].has_handle = true;
                        if (!nh.fds.empty() && nh.fds[0].get() >= 0) {
                            if (mSlots[slot].dma_fd >= 0) {
                                close(mSlots[slot].dma_fd);
                            }
                            mSlots[slot].dma_fd = dup(nh.fds[0].get());
                        }
                        if (nh.ints.size() >= 10 && (uint32_t)nh.ints[0] == 0x61616173) {
                            mSlots[slot].width = (uint32_t)nh.ints[1];
                            mSlots[slot].height = (uint32_t)nh.ints[2];
                            mSlots[slot].stride = (uint32_t)nh.ints[3];
                            mSlots[slot].format = (uint32_t)nh.ints[4];
                        } else {
                            mSlots[slot].width = 1280;
                            mSlots[slot].height = 720;
                            mSlots[slot].stride = 1280;
                            mSlots[slot].format = 1;
                        }
                    }
                    mCurrentClientTargetSlot = slot;
                    kmsg_log("[AaasComposerClient] ClientTarget: slot=%d %dx%d stride=%d fmt=%d dma_fd=%d acq_fence=%d\n",
                             slot, mSlots[slot].width, mSlots[slot].height, mSlots[slot].stride,
                             mSlots[slot].format, mSlots[slot].dma_fd, mSlots[slot].acquire_fence);
                }
            }

            // 2. Handle composition negotiation and validation
            if (cmd.acceptDisplayChanges) {
                mNeedsValidation = false;
            }

            if (cmd.validateDisplay) {
                ChangedCompositionTypes cct;
                cct.display = cmd.display;
                {
                    std::lock_guard<std::mutex> lock(mLayerLock);
                    for (int64_t layerId : mActiveLayers) {
                        ChangedCompositionLayer ccl;
                        ccl.layer = layerId;
                        ccl.composition = Composition::CLIENT;
                        cct.layers.push_back(ccl);
                    }
                }
                _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::changedCompositionTypes>(cct));

                DisplayRequest dr;
                dr.display = cmd.display;
                dr.mask = 0;
                _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::displayRequest>(dr));
                mNeedsValidation = false;
            } else if (cmd.presentOrValidateDisplay) {
                PresentOrValidate pv;
                pv.display = cmd.display;
                pv.result = PresentOrValidate::Result::Validated;
                _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::presentOrValidateResult>(pv));

                ChangedCompositionTypes cct;
                cct.display = cmd.display;
                {
                    std::lock_guard<std::mutex> lock(mLayerLock);
                    for (int64_t layerId : mActiveLayers) {
                        ChangedCompositionLayer ccl;
                        ccl.layer = layerId;
                        ccl.composition = Composition::CLIENT;
                        cct.layers.push_back(ccl);
                    }
                }
                _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::changedCompositionTypes>(cct));

                DisplayRequest dr;
                dr.display = cmd.display;
                dr.mask = 0;
                _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::displayRequest>(dr));
                mNeedsValidation = false;
            } else if (cmd.presentDisplay) {
                if (!presentCurrentFrame(cmd.display, command_index, _aidl_return)) {
                    CommandError error;
                    error.commandIndex = static_cast<int32_t>(command_index);
                    error.errorCode = IComposerClient::EX_NO_RESOURCES;
                    _aidl_return->push_back(
                        CommandResultPayload::make<CommandResultPayload::Tag::error>(error));
                }
            }
            command_index++;
        }
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus createVirtualDisplay(int32_t in_width, int32_t in_height, PixelFormat in_formatHint, int32_t in_outputBufferSlotCount, VirtualDisplay* _aidl_return) override {
        (void)in_width; (void)in_height; (void)in_formatHint; (void)in_outputBufferSlotCount; (void)_aidl_return;
        return ::ndk::ScopedAStatus::fromServiceSpecificError(IComposerClient::EX_UNSUPPORTED);
    }

    ::ndk::ScopedAStatus destroyVirtualDisplay(int64_t in_display) override {
        (void)in_display;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getOverlaySupport(OverlayProperties* _aidl_return) override {
        (void)_aidl_return;
        return ::ndk::ScopedAStatus::fromServiceSpecificError(IComposerClient::EX_UNSUPPORTED);
    }

    ::ndk::ScopedAStatus getMaxVirtualDisplayCount(int32_t* _aidl_return) override {
        *_aidl_return = 0;
        return ::ndk::ScopedAStatus::ok();
    }

private:
    static int create_signaled_fence() {
        int drm_fd = open("/dev/dri/renderD129", O_RDWR | O_CLOEXEC);
        if (drm_fd < 0) return -1;

        struct {
            uint32_t handle;
            uint32_t flags;
        } create_args = {0, 1 /* DRM_SYNCOBJ_CREATE_SIGNALED */};

        if (ioctl(drm_fd, 0xc00864bf, &create_args) != 0 || create_args.handle == 0) {
            close(drm_fd);
            return -1;
        }

        struct {
            uint32_t handle;
            uint32_t flags;
            int32_t fd;
            uint32_t pad;
        } h2fd_args = {create_args.handle, 1 /* DRM_SYNCOBJ_HANDLE_TO_FD_FLAGS_EXPORT_SYNC_FILE */, -1, 0};

        int res = ioctl(drm_fd, 0xc00c64c1, &h2fd_args);
        ioctl(drm_fd, 0xc00864c0, &create_args);
        close(drm_fd);

        if (res == 0 && h2fd_args.fd >= 0) {
            return h2fd_args.fd;
        }
        return -1;
    }

    bool presentCurrentFrame(int64_t display, size_t command_index,
                             std::vector<CommandResultPayload>* _aidl_return) {
        int slot = mCurrentClientTargetSlot;
        int release_fence = -1;

        if (slot >= 0 && slot < 64 && mSlots[slot].dma_fd >= 0) {
            AaasBufferSlot frame = {};
            frame.slot = (uint32_t)slot;
            frame.id = (uint32_t)(slot + 1);
            frame.dma_fd = mSlots[slot].dma_fd;
            frame.acquire_fence_fd = mSlots[slot].acquire_fence;
            frame.width = mSlots[slot].width > 0 ? mSlots[slot].width : 1280;
            frame.height = mSlots[slot].height > 0 ? mSlots[slot].height : 720;
            frame.stride = mSlots[slot].stride > 0 ? mSlots[slot].stride : 1280;
            frame.format = 0x34324241; // DRM_FORMAT_ABGR8888 ('AB24')
            frame.modifier = 0; // DRM_FORMAT_MOD_LINEAR

            // Check if backing is memfd
            char link[128], path[64];
            snprintf(path, sizeof(path), "/proc/self/fd/%d", frame.dma_fd);
            ssize_t len = readlink(path, link, sizeof(link) - 1);
            if (len > 0 && strncmp(link, "/memfd:", 7) == 0) {
                frame.is_linear = true;
            }

            uint32_t ct_sz = frame.stride * frame.height * 4;
            void* ct_ptr = mmap(NULL, ct_sz, PROT_READ, MAP_SHARED, frame.dma_fd, 0);
            if (ct_ptr != MAP_FAILED) {
                const uint8_t* u = (const uint8_t*)ct_ptr;
                uint8_t min_v = 255, max_v = 0;
                size_t non_zero = 0;
                for (size_t i = 0; i < ct_sz; i++) {
                    if (u[i] < min_v) min_v = u[i];
                    if (u[i] > max_v) max_v = u[i];
                    if (u[i] != 0) non_zero++;
                }
                kmsg_log("[AaasComposerClient] ClientTarget slot=%d %dx%d stride=%d sz=%u min=%u max=%u non_zero=%zu\n",
                         slot, frame.width, frame.height, frame.stride, ct_sz, min_v, max_v, non_zero);
                munmap(ct_ptr, ct_sz);
            }

            int submit_result = AaasTransport::getInstance().submitFrame(frame);
            if (submit_result != 0) {
                kmsg_log("[AaasComposerClient] presentDisplay rejected for command %zu: transport submit rc=%d\n",
                         command_index, submit_result);
                return false;
            }

            /* New presenters acknowledge once the source has been copied to
             * presenter-owned storage. Older peers complete this same wait at
             * their ordinary Wayland buffer release. */
            if (!AaasTransport::getInstance().waitForSlotRelease(
                    (uint32_t)slot, 250) ||
                !AaasTransport::getInstance().isConnected()) {
                kmsg_log("[AaasComposerClient] presentDisplay timed out waiting for safe source release on slot %d\n",
                         slot);
                return false;
            }
            release_fence = AaasTransport::getInstance().takeReleaseFence(slot);

            if (mSlots[slot].acquire_fence >= 0) {
                close(mSlots[slot].acquire_fence);
                mSlots[slot].acquire_fence = -1;
            }
        }

        if (release_fence < 0) {
            release_fence = create_signaled_fence();
        }

        PresentFence pf;
        pf.display = display;
        pf.fence = ::ndk::ScopedFileDescriptor(release_fence >= 0 ? release_fence : create_signaled_fence());
        _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::presentFence>(std::move(pf)));

        ReleaseFences rf;
        rf.display = display;
        {
            std::lock_guard<std::mutex> lock(mLayerLock);
            for (int64_t layerId : mActiveLayers) {
                ReleaseFences::Layer l;
                l.layer = layerId;
                l.fence = ::ndk::ScopedFileDescriptor(create_signaled_fence());
                rf.layers.push_back(std::move(l));
            }
        }
        _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::releaseFences>(std::move(rf)));
        return true;
    }

    void vsyncLoop() {
        while (mRunning && mVsyncThreadRunning) {
            if (mVsyncEnabled && mCallback) {
                struct timespec ts;
                clock_gettime(CLOCK_MONOTONIC, &ts);
                int64_t now_ns = (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
                mCallback->onVsync(1, now_ns, 16666666);
            }
            // 60 Hz tick = ~16.666 ms
            usleep(16666);
        }
        mVsyncThreadRunning = false;
    }

    std::shared_ptr<IComposerCallback> mCallback;
    std::atomic<int64_t> mNextLayerId;
    std::mutex mLayerLock;
    std::set<int64_t> mActiveLayers;

    ClientTargetSlot mSlots[64];
    int mCurrentClientTargetSlot;
    bool mNeedsValidation;

    std::atomic<bool> mVsyncEnabled;
    std::atomic<bool> mVsyncThreadRunning{false};
    std::atomic<bool> mRunning;
    std::thread mVsyncThread;
};

class AaasComposer : public BnComposer {
public:
    AaasComposer() {
        kmsg_log("[AaasComposer] Service instance initialized\n");
    }

    ::ndk::ScopedAStatus createClient(std::shared_ptr<IComposerClient>* _aidl_return) override {
        kmsg_log("[AaasComposer] createClient() requested by SurfaceFlinger\n");
        auto rawClient = ::ndk::SharedRefBase::make<AaasComposerClient>();
        *_aidl_return = ::ndk::SharedRefBase::make<IComposerClientDelegator>(rawClient);
        kmsg_log("[AaasComposer] Returning delegated AidlComposerClient\n");
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getCapabilities(std::vector<Capability>* _aidl_return) override {
        kmsg_log("[AaasComposer] getCapabilities() queried\n");
        _aidl_return->clear();
        return ::ndk::ScopedAStatus::ok();
    }
};

int main(int argc, char** argv, char** envp) {
    (void)argc; (void)argv; (void)envp;
    kmsg_log("============================================================\n");
    kmsg_log("=== AaaS Native AIDL Composer3 Service Starting (M1B.7)  ===\n");
    kmsg_log("============================================================\n");

    // Initialize transport to host Wayland presenter
    const char* transport_sock = "/dev/aaas/wayland.sock";
    kmsg_log("[AaasComposer] Connecting to transport socket at %s\n", transport_sock);
    AaasTransport::getInstance().initialize(transport_sock);

    auto composer = ::ndk::SharedRefBase::make<AaasComposer>();
    if (!composer) {
        kmsg_log("[AaasComposer] FATAL: Failed to allocate AaasComposer\n");
        return 1;
    }

    const std::string instance = std::string(IComposer::descriptor) + "/default";
    kmsg_log("[AaasComposer] Registering service with ServiceManager: %s\n", instance.c_str());

    binder_status_t status = AServiceManager_addService(composer->asBinder().get(), instance.c_str());
    if (status != STATUS_OK) {
        kmsg_log("[AaasComposer] FATAL: AServiceManager_addService failed with status: %d\n", status);
        return 2;
    }

    kmsg_log("[AaasComposer] Successfully registered %s with ServiceManager!\n", instance.c_str());

    ABinderProcess_setThreadPoolMaxThreadCount(4);
    ABinderProcess_startThreadPool();
    kmsg_log("[AaasComposer] Binder thread pool started, joining thread pool...\n");

    ABinderProcess_joinThreadPool();
    kmsg_log("[AaasComposer] Exiting thread pool\n");
    return 0;
}
