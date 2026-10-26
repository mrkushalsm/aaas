#pragma once

#include <stdint.h>
#include <string>
#include <vector>
#include <memory>
#include <mutex>
#include <atomic>
#include <thread>

#include <unordered_map>

struct AaasBufferSlot {
    int dma_fd = -1;
    int acquire_fence_fd = -1;
    int release_fence_fd = -1;
    uint32_t slot = 0;
    uint32_t id = 0;
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t stride = 0;
    uint32_t format = 0;
    uint64_t modifier = 0;
    bool is_linear = false;
};

class AaasTransport {
public:
    static AaasTransport& getInstance();

    bool initialize(const std::string& socket_path);
    void shutdown();
    bool isConnected() const { return mConnected.load(); }

    // Submit a frame buffer to host Wayland presenter
    int submitFrame(const AaasBufferSlot& frame);

    // Retrieve and clear any release fence returned by the host presenter for a buffer slot
    int takeReleaseFence(uint32_t slot);

    uint32_t getWidth() const { return mWidth.load(); }
    uint32_t getHeight() const { return mHeight.load(); }
    uint32_t getGeneration() const { return mGeneration.load(); }

private:
    AaasTransport();
    ~AaasTransport();

    void transportThreadLoop();
    bool connectSocket();

    std::string mSocketPath;
    int mSockFd;
    std::atomic<uint32_t> mGeneration;
    std::atomic<uint32_t> mWidth;
    std::atomic<uint32_t> mHeight;
    std::atomic<bool> mRunning;
    std::atomic<bool> mConnected;
    std::mutex mLock;
    std::thread mThread;

    int mReleaseFences[64];
    std::unordered_map<uint32_t, uint32_t> mIdToSlot;
    uint32_t mNextId = 1;
};
