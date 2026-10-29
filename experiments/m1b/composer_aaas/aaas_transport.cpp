#include "aaas_transport.h"
#include "wire_v2.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <stdarg.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <poll.h>
#include <time.h>

struct sync_file_info {
    char name[32];
    int32_t status;
    uint32_t flags;
    uint32_t num_fences;
    uint32_t pad;
    uint64_t sync_fence_info;
};

#ifndef SYNC_IOC_FILE_INFO
#define SYNC_IOC_FILE_INFO _IOWR('>', 4, struct sync_file_info)
#endif

extern "C" int sync_file_is_valid(int fd) {
    if (fd < 0) return 0;
    struct sync_file_info info = {};
    if (ioctl(fd, SYNC_IOC_FILE_INFO, &info) < 0) {
        return 0;
    }
    return 1;
}

static void transport_log(const char* fmt, ...) {
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

AaasTransport& AaasTransport::getInstance() {
    static AaasTransport sInstance;
    return sInstance;
}

AaasTransport::AaasTransport()
    : mSockFd(-1), mGeneration(0), mWidth(1280), mHeight(720),
      mRunning(false), mConnected(false), mCopyCompleteSupported(false) {
    for (int i = 0; i < 64; i++) {
        mReleaseFences[i] = -1;
    }
}

AaasTransport::~AaasTransport() {
    shutdown();
}

bool AaasTransport::initialize(const std::string& socket_path) {
    std::lock_guard<std::mutex> lock(mLock);
    mSocketPath = socket_path;
    mRunning = true;

    if (!connectSocket()) {
        transport_log("[AaasTransport] Initial connection to %s failed (will retry in thread)\n", socket_path.c_str());
    }

    mThread = std::thread([this]() {
        transportThreadLoop();
    });

    return true;
}

void AaasTransport::shutdown() {
    mRunning = false;
    if (mSockFd >= 0) {
        ::shutdown(mSockFd, SHUT_RDWR);
        close(mSockFd);
        mSockFd = -1;
    }
    mConnected = false;

    if (mThread.joinable()) {
        mThread.join();
    }

    std::lock_guard<std::mutex> lock(mLock);
    for (int i = 0; i < 64; i++) {
        if (mReleaseFences[i] >= 0) {
            close(mReleaseFences[i]);
            mReleaseFences[i] = -1;
        }
    }
    mInFlightSlots.clear();
    mInFlightBackingInos.clear();
    mIdToSlot.clear();
    mIdToBackingIno.clear();
    mSourceReleasedIds.clear();
    mReleaseCv.notify_all();
}

bool AaasTransport::connectSocket() {
    if (mSockFd >= 0) {
        close(mSockFd);
        mSockFd = -1;
    }
    mConnected = false;

    int s = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
    if (s < 0) {
        transport_log("[AaasTransport] socket failed: %s\n", strerror(errno));
        return false;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, mSocketPath.c_str(), sizeof(addr.sun_path) - 1);

    if (connect(s, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        static int sLastErr = 0;
        if (errno != sLastErr) {
            transport_log("[AaasTransport] connect to %s failed: %s (errno=%d)\n", mSocketPath.c_str(), strerror(errno), errno);
            sLastErr = errno;
        }
        close(s);
        return false;
    }

    mSockFd = s;
    mConnected = true;
    transport_log("[AaasTransport] Connected to host presenter at %s (fd=%d)\n", mSocketPath.c_str(), s);

    // Send HELLO
    aaas_v2_msg hello = {};
    hello.magic = AAAS_V2_MAGIC;
    hello.version = AAAS_V2_VERSION;
    hello.type = AAAS_V2_HELLO;
    hello.flags = AAAS_V2_FLAG_COPY_COMPLETE;
    if (aaas_v2_send(mSockFd, &hello, nullptr, 0) != 0) {
        transport_log("[AaasTransport] Failed to send HELLO: %s\n", strerror(errno));
        close(mSockFd);
        mSockFd = -1;
        mConnected = false;
        return false;
    }
    transport_log("[AaasTransport] Protocol v2 HELLO sent successfully\n");
    return true;
}

void AaasTransport::transportThreadLoop() {
    while (mRunning) {
        if (!mConnected || mSockFd < 0) {
            usleep(500000);
            std::lock_guard<std::mutex> lock(mLock);
            if (mRunning) {
                connectSocket();
            }
            continue;
        }

        struct pollfd pfd = { .fd = mSockFd, .events = POLLIN, .revents = 0 };
        int r = poll(&pfd, 1, 200);
        if (r < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (r == 0) continue;

        if (pfd.revents & (POLLHUP | POLLERR)) {
            transport_log("[AaasTransport] Host presenter disconnected\n");
            std::lock_guard<std::mutex> lock(mLock);
            if (mSockFd >= 0) close(mSockFd);
            mSockFd = -1;
            mConnected = false;
            mInFlightSlots.clear();
            mInFlightBackingInos.clear();
            mReleaseCv.notify_all();
            continue;
        }

        if (pfd.revents & POLLIN) {
            aaas_v2_msg msg = {};
            int fds[AAAS_V2_MAX_FDS];
            unsigned nfds = 0;
            int ret = aaas_v2_recv(mSockFd, &msg, fds, &nfds);
            if (ret <= 0) {
                transport_log("[AaasTransport] recv error or eof: %d\n", ret);
                std::lock_guard<std::mutex> lock(mLock);
                if (mSockFd >= 0) close(mSockFd);
                mSockFd = -1;
                mConnected = false;
                mInFlightSlots.clear();
                mInFlightBackingInos.clear();
                mReleaseCv.notify_all();
                continue;
            }

            if (msg.type == AAAS_V2_RESIZE) {
                mGeneration.store(msg.generation);
                mWidth.store(msg.width);
                mHeight.store(msg.height);
                mCopyCompleteSupported.store(
                    (msg.flags & AAAS_V2_FLAG_COPY_COMPLETE) != 0);
                transport_log("[AaasTransport] Received RESIZE: %dx%d (generation=%u)\n",
                              msg.width, msg.height, msg.generation);
            } else if (msg.type == AAAS_V2_COPY_COMPLETE ||
                       msg.type == AAAS_V2_RELEASE) {
                int fence_fd = (nfds > 0 && fds[0] >= 0) ? fds[0] : -1;
                std::lock_guard<std::mutex> lock(mLock);
                auto it = mIdToSlot.find(msg.id);
                if (it != mIdToSlot.end()) {
                    uint32_t slot_idx = it->second;
                    const bool source_released =
                        mSourceReleasedIds.find(msg.id) != mSourceReleasedIds.end();
                    if (msg.type == AAAS_V2_COPY_COMPLETE) {
                        if (!source_released) {
                            auto id_ino = mIdToBackingIno.find(msg.id);
                            if (id_ino != mIdToBackingIno.end()) {
                                mInFlightBackingInos.erase(id_ino->second);
                                auto slot_ino = mSlotToBackingIno.find(slot_idx);
                                if (slot_ino != mSlotToBackingIno.end() &&
                                    slot_ino->second == id_ino->second) {
                                    mSlotToBackingIno.erase(slot_ino);
                                }
                            }
                            mInFlightSlots.erase(slot_idx);
                            mSourceReleasedIds.insert(msg.id);
                        }
                        transport_log("[AaasTransport] Source copy complete for slot %u id=%u\n",
                                      slot_idx, msg.id);
                        mReleaseCv.notify_all();
                    } else {
                        mIdToSlot.erase(it);
                        if (!source_released) {
                            mInFlightSlots.erase(slot_idx);
                            auto id_ino = mIdToBackingIno.find(msg.id);
                            if (id_ino != mIdToBackingIno.end()) {
                                mInFlightBackingInos.erase(id_ino->second);
                                auto slot_ino = mSlotToBackingIno.find(slot_idx);
                                if (slot_ino != mSlotToBackingIno.end() &&
                                    slot_ino->second == id_ino->second) {
                                    mSlotToBackingIno.erase(slot_ino);
                                }
                            }
                            if (slot_idx < 64) {
                                if (mReleaseFences[slot_idx] >= 0) {
                                    close(mReleaseFences[slot_idx]);
                                }
                                mReleaseFences[slot_idx] = fence_fd;
                                fence_fd = -1;
                            }
                        }
                        mIdToBackingIno.erase(msg.id);
                        mSourceReleasedIds.erase(msg.id);
                        transport_log("[AaasTransport] Received RELEASE for slot %u (id=%u, source_released=%d, remaining_in_flight=%zu)\n",
                                      slot_idx, msg.id, source_released,
                                      mInFlightSlots.size());
                        mReleaseCv.notify_all();
                    }
                    if (fence_fd >= 0) close(fence_fd);
                } else {
                    transport_log("[AaasTransport] Received %s for unknown id=%u\n",
                                  msg.type == AAAS_V2_COPY_COMPLETE ? "COPY_COMPLETE" : "RELEASE",
                                  msg.id);
                    if (fence_fd >= 0) close(fence_fd);
                }
                for (unsigned i = 1; i < nfds; ++i) {
                    if (fds[i] >= 0) close(fds[i]);
                }
            } else if (msg.type == AAAS_V2_CLOSE) {
                transport_log("[AaasTransport] Received CLOSE from host presenter\n");
                std::lock_guard<std::mutex> lock(mLock);
                if (mSockFd >= 0) close(mSockFd);
                mSockFd = -1;
                mConnected = false;
                mInFlightSlots.clear();
                mInFlightBackingInos.clear();
                mReleaseCv.notify_all();
            }
        }
    }
}

bool AaasTransport::waitForSlotRelease(uint32_t slot, uint32_t timeout_ms) {
    std::unique_lock<std::mutex> lock(mLock);
    if (!mConnected || mSockFd < 0) return true;
    if (mInFlightSlots.find(slot) == mInFlightSlots.end()) {
        return true;
    }
    transport_log("[AaasTransport] Backpressure: waiting for slot %u release (in_flight=%zu)...\n",
                  slot, mInFlightSlots.size());
    bool ok = mReleaseCv.wait_for(lock, std::chrono::milliseconds(timeout_ms), [this, slot]() {
        return !mConnected || mInFlightSlots.find(slot) == mInFlightSlots.end();
    });
    if (!ok) {
        transport_log("[AaasTransport] WARNING: Timeout waiting for slot %u release after %ums (in_flight=%zu)\n",
                      slot, timeout_ms, mInFlightSlots.size());
    } else {
        transport_log("[AaasTransport] Slot %u release confirmed (remaining in_flight=%zu)\n",
                      slot, mInFlightSlots.size());
    }
    return ok;
}

bool AaasTransport::waitForAnyRelease(uint32_t timeout_ms) {
    std::unique_lock<std::mutex> lock(mLock);
    if (!mConnected || mSockFd < 0 || mInFlightSlots.size() < 2) return true;
    transport_log("[AaasTransport] Backpressure: 2 buffers in flight, waiting for release...\n");
    bool ok = mReleaseCv.wait_for(lock, std::chrono::milliseconds(timeout_ms), [this]() {
        return !mConnected || mInFlightSlots.size() < 2;
    });
    if (!ok) {
        transport_log("[AaasTransport] WARNING: Timeout waiting for any release after %ums (in_flight=%zu)\n",
                      timeout_ms, mInFlightSlots.size());
    } else {
        transport_log("[AaasTransport] Buffer release confirmed (remaining in_flight=%zu)\n",
                      mInFlightSlots.size());
    }
    return ok;
}

bool AaasTransport::isSlotInFlight(uint32_t slot) {
    std::lock_guard<std::mutex> lock(mLock);
    return mInFlightSlots.find(slot) != mInFlightSlots.end();
}

size_t AaasTransport::getInFlightCount() {
    std::lock_guard<std::mutex> lock(mLock);
    return mInFlightSlots.size();
}

int AaasTransport::submitFrame(const AaasBufferSlot& frame) {
    if (frame.slot >= 64 || frame.dma_fd < 0) return -EINVAL;

    std::lock_guard<std::mutex> lock(mLock);
    if (!mConnected || mSockFd < 0) {
        transport_log("[AaasTransport] Cannot submitFrame: not connected\n");
        return -1;
    }
    if (mInFlightSlots.find(frame.slot) != mInFlightSlots.end()) {
        transport_log("[AaasTransport] Rejecting in-flight source slot %u\n", frame.slot);
        return -EBUSY;
    }

    struct stat backing = {};
    if (fstat(frame.dma_fd, &backing) != 0) {
        transport_log("[AaasTransport] fstat(dma_fd=%d) failed: %s\n",
                      frame.dma_fd, strerror(errno));
        return -errno;
    }
    if (mInFlightBackingInos.find(backing.st_ino) != mInFlightBackingInos.end()) {
        transport_log("[AaasTransport] Rejecting backing inode %llu while its source is in flight\n",
                      (unsigned long long)backing.st_ino);
        return -EBUSY;
    }

    uint32_t gen = mGeneration.load();
    if (gen == 0) gen = 1;

    uint32_t frame_id = mNextId++;
    mIdToSlot[frame_id] = frame.slot;
    mIdToBackingIno[frame_id] = backing.st_ino;
    mInFlightSlots.insert(frame.slot);
    mSlotToBackingIno[frame.slot] = backing.st_ino;
    mInFlightBackingInos.insert(backing.st_ino);

    aaas_v2_msg m = {};
    m.magic = AAAS_V2_MAGIC;
    m.version = AAAS_V2_VERSION;
    m.type = AAAS_V2_BUFFER;
    m.flags = (frame.acquire_fence_fd >= 0 ? AAAS_V2_FLAG_EXPLICIT_SYNC : 0) |
              (frame.is_linear ? AAAS_V2_FLAG_LINEAR : 0);
    m.generation = gen;
    m.id = frame_id;
    m.width = frame.width;
    m.height = frame.height;
    m.format = frame.format;
    m.num_planes = 1;
    m.modifier = frame.modifier;
    m.offset[0] = 0;
    m.stride[0] = frame.stride * 4;

    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    m.timestamp_ns = (uint64_t)ts.tv_sec * 1000000000ULL + ts.tv_nsec;

    int send_fds[2];
    unsigned nfds = 1;

    int dma_dup = dup(frame.dma_fd);
    if (dma_dup < 0) {
        transport_log("[AaasTransport] dup(dma_fd=%d) failed: %s\n", frame.dma_fd, strerror(errno));
        mInFlightSlots.erase(frame.slot);
        mInFlightBackingInos.erase(backing.st_ino);
        mSlotToBackingIno.erase(frame.slot);
        mIdToSlot.erase(frame_id);
        mIdToBackingIno.erase(frame_id);
        return -1;
    }
    send_fds[0] = dma_dup;

    if (frame.acquire_fence_fd >= 0) {
        int acq_dup = dup(frame.acquire_fence_fd);
        if (acq_dup >= 0) {
            send_fds[1] = acq_dup;
            nfds = 2;
        } else {
            close(send_fds[0]);
            mInFlightSlots.erase(frame.slot);
            mInFlightBackingInos.erase(backing.st_ino);
            mSlotToBackingIno.erase(frame.slot);
            mIdToSlot.erase(frame_id);
            mIdToBackingIno.erase(frame_id);
            return -errno;
        }
    }

    transport_log("[AaasTransport] Submitting frame id=%u (slot=%u, %dx%d, fmt=0x%x, stride=%u, dma_fd=%d, acq_fd=%d, backing_dev=%llu, backing_ino=%llu, in_flight=%zu)\n",
                  m.id, frame.slot, m.width, m.height, m.format, m.stride[0], send_fds[0], (nfds > 1 ? send_fds[1] : -1),
                  (unsigned long long)backing.st_dev, (unsigned long long)backing.st_ino, mInFlightSlots.size());

    int res = aaas_v2_send(mSockFd, &m, send_fds, nfds);
    close(send_fds[0]);
    if (nfds > 1) {
        close(send_fds[1]);
    }

    if (res != 0) {
        transport_log("[AaasTransport] aaas_v2_send failed: %s (errno=%d)\n", strerror(errno), errno);
        mInFlightSlots.erase(frame.slot);
        mInFlightBackingInos.erase(backing.st_ino);
        mSlotToBackingIno.erase(frame.slot);
        mIdToSlot.erase(frame_id);
        mIdToBackingIno.erase(frame_id);
        return -1;
    }

    transport_log("[AaasTransport] Frame id=%u submitted to host successfully!\n", m.id);
    return 0;
}

int AaasTransport::takeReleaseFence(uint32_t slot) {
    std::lock_guard<std::mutex> lock(mLock);
    if (slot >= 64) return -1;
    int fd = mReleaseFences[slot];
    mReleaseFences[slot] = -1;
    return fd;
}

