#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <stdarg.h>
#include <limits>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <linux/dma-buf.h>
#include <poll.h>

#include <atomic>
#include <chrono>
#include <memory>
#include <string>
#include <thread>
#include <vector>
#include <set>
#include <mutex>
#include <unordered_map>

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
#include "linear_copy.h"
#include "mixed_compose.h"
#include "virtual_transport_pool.h"

#ifndef AAAS_DISPLAY_WIDTH
#define AAAS_DISPLAY_WIDTH 1280
#endif
#ifndef AAAS_DISPLAY_HEIGHT
#define AAAS_DISPLAY_HEIGHT 720
#endif
#ifndef AAAS_VIRTUAL_DISPLAY_CAPACITY
#define AAAS_VIRTUAL_DISPLAY_CAPACITY 1
#endif

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

struct VirtualBufferSlot {
    int dma_fd = -1;
    int acquire_fence = -1;
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t stride = 0;
    uint32_t format = 0;
    uint32_t allocation_size = 0;
    uint64_t buffer_id = 0;
    uint64_t generation = 0;
};

struct VirtualLayerBufferSlot {
    int dma_fd = -1;
    int acquire_fence = -1;
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t stride = 0;
    uint32_t format = 0;
    uint32_t allocation_size = 0;
    uint64_t buffer_id = 0;
};

struct VirtualLayerState {
    int64_t id = 0;
    int requested_composition = -1;
    int selected_composition = static_cast<int>(Composition::CLIENT);
    int buffer_slot = -1;
    std::vector<VirtualLayerBufferSlot> buffers;
    bool has_display_frame = false;
    Rect display_frame;
    bool has_source_crop = false;
    FRect source_crop;
    bool has_blend_mode = false;
    BlendMode blend_mode = BlendMode::INVALID;
    bool has_plane_alpha = false;
    float plane_alpha = 1.0f;
    bool has_transform = false;
    Transform transform = Transform::NONE;
    bool has_z = false;
    int32_t z = 0;
    bool has_color_transform = false;
    bool has_brightness = false;
    float brightness = 1.0f;
    bool has_luts = false;
};

struct VirtualDisplayState {
    std::mutex lock;
    bool destroyed = false;
    int32_t width = 0;
    int32_t height = 0;
    PixelFormat format = PixelFormat::UNSPECIFIED;
    std::vector<VirtualBufferSlot> output_slots;
    VirtualBufferSlot client_target[64];
    std::unordered_map<int64_t, VirtualLayerState> layers;
    int current_output_slot = -1;
    int current_client_slot = -1;
    int transport_slot = -1;
    uint32_t ownership_diagnostics = 0;
    uint32_t empty_frame_diagnostics = 0;
};

class AaasComposerClient : public IComposerClientDefault {
public:
    AaasComposerClient()
        : mNextLayerId(1), mCurrentClientTargetSlot(-1),
          mNeedsValidation(true), mVsyncEnabled(false), mRunning(true) {
#ifdef AAAS_ENABLE_VIRTUAL_DISPLAY
        for (int i = 0; i < AAAS_VIRTUAL_DISPLAY_CAPACITY; ++i) {
            auto transport = std::make_unique<AaasTransport>();
            std::string socket_path = AAAS_VIRTUAL_DISPLAY_SOCKET;
            if (i > 0) socket_path += "-" + std::to_string(i + 1);
            transport->initialize(socket_path);
            // Advertise only endpoints already listening. A display never
            // shares another display's transport object or slot namespace.
            for (int wait = 0; wait < 100 && !transport->isConnected(); ++wait) usleep(10000);
            const bool ready = transport->isConnected();
            kmsg_log("[AaasComposerClient] virtual transport slot=%d socket=%s ready=%d\n",
                     i, socket_path.c_str(), ready ? 1 : 0);
            mVirtualTransportPaths.push_back(socket_path);
            mVirtualTransportReady.push_back(ready);
            mVirtualTransportUsed.push_back(false);
            mVirtualTransports.push_back(std::move(transport));
        }
#endif
        kmsg_log("[AaasComposerClient] Instance created (M1B.7)\n");
    }

    ~AaasComposerClient() override {
        kmsg_log("[AaasComposerClient] Instance destroyed\n");
        mRunning = false;
        if (mVsyncThread.joinable()) {
            mVsyncThread.join();
        }
        for (auto& entry : mVirtualDisplays) {
            std::lock_guard<std::mutex> state_lock(entry.second->lock);
            entry.second->destroyed = true;
            closeVirtualDisplayState(*entry.second);
        }
        for (auto& transport : mVirtualTransports) transport->shutdown();
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
        int32_t width = AAAS_DISPLAY_WIDTH;
        int32_t height = AAAS_DISPLAY_HEIGHT;
        auto virtual_state = findVirtualDisplay(in_display);
        if (virtual_state) {
            std::lock_guard<std::mutex> state_lock(virtual_state->lock);
            width = virtual_state->width;
            height = virtual_state->height;
        }
        kmsg_log("[AaasComposerClient] getDisplayConfigurations(display=%ld) -> %dx%d@60Hz\n",
                 (long)in_display, width, height);
        DisplayConfiguration cfg;
        cfg.configId = 1;
        cfg.width = width;
        cfg.height = height;
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
        if (in_bufferSlotCount < 1 || in_bufferSlotCount > 256) {
            return ::ndk::ScopedAStatus::fromServiceSpecificError(IComposerClient::EX_BAD_PARAMETER);
        }
        int64_t layerId = mNextLayerId++;
        {
            std::lock_guard<std::mutex> lock(mLayerLock);
            mLayerDisplays.emplace(layerId, in_display);
        }
        // Virtual displays in the normal staged path accept SurfaceFlinger
        // client targets only. Track their layers in every build so validate
        // can explicitly negotiate CLIENT when SurfaceFlinger recreates the
        // virtual display after a resize. The optional mixed test may still
        // select one supported DEVICE layer below.
        if (auto state = findVirtualDisplay(in_display)) {
            std::lock_guard<std::mutex> state_lock(state->lock);
            VirtualLayerState layer;
            layer.id = layerId;
            layer.buffers.resize(static_cast<size_t>(in_bufferSlotCount));
            state->layers.emplace(layerId, std::move(layer));
        }
        mNeedsValidation = true;
        kmsg_log("[AaasComposerClient] createLayer(display=%ld, slotCount=%d) -> layerId=%ld\n",
                 (long)in_display, in_bufferSlotCount, (long)layerId);
        *_aidl_return = layerId;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus destroyLayer(int64_t in_display, int64_t in_layer) override {
        {
            std::lock_guard<std::mutex> lock(mLayerLock);
            auto it = mLayerDisplays.find(in_layer);
            if (it != mLayerDisplays.end() && it->second == in_display) {
                mLayerDisplays.erase(it);
            }
        }
        if (auto state = findVirtualDisplay(in_display)) {
            std::lock_guard<std::mutex> state_lock(state->lock);
            auto it = state->layers.find(in_layer);
            if (it != state->layers.end()) {
                for (auto& slot : it->second.buffers) {
                    if (slot.dma_fd >= 0) close(slot.dma_fd);
                    if (slot.acquire_fence >= 0) close(slot.acquire_fence);
                }
                state->layers.erase(it);
            }
        }
        mNeedsValidation = true;
        kmsg_log("[AaasComposerClient] destroyLayer(display=%ld, layerId=%ld)\n", (long)in_display, (long)in_layer);
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus executeCommands(const std::vector<DisplayCommand>& in_commands, std::vector<CommandResultPayload>* _aidl_return) override {
        kmsg_log("[AaasComposerClient] executeCommands: count=%zu\n", in_commands.size());
        static std::atomic<uint32_t> virtual_composition_diagnostics = 0;
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
                const int requested_composition = l.composition.has_value()
                        ? static_cast<int>(l.composition->composition) : -1;
                if (cmd.display >= 100 &&
                    virtual_composition_diagnostics.fetch_add(
                            1, std::memory_order_relaxed) < 64) {
                    const auto& frame = l.displayFrame;
                    const auto& crop = l.sourceCrop;
                    const int blend = l.blendMode.has_value()
                            ? static_cast<int>(l.blendMode->blendMode) : -1;
                    const int transform = l.transform.has_value()
                            ? static_cast<int>(l.transform->transform) : -1;
                    const float alpha = l.planeAlpha.has_value()
                            ? l.planeAlpha->alpha : -1.0f;
                    const int32_t z = l.z.has_value() ? l.z->z : -1;
                    kmsg_log("    [layer] id=%lld composition=%d buf=%d slot=%d has_h=%d fd=%d frame=%d,%d,%d,%d crop=%.2f,%.2f,%.2f,%.2f blend=%d alpha=%.3f transform=%d z=%d\n",
                             (long long)l.layer, requested_composition,
                             l.buffer.has_value(), slot, has_h, fd,
                             frame.has_value() ? frame->left : -1,
                             frame.has_value() ? frame->top : -1,
                             frame.has_value() ? frame->right : -1,
                             frame.has_value() ? frame->bottom : -1,
                             crop.has_value() ? crop->left : -1.0f,
                             crop.has_value() ? crop->top : -1.0f,
                             crop.has_value() ? crop->right : -1.0f,
                             crop.has_value() ? crop->bottom : -1.0f,
                             blend, alpha, transform, z);
                }
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
                if (auto virtual_state = findVirtualDisplay(cmd.display)) {
                    std::lock_guard<std::mutex> state_lock(virtual_state->lock);
                    if (!virtual_state->destroyed) updateVirtualLayer(*virtual_state, l);
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
                            mSlots[slot].width = AAAS_DISPLAY_WIDTH;
                            mSlots[slot].height = AAAS_DISPLAY_HEIGHT;
                            mSlots[slot].stride = AAAS_DISPLAY_WIDTH;
                            mSlots[slot].format = 1;
                        }
                    }
                    mCurrentClientTargetSlot = slot;
                    kmsg_log("[AaasComposerClient] ClientTarget: slot=%d %dx%d stride=%d fmt=%d dma_fd=%d acq_fence=%d\n",
                             slot, mSlots[slot].width, mSlots[slot].height, mSlots[slot].stride,
                             mSlots[slot].format, mSlots[slot].dma_fd, mSlots[slot].acquire_fence);
                }
                auto virtual_state = findVirtualDisplay(cmd.display);
                if (virtual_state) {
                    std::lock_guard<std::mutex> state_lock(virtual_state->lock);
                    if (!virtual_state->destroyed) {
                        updateVirtualBuffer(virtual_state->client_target, 64,
                                            ct.buffer, 0, 0);
                        if (slot >= 0 && slot < 64) {
                            virtual_state->current_client_slot = slot;
                        }
                    }
                }
            }

            if (cmd.virtualDisplayOutputBuffer.has_value()) {
                auto virtual_state = findVirtualDisplay(cmd.display);
                if (virtual_state) {
                    std::lock_guard<std::mutex> state_lock(virtual_state->lock);
                    if (!virtual_state->destroyed &&
                        !updateVirtualBuffer(virtual_state->output_slots.data(),
                                             virtual_state->output_slots.size(),
                                             *cmd.virtualDisplayOutputBuffer,
                                             0, 0)) {
                        kmsg_log("[AaasComposerClient] invalid virtual output buffer display=%lld slot=%d\n",
                                 (long long)cmd.display,
                                 cmd.virtualDisplayOutputBuffer->slot);
                    } else if (!virtual_state->destroyed) {
                        virtual_state->current_output_slot = cmd.virtualDisplayOutputBuffer->slot;
                        const auto& output = virtual_state->output_slots[
                                virtual_state->current_output_slot];
                        if (output.width >= 64 && output.height >= 64 &&
                            output.width <= 4096 && output.height <= 4096) {
                            if (virtual_state->width != static_cast<int32_t>(output.width) ||
                                virtual_state->height != static_cast<int32_t>(output.height)) {
                                kmsg_log("[AaasComposerClient] virtual display resize observed display=%lld old=%dx%d new=%ux%u\n",
                                         (long long)cmd.display, virtual_state->width,
                                         virtual_state->height, output.width, output.height);
                            }
                            virtual_state->width = static_cast<int32_t>(output.width);
                            virtual_state->height = static_cast<int32_t>(output.height);
                        }
                    }
                }
            }

            // 2. Handle composition negotiation and validation
            if (cmd.acceptDisplayChanges) {
                mNeedsValidation = false;
            }

            if (cmd.validateDisplay) {
                ChangedCompositionTypes cct;
                cct.display = cmd.display;
                if (auto virtual_state = findVirtualDisplay(cmd.display)) {
                    std::lock_guard<std::mutex> state_lock(virtual_state->lock);
                    VirtualLayerState* device_layer =
                            virtual_state->destroyed ? nullptr : selectTestDeviceLayer(*virtual_state);
                    for (auto& [layer_id, layer] : virtual_state->layers) {
                        const int selected = device_layer && device_layer->id == layer_id
                                ? static_cast<int>(Composition::DEVICE)
                                : static_cast<int>(Composition::CLIENT);
                        layer.selected_composition = selected;
                        if (layer.requested_composition == selected) {
                            continue;
                        }
                        ChangedCompositionLayer ccl;
                        ccl.layer = layer_id;
                        ccl.composition = static_cast<Composition>(selected);
                        cct.layers.push_back(ccl);
                    }
                    kmsg_log("[AaasComposerClient] virtual composition display=%lld requested_layers=%zu selected_device_layer=%lld\n",
                             (long long)cmd.display, virtual_state->layers.size(),
                             device_layer ? (long long)device_layer->id : -1LL);
                } else {
                    std::lock_guard<std::mutex> lock(mLayerLock);
                    for (const auto& [layerId, ownerDisplay] : mLayerDisplays) {
                        if (ownerDisplay != cmd.display) continue;
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
                if (auto virtual_state = findVirtualDisplay(cmd.display)) {
                    std::lock_guard<std::mutex> state_lock(virtual_state->lock);
                    VirtualLayerState* device_layer =
                            virtual_state->destroyed ? nullptr : selectTestDeviceLayer(*virtual_state);
                    for (auto& [layer_id, layer] : virtual_state->layers) {
                        const int selected = device_layer && device_layer->id == layer_id
                                ? static_cast<int>(Composition::DEVICE)
                                : static_cast<int>(Composition::CLIENT);
                        layer.selected_composition = selected;
                        if (layer.requested_composition == selected) {
                            continue;
                        }
                        ChangedCompositionLayer ccl;
                        ccl.layer = layer_id;
                        ccl.composition = static_cast<Composition>(selected);
                        cct.layers.push_back(ccl);
                    }
                    kmsg_log("[AaasComposerClient] virtual composition display=%lld requested_layers=%zu selected_device_layer=%lld\n",
                             (long long)cmd.display, virtual_state->layers.size(),
                             device_layer ? (long long)device_layer->id : -1LL);
                } else {
                    std::lock_guard<std::mutex> lock(mLayerLock);
                    for (const auto& [layerId, ownerDisplay] : mLayerDisplays) {
                        if (ownerDisplay != cmd.display) continue;
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
                bool presented = false;
                auto virtual_state = findVirtualDisplay(cmd.display);
                if (virtual_state) {
                    std::lock_guard<std::mutex> state_lock(virtual_state->lock);
                    presented = !virtual_state->destroyed &&
                        presentVirtualDisplayFrame(cmd.display, *virtual_state,
                                                   command_index, _aidl_return);
                } else {
                    presented = presentCurrentFrame(cmd.display, command_index, _aidl_return);
                }
                if (!presented) {
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
        if (availableVirtualDisplayCount() == 0) {
            return ::ndk::ScopedAStatus::fromServiceSpecificError(IComposerClient::EX_UNSUPPORTED);
        }
        if (in_width <= 0 || in_height <= 0 || in_width > 4096 || in_height > 4096 ||
            // Android 16 SurfaceFlinger currently requests one HAL output
            // buffer slot for each virtual display (AidlComposer.cpp).
            in_outputBufferSlotCount < 1 || in_outputBufferSlotCount > 64 ||
            (in_formatHint != PixelFormat::RGBA_8888 &&
             in_formatHint != PixelFormat::BGRA_8888 &&
             in_formatHint != PixelFormat::IMPLEMENTATION_DEFINED)) {
            return ::ndk::ScopedAStatus::fromServiceSpecificError(IComposerClient::EX_UNSUPPORTED);
        }
        std::lock_guard<std::mutex> lock(mVirtualDisplayLock);
        const int transport_slot = reserveVirtualTransport(
                mVirtualTransportReady, mVirtualTransportUsed);
        if (transport_slot < 0) {
            return ::ndk::ScopedAStatus::fromServiceSpecificError(IComposerClient::EX_NO_RESOURCES);
        }
        const int64_t id = mNextVirtualDisplayId++;
        auto state = std::make_shared<VirtualDisplayState>();
        state->width = in_width;
        state->height = in_height;
        state->format = in_formatHint;
        state->transport_slot = transport_slot;
        state->output_slots.resize(static_cast<size_t>(in_outputBufferSlotCount));
        mVirtualDisplays.emplace(id, std::move(state));
        mVirtualTransportUsed[transport_slot] = true;
        _aidl_return->display = id;
        _aidl_return->format = in_formatHint;
        kmsg_log("[AaasComposerClient] createVirtualDisplay id=%lld size=%dx%d slots=%d format=%d\n",
                 (long long)id, in_width, in_height, in_outputBufferSlotCount,
                 static_cast<int>(in_formatHint));
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus destroyVirtualDisplay(int64_t in_display) override {
        std::shared_ptr<VirtualDisplayState> state;
        {
            std::lock_guard<std::mutex> lock(mVirtualDisplayLock);
            auto it = mVirtualDisplays.find(in_display);
            if (it == mVirtualDisplays.end()) {
                return ::ndk::ScopedAStatus::fromServiceSpecificError(IComposerClient::EX_BAD_DISPLAY);
            }
            state = it->second;
            mVirtualDisplays.erase(it);
        }
        int transport_slot = -1;
        {
            std::lock_guard<std::mutex> state_lock(state->lock);
            state->destroyed = true;
            transport_slot = state->transport_slot;
            closeVirtualDisplayState(*state);
        }
        if (transport_slot >= 0 &&
            static_cast<size_t>(transport_slot) < mVirtualTransportUsed.size()) {
            std::lock_guard<std::mutex> lock(mVirtualDisplayLock);
            // Presenter processes keep their socket listener alive when an app
            // closes. Recycle the Composer transport connection synchronously
            // so a later virtual display can reuse this endpoint safely.
            const size_t index = static_cast<size_t>(transport_slot);
            mVirtualTransportReady[index] = false;
            mVirtualTransportUsed[index] = true;
            mVirtualTransports[index]->shutdown();
            const bool reconnected = mVirtualTransports[index]->initialize(
                    mVirtualTransportPaths[index]);
            for (int wait = 0; reconnected && wait < 200 &&
                    !mVirtualTransports[index]->isConnected(); ++wait) usleep(10000);
            mVirtualTransportReady[index] = reconnected &&
                    mVirtualTransports[index]->isConnected();
            mVirtualTransportUsed[index] = false;
            kmsg_log("[AaasComposerClient] recycled virtual transport slot=%d ready=%d\n",
                     transport_slot, mVirtualTransportReady[index] ? 1 : 0);
        }
        kmsg_log("[AaasComposerClient] destroyVirtualDisplay id=%lld\n", (long long)in_display);
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus getOverlaySupport(OverlayProperties* _aidl_return) override {
        (void)_aidl_return;
        return ::ndk::ScopedAStatus::fromServiceSpecificError(IComposerClient::EX_UNSUPPORTED);
    }

    ::ndk::ScopedAStatus getMaxVirtualDisplayCount(int32_t* _aidl_return) override {
        *_aidl_return = availableVirtualDisplayCount();
        kmsg_log("[AaasComposerClient] getMaxVirtualDisplayCount -> %d independent transports ready\n",
                 *_aidl_return);
        return ::ndk::ScopedAStatus::ok();
    }

private:
    std::shared_ptr<VirtualDisplayState> findVirtualDisplay(int64_t display) {
        std::lock_guard<std::mutex> lock(mVirtualDisplayLock);
        auto it = mVirtualDisplays.find(display);
        return it == mVirtualDisplays.end() ? nullptr : it->second;
    }

    int32_t availableVirtualDisplayCount() const {
        int32_t count = 0;
        for (bool ready : mVirtualTransportReady) if (ready) ++count;
        return count;
    }

    static void closeVirtualSlot(VirtualBufferSlot& slot) {
        if (slot.dma_fd >= 0) close(slot.dma_fd);
        if (slot.acquire_fence >= 0) close(slot.acquire_fence);
        slot = VirtualBufferSlot{};
    }

    static void closeVirtualDisplayState(VirtualDisplayState& state) {
        for (auto& slot : state.output_slots) closeVirtualSlot(slot);
        for (auto& slot : state.client_target) closeVirtualSlot(slot);
        for (auto& [layer_id, layer] : state.layers) {
            (void)layer_id;
            for (auto& slot : layer.buffers) {
                if (slot.dma_fd >= 0) close(slot.dma_fd);
                if (slot.acquire_fence >= 0) close(slot.acquire_fence);
            }
        }
        state.layers.clear();
        state.current_output_slot = -1;
        state.current_client_slot = -1;
    }

    static bool updateVirtualBuffer(VirtualBufferSlot* slots, size_t slot_count,
                                    const Buffer& buffer, int32_t width,
                                    int32_t height) {
        if (buffer.slot < 0 || static_cast<size_t>(buffer.slot) >= slot_count) return false;
        auto& slot = slots[buffer.slot];
        int new_fence = buffer.fence.get() >= 0 ? dup(buffer.fence.get()) : -1;
        if (buffer.fence.get() >= 0 && new_fence < 0) return false;

        if (buffer.handle.has_value()) {
            const auto& handle = *buffer.handle;
            if (handle.fds.empty() || handle.ints.size() < 8 ||
                handle.fds[0].get() < 0 ||
                static_cast<uint32_t>(handle.ints[0]) != 0x61616173) {
                if (new_fence >= 0) close(new_fence);
                return false;
            }
            const uint32_t handle_width = static_cast<uint32_t>(handle.ints[1]);
            const uint32_t handle_height = static_cast<uint32_t>(handle.ints[2]);
            const uint32_t handle_stride = static_cast<uint32_t>(handle.ints[3]);
            const uint32_t handle_format = static_cast<uint32_t>(handle.ints[4]);
            if (handle_width < 64 || handle_height < 64 ||
                handle_width > 4096 || handle_height > 4096 ||
                (width > 0 && handle_width != static_cast<uint32_t>(width)) ||
                (height > 0 && handle_height != static_cast<uint32_t>(height)) ||
                handle_stride < handle_width || handle.ints[7] <= 0) {
                if (new_fence >= 0) close(new_fence);
                return false;
            }
            int new_dma = dup(handle.fds[0].get());
            if (new_dma < 0) {
                if (new_fence >= 0) close(new_fence);
                return false;
            }
            if (slot.dma_fd >= 0) close(slot.dma_fd);
            slot.dma_fd = new_dma;
            slot.width = handle_width;
            slot.height = handle_height;
            slot.stride = handle_stride;
            slot.format = handle_format;
            slot.allocation_size = static_cast<uint32_t>(handle.ints[7]);
            if (handle.ints.size() >= 10) {
                slot.buffer_id =
                        (static_cast<uint64_t>(static_cast<uint32_t>(handle.ints[9])) << 32) |
                        static_cast<uint32_t>(handle.ints[8]);
            } else {
                slot.buffer_id = 0;
            }
            ++slot.generation;
        } else if (slot.dma_fd < 0 ||
                   (width > 0 && slot.width != static_cast<uint32_t>(width)) ||
                   (height > 0 && slot.height != static_cast<uint32_t>(height))) {
            if (new_fence >= 0) close(new_fence);
            return false;
        }
        if (slot.acquire_fence >= 0) close(slot.acquire_fence);
        slot.acquire_fence = new_fence;
        return true;
    }

    static void updateVirtualLayer(VirtualDisplayState& state,
                                   const LayerCommand& command) {
        auto [it, inserted] = state.layers.try_emplace(command.layer);
        VirtualLayerState& layer = it->second;
        if (inserted) layer.id = command.layer;
        if (command.composition.has_value()) {
            layer.requested_composition =
                    static_cast<int>(command.composition->composition);
        }
        if (command.displayFrame.has_value()) {
            layer.display_frame = *command.displayFrame;
            layer.has_display_frame = true;
        }
        if (command.sourceCrop.has_value()) {
            layer.source_crop = *command.sourceCrop;
            layer.has_source_crop = true;
        }
        if (command.blendMode.has_value()) {
            layer.blend_mode = command.blendMode->blendMode;
            layer.has_blend_mode = true;
        }
        if (command.planeAlpha.has_value()) {
            layer.plane_alpha = command.planeAlpha->alpha;
            layer.has_plane_alpha = true;
        }
        if (command.transform.has_value()) {
            layer.transform = command.transform->transform;
            layer.has_transform = true;
        }
        if (command.z.has_value()) {
            layer.z = command.z->z;
            layer.has_z = true;
        }
        if (command.colorTransform.has_value()) layer.has_color_transform = true;
        if (command.brightness.has_value()) {
            layer.has_brightness = true;
            layer.brightness = command.brightness->brightness;
        }
        if (command.luts.has_value()) layer.has_luts = true;

        if (command.bufferSlotsToClear.has_value()) {
            for (int32_t slot_index : *command.bufferSlotsToClear) {
                if (slot_index < 0 || static_cast<size_t>(slot_index) >= layer.buffers.size()) continue;
                auto& slot = layer.buffers[static_cast<size_t>(slot_index)];
                if (slot.dma_fd >= 0) close(slot.dma_fd);
                if (slot.acquire_fence >= 0) close(slot.acquire_fence);
                slot = VirtualLayerBufferSlot{};
            }
        }
        if (!command.buffer.has_value()) return;

        const Buffer& buffer = *command.buffer;
        if (buffer.slot < 0 || static_cast<size_t>(buffer.slot) >= layer.buffers.size()) return;
        VirtualLayerBufferSlot& slot = layer.buffers[static_cast<size_t>(buffer.slot)];
        int new_fence = buffer.fence.get() >= 0 ? dup(buffer.fence.get()) : -1;
        if (buffer.fence.get() >= 0 && new_fence < 0) return;

        if (buffer.handle.has_value()) {
            const auto& handle = *buffer.handle;
            if (handle.fds.empty() || handle.fds[0].get() < 0 || handle.ints.size() < 8 ||
                static_cast<uint32_t>(handle.ints[0]) != 0x61616173) {
                if (new_fence >= 0) close(new_fence);
                return;
            }
            const uint32_t width = static_cast<uint32_t>(handle.ints[1]);
            const uint32_t height = static_cast<uint32_t>(handle.ints[2]);
            const uint32_t stride = static_cast<uint32_t>(handle.ints[3]);
            const uint32_t format = static_cast<uint32_t>(handle.ints[4]);
            const uint32_t allocation_size = static_cast<uint32_t>(handle.ints[7]);
            if (width == 0 || height == 0 || width > 4096 || height > 4096 ||
                stride < width || allocation_size == 0 ||
                (format != static_cast<uint32_t>(PixelFormat::RGBA_8888) &&
                 format != static_cast<uint32_t>(PixelFormat::BGRA_8888)) ||
                static_cast<uint64_t>(stride) * height * 4 > allocation_size) {
                if (new_fence >= 0) close(new_fence);
                return;
            }
            const int new_dma = dup(handle.fds[0].get());
            if (new_dma < 0) {
                if (new_fence >= 0) close(new_fence);
                return;
            }
            if (slot.dma_fd >= 0) close(slot.dma_fd);
            slot.dma_fd = new_dma;
            slot.width = width;
            slot.height = height;
            slot.stride = stride;
            slot.format = format;
            slot.allocation_size = allocation_size;
            slot.buffer_id = handle.ints.size() >= 10
                    ? (static_cast<uint64_t>(static_cast<uint32_t>(handle.ints[9])) << 32) |
                              static_cast<uint32_t>(handle.ints[8])
                    : 0;
        }
        if (slot.dma_fd < 0) {
            if (new_fence >= 0) close(new_fence);
            return;
        }
        if (slot.acquire_fence >= 0) close(slot.acquire_fence);
        slot.acquire_fence = new_fence;
        layer.buffer_slot = buffer.slot;
    }

    static VirtualLayerBufferSlot* layerBuffer(VirtualLayerState& layer) {
        if (layer.buffer_slot < 0 ||
            static_cast<size_t>(layer.buffer_slot) >= layer.buffers.size()) return nullptr;
        auto& slot = layer.buffers[static_cast<size_t>(layer.buffer_slot)];
        return slot.dma_fd >= 0 ? &slot : nullptr;
    }

    static const VirtualLayerBufferSlot* layerBuffer(const VirtualLayerState& layer) {
        if (layer.buffer_slot < 0 ||
            static_cast<size_t>(layer.buffer_slot) >= layer.buffers.size()) return nullptr;
        const auto& slot = layer.buffers[static_cast<size_t>(layer.buffer_slot)];
        return slot.dma_fd >= 0 ? &slot : nullptr;
    }

    static bool integralCoordinate(float value) {
        if (value != value || value < 0.0f || value > 4096.0f) return false;
        return static_cast<float>(static_cast<uint32_t>(value)) == value;
    }

    static bool supportsTestDeviceLayer(const VirtualDisplayState& state,
                                        const VirtualLayerState& layer) {
        if ((layer.requested_composition != static_cast<int>(Composition::DEVICE) &&
             layer.requested_composition != static_cast<int>(Composition::CLIENT)) ||
            !layer.has_display_frame || !layer.has_source_crop || !layer.has_blend_mode ||
            !layer.has_z || layer.has_color_transform ||
            (layer.has_brightness && layer.brightness != 1.0f) || layer.has_luts ||
            (layer.has_transform && layer.transform != Transform::NONE) ||
            layer.plane_alpha != layer.plane_alpha || layer.plane_alpha < 0.0f ||
            layer.plane_alpha > 1.0f ||
            (layer.blend_mode != BlendMode::NONE &&
             layer.blend_mode != BlendMode::PREMULTIPLIED &&
             layer.blend_mode != BlendMode::COVERAGE)) return false;
        if (layer.blend_mode == BlendMode::NONE && layer.plane_alpha != 1.0f) return false;
        const auto* buffer = layerBuffer(layer);
        if (!buffer ||
            (buffer->format != static_cast<uint32_t>(PixelFormat::RGBA_8888) &&
             buffer->format != static_cast<uint32_t>(PixelFormat::BGRA_8888))) return false;
        const auto& frame = layer.display_frame;
        const auto& crop = layer.source_crop;
        if (frame.left < 0 || frame.top < 0 || frame.right > state.width ||
            frame.bottom > state.height || frame.right <= frame.left || frame.bottom <= frame.top ||
            crop.left < 0.0f || crop.top < 0.0f ||
            !integralCoordinate(crop.left) || !integralCoordinate(crop.top) ||
            !integralCoordinate(crop.right) || !integralCoordinate(crop.bottom) ||
            crop.right <= crop.left || crop.bottom <= crop.top ||
            crop.right > buffer->width || crop.bottom > buffer->height ||
            crop.right - crop.left != frame.right - frame.left ||
            crop.bottom - crop.top != frame.bottom - frame.top) return false;
        return true;
    }

    static VirtualLayerState* selectTestDeviceLayer(VirtualDisplayState& state) {
#if defined(AAAS_ENABLE_MIXED_COMPOSITION_TEST)
        static std::atomic<uint32_t> selection_diagnostics = 0;
        VirtualLayerState* candidate = nullptr;
        size_t layer_count = 0;
        for (auto& [id, layer] : state.layers) {
            ++layer_count;
            const bool supported = supportsTestDeviceLayer(state, layer);
            if (selection_diagnostics.fetch_add(1, std::memory_order_relaxed) < 32) {
                const auto* buffer = layerBuffer(layer);
                kmsg_log("[AaasComposerClient] mixed-test eligibility layer=%lld supported=%d request=%d buffer_slot=%d buffer=%dx%d stride=%u fmt=%u alloc=%u frame=%d,%d,%d,%d crop=%.2f,%.2f,%.2f,%.2f blend=%d alpha=%.3f transform=%d z=%d extra=%d%d%d brightness=%.3f display=%dx%d\n",
                         (long long)id, supported ? 1 : 0,
                         layer.requested_composition, layer.buffer_slot,
                         buffer ? buffer->width : 0, buffer ? buffer->height : 0,
                         buffer ? buffer->stride : 0, buffer ? buffer->format : 0,
                         buffer ? buffer->allocation_size : 0,
                         layer.display_frame.left, layer.display_frame.top,
                         layer.display_frame.right, layer.display_frame.bottom,
                         layer.source_crop.left, layer.source_crop.top,
                         layer.source_crop.right, layer.source_crop.bottom,
                         static_cast<int>(layer.blend_mode), layer.plane_alpha,
                         static_cast<int>(layer.transform), layer.z,
                         layer.has_color_transform, layer.has_brightness, layer.has_luts,
                         layer.brightness, state.width, state.height);
            }
            if (supported &&
                (!candidate || layer.z > candidate->z)) candidate = &layer;
        }
        // Mixed composition must retain at least one CLIENT layer. Promoting
        // the only layer to DEVICE makes SurfaceFlinger omit ClientTarget,
        // which is outside this diagnostic client-target-copy contract.
        if (!candidate || layer_count < 2) return nullptr;
        for (const auto& [id, layer] : state.layers) {
            if (id == candidate->id) continue;
            if (!layer.has_display_frame || !layer.has_z || layer.z >= candidate->z) return nullptr;
        }
        return candidate;
#else
        (void)state;
        return nullptr;
#endif
    }

    static bool waitAcquireFence(int fd, int timeout_ms) {
        if (fd < 0) return true;
        struct pollfd pfd = {fd, POLLIN, 0};
        int result;
        do { result = poll(&pfd, 1, timeout_ms); } while (result < 0 && errno == EINTR);
        return result > 0 && (pfd.revents & POLLIN) != 0;
    }

    static bool syncDmaBufCpu(int fd, uint64_t flags) {
        struct dma_buf_sync sync = {};
        sync.flags = flags;
        int result;
        do { result = ioctl(fd, DMA_BUF_IOCTL_SYNC, &sync); } while (result < 0 && errno == EINTR);
        return result == 0;
    }

    bool presentVirtualDisplayFrame(int64_t display, VirtualDisplayState& state,
                                    size_t command_index,
                                    std::vector<CommandResultPayload>* results) {
        if (state.current_client_slot < 0 ||
            static_cast<size_t>(state.current_client_slot) >= 64) {
            if (state.empty_frame_diagnostics++ < 3) {
                kmsg_log("[AaasComposerClient] virtual display %lld has no client target yet\n",
                         (long long)display);
            }
            return false;
        }
        auto& source = state.client_target[state.current_client_slot];
        const bool has_output_buffer = state.current_output_slot >= 0 &&
                static_cast<size_t>(state.current_output_slot) < state.output_slots.size() &&
                state.output_slots[state.current_output_slot].dma_fd >= 0;
        // SurfaceFlinger omits virtualDisplayOutputBuffer for pure client
        // composition. In that AIDL path the ClientTarget is the complete
        // display image and is forwarded as the output allocation.
        auto& output = has_output_buffer
                ? state.output_slots[state.current_output_slot] : source;
        if (output.dma_fd < 0 || source.dma_fd < 0 || output.width != source.width ||
            output.height != source.height || output.width != static_cast<uint32_t>(state.width) ||
            output.height != static_cast<uint32_t>(state.height) || output.format != source.format) {
            kmsg_log("[AaasComposerClient] virtual display %lld incompatible buffers out=%dx%d fmt=%u src=%dx%d fmt=%u\n",
                     (long long)display, output.width, output.height, output.format,
                     source.width, source.height, source.format);
            return false;
        }
        struct stat out_stat = {}, source_stat = {};
        const int out_stat_rc = fstat(output.dma_fd, &out_stat);
        const int source_stat_rc = fstat(source.dma_fd, &source_stat);
        const bool aliases = out_stat_rc == 0 && source_stat_rc == 0 &&
                             out_stat.st_dev == source_stat.st_dev &&
                             out_stat.st_ino == source_stat.st_ino;
        if (state.ownership_diagnostics++ < 4) {
            kmsg_log("[AaasComposerClient] vdisplay ownership display=%lld out_slot=%d out_fd=%d out_stat=%d:%llu src_slot=%d src_fd=%d src_stat=%d:%llu alias=%d\n",
                     (long long)display, state.current_output_slot, output.dma_fd,
                     out_stat_rc == 0 ? (int)out_stat.st_dev : -1,
                     (unsigned long long)(out_stat_rc == 0 ? out_stat.st_ino : 0),
                     state.current_client_slot, source.dma_fd,
                     source_stat_rc == 0 ? (int)source_stat.st_dev : -1,
                     (unsigned long long)(source_stat_rc == 0 ? source_stat.st_ino : 0),
                     aliases ? 1 : 0);
        }
        if (out_stat_rc != 0 || source_stat_rc != 0) {
            kmsg_log("[AaasComposerClient] virtual display %lld dma-buf fstat failed output=%d source=%d errno=%d\n",
                     (long long)display, out_stat_rc, source_stat_rc, errno);
            return false;
        }
        if (aliases && output.stride != source.stride) {
            kmsg_log("[AaasComposerClient] virtual display %lld aliased buffers disagree on stride\n",
                     (long long)display);
            return false;
        }
        VirtualLayerState* device_layer = nullptr;
        for (auto& [layer_id, layer] : state.layers) {
            (void)layer_id;
            if (layer.selected_composition != static_cast<int>(Composition::DEVICE)) continue;
            if (device_layer) {
                kmsg_log("[AaasComposerClient] virtual display %lld has multiple selected device layers\n",
                         (long long)display);
                return false;
            }
            device_layer = &layer;
        }
        if (device_layer && !has_output_buffer) {
            kmsg_log("[AaasComposerClient] virtual display %lld selected device composition without an output buffer\n",
                     (long long)display);
            return false;
        }
        VirtualLayerBufferSlot* device_buffer = nullptr;
        if (device_layer) {
            if (!supportsTestDeviceLayer(state, *device_layer) || aliases ||
                device_layer->buffer_slot < 0) {
                kmsg_log("[AaasComposerClient] virtual display %lld selected device layer is not safely composable\n",
                         (long long)display);
                return false;
            }
            device_buffer = layerBuffer(*device_layer);
            if (!device_buffer || device_buffer->format != output.format) return false;
            struct stat layer_stat = {};
            if (fstat(device_buffer->dma_fd, &layer_stat) != 0 ||
                (layer_stat.st_dev == source_stat.st_dev && layer_stat.st_ino == source_stat.st_ino) ||
                (layer_stat.st_dev == out_stat.st_dev && layer_stat.st_ino == out_stat.st_ino)) {
                kmsg_log("[AaasComposerClient] virtual display %lld device layer backing aliases another composition allocation\n",
                         (long long)display);
                return false;
            }
        }
        if (!waitAcquireFence(source.acquire_fence, 1000) ||
            !waitAcquireFence(output.acquire_fence, 1000) ||
            (device_buffer && !waitAcquireFence(device_buffer->acquire_fence, 1000))) {
            kmsg_log("[AaasComposerClient] virtual display %lld acquire fence timeout\n",
                     (long long)display);
            return false;
        }

        const size_t size_limit = std::numeric_limits<size_t>::max();
        if (source.stride == 0 || output.stride == 0 ||
            source.height > size_limit / (static_cast<size_t>(source.stride) * 4) ||
            output.height > size_limit / (static_cast<size_t>(output.stride) * 4)) return false;
        const size_t source_size = static_cast<size_t>(source.stride) * source.height * 4;
        const size_t output_size = static_cast<size_t>(output.stride) * output.height * 4;
        if (source_size == 0 || source_size > source.allocation_size ||
            output_size == 0 || output_size > output.allocation_size) return false;
        // SurfaceFlinger can provide the same allocation in both AIDL fields.
        // This Composer reports every layer as CLIENT, so the client target is
        // already the complete composition in that case. Keep the output and
        // client-target slot records separate, wait both acquire fences, and
        // forward the output allocation without an overlapping self-copy.
        if (!aliases) {
            if (output.format != static_cast<uint32_t>(PixelFormat::RGBA_8888) &&
                output.format != static_cast<uint32_t>(PixelFormat::BGRA_8888)) {
                kmsg_log("[AaasComposerClient] virtual display %lld cannot CPU-copy format=%u\n",
                         (long long)display, output.format);
                return false;
            }
            if (!syncDmaBufCpu(source.dma_fd, DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ)) {
                kmsg_log("[AaasComposerClient] virtual display %lld source CPU-read sync failed errno=%d\n",
                         (long long)display, errno);
                return false;
            }
            bool layer_sync_started = false;
            if (device_buffer) {
                if (!syncDmaBufCpu(device_buffer->dma_fd,
                                   DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ)) {
                    const int sync_error = errno;
                    syncDmaBufCpu(source.dma_fd, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
                    kmsg_log("[AaasComposerClient] virtual display %lld device layer CPU-read sync failed errno=%d\n",
                             (long long)display, sync_error);
                    return false;
                }
                layer_sync_started = true;
            }
            if (!syncDmaBufCpu(output.dma_fd, DMA_BUF_SYNC_START | DMA_BUF_SYNC_WRITE)) {
                const int sync_error = errno;
                if (layer_sync_started) {
                    syncDmaBufCpu(device_buffer->dma_fd,
                                  DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
                }
                syncDmaBufCpu(source.dma_fd, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
                kmsg_log("[AaasComposerClient] virtual display %lld output CPU-write sync failed errno=%d\n",
                         (long long)display, sync_error);
                return false;
            }
            void* src = mmap(nullptr, source_size, PROT_READ, MAP_SHARED, source.dma_fd, 0);
            size_t device_size = 0;
            void* layer_ptr = MAP_FAILED;
            if (device_buffer) {
                if (device_buffer->stride == 0 ||
                    device_buffer->height > size_limit /
                            (static_cast<size_t>(device_buffer->stride) * 4)) {
                    if (src != MAP_FAILED) munmap(src, source_size);
                    syncDmaBufCpu(output.dma_fd, DMA_BUF_SYNC_END | DMA_BUF_SYNC_WRITE);
                    syncDmaBufCpu(device_buffer->dma_fd, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
                    syncDmaBufCpu(source.dma_fd, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
                    return false;
                }
                device_size = static_cast<size_t>(device_buffer->stride) *
                              device_buffer->height * 4;
                if (device_size == 0 || device_size > device_buffer->allocation_size) {
                    if (src != MAP_FAILED) munmap(src, source_size);
                    syncDmaBufCpu(output.dma_fd, DMA_BUF_SYNC_END | DMA_BUF_SYNC_WRITE);
                    syncDmaBufCpu(device_buffer->dma_fd, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
                    syncDmaBufCpu(source.dma_fd, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
                    return false;
                }
                layer_ptr = mmap(nullptr, device_size, PROT_READ, MAP_SHARED,
                                 device_buffer->dma_fd, 0);
            }
            void* dst = MAP_FAILED;
            bool copied = false;
            if (src != MAP_FAILED) {
                dst = mmap(nullptr, output_size, PROT_WRITE, MAP_SHARED, output.dma_fd, 0);
                if (dst != MAP_FAILED) {
                    copied = copyLinearRows(src, source.stride, dst, output.stride,
                                            state.width, state.height, 4);
                    if (copied && device_layer && layer_ptr != MAP_FAILED) {
                        const auto& frame_rect = device_layer->display_frame;
                        const auto& crop_rect = device_layer->source_crop;
                        const AaasBlendMode blend_mode =
                                static_cast<AaasBlendMode>(device_layer->blend_mode);
                        copied = composeLinearLayer(
                                layer_ptr, device_buffer->width, device_buffer->height,
                                device_buffer->stride, dst, output.width, output.height,
                                output.stride, static_cast<size_t>(crop_rect.left),
                                static_cast<size_t>(crop_rect.top),
                                static_cast<size_t>(frame_rect.left),
                                static_cast<size_t>(frame_rect.top),
                                static_cast<size_t>(frame_rect.right - frame_rect.left),
                                static_cast<size_t>(frame_rect.bottom - frame_rect.top),
                                blend_mode, device_layer->plane_alpha);
                    }
                    if (device_layer && layer_ptr == MAP_FAILED) copied = false;
#if defined(AAAS_ENABLE_MIXED_COMPOSITION_TEST)
                    if (copied && device_layer) {
                        copied = verifyLinearLayerResult(
                                src, output.width, output.height, source.stride,
                                layer_ptr, device_buffer->width, device_buffer->height,
                                device_buffer->stride,
                                static_cast<size_t>(device_layer->source_crop.left),
                                static_cast<size_t>(device_layer->source_crop.top),
                                static_cast<size_t>(device_layer->display_frame.left),
                                static_cast<size_t>(device_layer->display_frame.top),
                                static_cast<size_t>(device_layer->display_frame.right -
                                                    device_layer->display_frame.left),
                                static_cast<size_t>(device_layer->display_frame.bottom -
                                                    device_layer->display_frame.top),
                                static_cast<AaasBlendMode>(device_layer->blend_mode),
                                device_layer->plane_alpha, dst, output.stride);
                        struct stat layer_stat = {};
                        const bool have_layer_stat =
                                fstat(device_buffer->dma_fd, &layer_stat) == 0;
                        kmsg_log("[AaasComposerClient] mixed-frame verify display=%lld layer=%lld src_id=%llu dst_id=%llu layer_id=%llu src=%llu:%llu dst=%llu:%llu overlay=%llu:%llu pixels=%s\n",
                                 (long long)display, (long long)device_layer->id,
                                 (unsigned long long)source.buffer_id,
                                 (unsigned long long)output.buffer_id,
                                 (unsigned long long)device_buffer->buffer_id,
                                 (unsigned long long)source_stat.st_dev,
                                 (unsigned long long)source_stat.st_ino,
                                 (unsigned long long)out_stat.st_dev,
                                 (unsigned long long)out_stat.st_ino,
                                 (unsigned long long)(have_layer_stat ? layer_stat.st_dev : 0),
                                 (unsigned long long)(have_layer_stat ? layer_stat.st_ino : 0),
                                 copied ? "exact" : "mismatch");
                    }
#endif
                }
            }
            if (dst != MAP_FAILED) munmap(dst, output_size);
            if (layer_ptr != MAP_FAILED) munmap(layer_ptr, device_size);
            if (src != MAP_FAILED) munmap(src, source_size);
            const bool output_sync_ok = syncDmaBufCpu(output.dma_fd,
                    DMA_BUF_SYNC_END | DMA_BUF_SYNC_WRITE);
            const bool source_sync_ok = syncDmaBufCpu(source.dma_fd,
                    DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
            const bool layer_sync_ok = !layer_sync_started ||
                    syncDmaBufCpu(device_buffer->dma_fd,
                                  DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
            if (!copied || !output_sync_ok || !source_sync_ok || !layer_sync_ok) {
                kmsg_log("[AaasComposerClient] virtual display %lld distinct-backing compose failed copied=%d out_sync=%d src_sync=%d layer_sync=%d errno=%d\n",
                         (long long)display, copied ? 1 : 0,
                         output_sync_ok ? 1 : 0, source_sync_ok ? 1 : 0,
                         layer_sync_ok ? 1 : 0, errno);
                return false;
            }
        }

        AaasBufferSlot frame = {};
        frame.slot = static_cast<uint32_t>(has_output_buffer
                ? state.current_output_slot : state.current_client_slot);
        frame.id = frame.slot + 1;
        frame.dma_fd = output.dma_fd;
        frame.width = output.width;
        frame.height = output.height;
        frame.stride = output.stride;
        frame.format = output.format == static_cast<uint32_t>(PixelFormat::BGRA_8888)
                           ? 0x34325241 : 0x34324241;
        frame.modifier = 0;
        frame.is_linear = true;
        if (state.transport_slot < 0 ||
            static_cast<size_t>(state.transport_slot) >= mVirtualTransports.size()) return false;
        AaasTransport& transport = *mVirtualTransports[state.transport_slot];
        if (transport.submitFrame(frame) != 0 ||
            !transport.waitForSlotRelease(frame.slot, 250) ||
            !transport.isConnected()) {
            kmsg_log("[AaasComposerClient] virtual display %lld transport release timeout\n",
                     (long long)display);
            return false;
        }
        int release_fence = transport.takeReleaseFence(frame.slot);
        if (output.acquire_fence >= 0) {
            close(output.acquire_fence);
            output.acquire_fence = -1;
        }
        if (source.acquire_fence >= 0) {
            close(source.acquire_fence);
            source.acquire_fence = -1;
        }
        if (device_buffer && device_buffer->acquire_fence >= 0) {
            close(device_buffer->acquire_fence);
            device_buffer->acquire_fence = -1;
        }
        if (release_fence < 0) release_fence = create_signaled_fence();
        PresentFence present;
        present.display = display;
        present.fence = ::ndk::ScopedFileDescriptor(release_fence);
        results->push_back(CommandResultPayload::make<CommandResultPayload::Tag::presentFence>(
            std::move(present)));
        ReleaseFences releases;
        releases.display = display;
        if (device_layer) {
            ReleaseFences::Layer layer_release;
            layer_release.layer = device_layer->id;
            layer_release.fence = ::ndk::ScopedFileDescriptor(create_signaled_fence());
            releases.layers.push_back(std::move(layer_release));
        }
        results->push_back(CommandResultPayload::make<CommandResultPayload::Tag::releaseFences>(
            std::move(releases)));
        struct stat dma_stat = {};
        const bool have_dma_stat = output.dma_fd >= 0 && fstat(output.dma_fd, &dma_stat) == 0;
        kmsg_log("[AaasComposerClient] virtual output frame display=%lld slot=%u generation=%llu buffer_id=%llu width=%u height=%u stride=%u dma_dev=%llu dma_ino=%llu command=%zu\n",
                 (long long)display, frame.slot,
                 (unsigned long long)output.generation,
                 (unsigned long long)output.buffer_id, output.width, output.height,
                 output.stride,
                 static_cast<unsigned long long>(have_dma_stat ? dma_stat.st_dev : 0),
                 static_cast<unsigned long long>(have_dma_stat ? dma_stat.st_ino : 0),
                 command_index);
        return true;
    }

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
            for (const auto& [layerId, ownerDisplay] : mLayerDisplays) {
                if (ownerDisplay != display) continue;
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
    std::unordered_map<int64_t, int64_t> mLayerDisplays;

    ClientTargetSlot mSlots[64];
    std::mutex mVirtualDisplayLock;
    std::unordered_map<int64_t, std::shared_ptr<VirtualDisplayState>> mVirtualDisplays;
    int64_t mNextVirtualDisplayId = 100;
    std::vector<std::unique_ptr<AaasTransport>> mVirtualTransports;
    std::vector<std::string> mVirtualTransportPaths;
    std::vector<bool> mVirtualTransportReady;
    std::vector<bool> mVirtualTransportUsed;
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
