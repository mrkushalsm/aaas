#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <stdarg.h>

#include <atomic>
#include <chrono>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include <android/binder_ibinder.h>
#include <android/binder_manager.h>
#include <android/binder_process.h>
#include <android/binder_auto_utils.h>

#include <aidl/android/hardware/graphics/composer3/BnComposer.h>
#include <aidl/android/hardware/graphics/composer3/BnComposerClient.h>
#include <aidl/android/hardware/graphics/composer3/IComposerCallback.h>
#include <aidl/android/hardware/graphics/composer3/PresentOrValidate.h>
#include <aidl/android/hardware/graphics/composer3/PresentFence.h>
#include <aidl/android/hardware/graphics/composer3/ChangedCompositionTypes.h>
#include <aidl/android/hardware/graphics/composer3/DisplayRequest.h>
#include <aidl/android/hardware/graphics/common/DisplayHotplugEvent.h>
#include <aidl/android/hardware/graphics/composer3/DisplayConnectionType.h>
#include <aidl/android/hardware/graphics/common/Transform.h>
#include <aidl/android/hardware/graphics/common/PixelFormat.h>

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
        int fd = open("/dev/kmsg", O_WRONLY | O_APPEND);
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

class AaasComposerClient : public IComposerClientDefault {
public:
    AaasComposerClient() : mNextLayerId(1), mVsyncEnabled(false), mRunning(true) {
        kmsg_log("[AaasComposerClient] Instance created\n");
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
        *_aidl_return = layerId;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus destroyLayer(int64_t in_display, int64_t in_layer) override {
        (void)in_display; (void)in_layer;
        return ::ndk::ScopedAStatus::ok();
    }

    ::ndk::ScopedAStatus executeCommands(const std::vector<DisplayCommand>& in_commands, std::vector<CommandResultPayload>* _aidl_return) override {
        for (const auto& cmd : in_commands) {
            if (cmd.presentOrValidateDisplay) {
                PresentOrValidate pv;
                pv.display = cmd.display;
                pv.result = PresentOrValidate::Result::Presented;
                _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::presentOrValidateResult>(pv));

                PresentFence pf;
                pf.display = cmd.display;
                pf.fence = ::ndk::ScopedFileDescriptor(-1);
                _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::presentFence>(std::move(pf)));
            } else if (cmd.validateDisplay) {
                ChangedCompositionTypes cct;
                cct.display = cmd.display;
                _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::changedCompositionTypes>(cct));

                DisplayRequest dr;
                dr.display = cmd.display;
                dr.mask = 0;
                _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::displayRequest>(dr));
            } else if (cmd.presentDisplay) {
                PresentFence pf;
                pf.display = cmd.display;
                pf.fence = ::ndk::ScopedFileDescriptor(-1);
                _aidl_return->push_back(CommandResultPayload::make<CommandResultPayload::Tag::presentFence>(std::move(pf)));
            }
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
    kmsg_log("=== AaaS Native AIDL Composer3 Service Starting (M1B.6) ===\n");
    kmsg_log("============================================================\n");

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
