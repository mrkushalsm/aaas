#pragma once

#include <stdint.h>
#include <string>
#include <vector>
#include <memory>
#include <mutex>
#include <atomic>
#include <thread>
#include <condition_variable>
#include <unordered_map>
#include <unordered_set>

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

    // Wait until a specific slot is released by the host presenter (not in flight)
    bool waitForSlotRelease(uint32_t slot, uint32_t timeout_ms = 40);

    // Wait until at least one buffer is released if both/all slots are in flight
    bool waitForAnyRelease(uint32_t timeout_ms = 40);

    // Check if slot is currently in flight on host
    bool isSlotInFlight(uint32_t slot);

    // Get number of in-flight slots
    size_t getInFlightCount();

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
    std::atomic<bool> mCopyCompleteSupported;
    std::mutex mLock;
    std::condition_variable mReleaseCv;
    std::thread mThread;

    int mReleaseFences[64];
    std::unordered_map<uint32_t, uint32_t> mIdToSlot;
    std::unordered_map<uint32_t, uint64_t> mIdToBackingIno;
    std::unordered_set<uint32_t> mSourceReleasedIds;
    std::unordered_set<uint32_t> mInFlightSlots;
    std::unordered_map<uint32_t, uint64_t> mSlotToBackingIno;
    std::unordered_set<uint64_t> mInFlightBackingInos;
    uint32_t mNextId = 1;
};
