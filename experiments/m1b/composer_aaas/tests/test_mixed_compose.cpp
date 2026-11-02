#include "../mixed_compose.h"

#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

#include <array>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

static void require(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

static bool sameBacking(int first, int second) {
    struct stat a = {}, b = {};
    return fstat(first, &a) == 0 && fstat(second, &b) == 0 &&
           a.st_dev == b.st_dev && a.st_ino == b.st_ino;
}

int main() {
    constexpr size_t source_stride = 5;
    constexpr size_t source_width = 3;
    constexpr size_t source_height = 2;
    constexpr size_t target_stride = 6;
    constexpr size_t target_width = 4;
    constexpr size_t target_height = 3;
    const size_t source_size = source_stride * source_height * 4;
    const size_t target_size = target_stride * target_height * 4;

    int source_fd = memfd_create("aaas-mixed-source", MFD_CLOEXEC);
    int target_fd = memfd_create("aaas-mixed-target", MFD_CLOEXEC);
    require(source_fd >= 0 && target_fd >= 0, "create source and target allocations");
    require(ftruncate(source_fd, source_size) == 0 && ftruncate(target_fd, target_size) == 0,
            "size backing allocations");
    const int source_alias_fd = dup(source_fd);
    require(source_alias_fd >= 0, "duplicate source descriptor");
    require(sameBacking(source_fd, source_alias_fd),
            "identity check recognizes duplicated backing as alias");
    require(!sameBacking(source_fd, target_fd),
            "identity check recognizes distinct backing allocations");

    auto* source = static_cast<uint8_t*>(mmap(nullptr, source_size,
            PROT_READ | PROT_WRITE, MAP_SHARED, source_fd, 0));
    auto* target = static_cast<uint8_t*>(mmap(nullptr, target_size,
            PROT_READ | PROT_WRITE, MAP_SHARED, target_fd, 0));
    require(source != MAP_FAILED && target != MAP_FAILED, "map independent allocations");
    std::memset(source, 0xCD, source_size);
    std::memset(target, 0x40, target_size);
    const std::vector<uint8_t> base(target, target + target_size);

    // A source overlay with premultiplied RGB, alpha 128, and padded rows.
    for (size_t y = 0; y < source_height; ++y) {
        for (size_t x = 0; x < source_width; ++x) {
            uint8_t* pixel = source + (y * source_stride + x) * 4;
            pixel[0] = 0x20;
            pixel[1] = 0x10;
            pixel[2] = 0x08;
            pixel[3] = 0x80;
        }
    }
    require(composeLinearLayer(source, source_width, source_height, source_stride,
                               target, target_width, target_height, target_stride,
                               0, 0, 1, 1, 2, 1,
                               AaasBlendMode::Premultiplied, 1.0f),
            "blend a bounded overlay rectangle");
    const uint8_t* blended = target + (1 * target_stride + 1) * 4;
    require(blended[0] == 0x40 && blended[1] == 0x30 &&
                blended[2] == 0x28 && blended[3] == 0xA0,
            "premultiplied blend produces expected visible pixel");
    require(target[(1 * target_stride + 3) * 4] == 0x40,
            "pixels outside overlay remain unchanged");
    require(target[(1 * target_stride + target_width) * 4] == 0x40,
            "destination row padding remains unchanged");
    require(source[(0 * source_stride + source_width) * 4] == 0xCD,
            "source row padding is not treated as visible pixels");
    require(verifyLinearLayerResult(base.data(), target_width, target_height,
                                   target_stride, source, source_width, source_height,
                                   source_stride, 0, 0, 1, 1, 2, 1,
                                   AaasBlendMode::Premultiplied, 1.0f,
                                   target, target_stride),
            "independent pixel oracle accepts the expected blended image");
    target[(1 * target_stride + 1) * 4] ^= 0x01;
    require(!verifyLinearLayerResult(base.data(), target_width, target_height,
                                    target_stride, source, source_width, source_height,
                                    source_stride, 0, 0, 1, 1, 2, 1,
                                    AaasBlendMode::Premultiplied, 1.0f,
                                    target, target_stride),
            "independent pixel oracle detects a changed output pixel");
    target[(1 * target_stride + 1) * 4] ^= 0x01;

    std::array<uint8_t, 4> replacement = {1, 2, 3, 255};
    std::array<uint8_t, 4> pixel = {9, 9, 9, 9};
    require(composeLinearLayer(replacement.data(), 1, 1, 1, pixel.data(), 1, 1, 1,
                               0, 0, 0, 0, 1, 1, AaasBlendMode::None, 1.0f),
            "opaque no-blend layer copies exact pixel");
    require(pixel == replacement, "opaque layer bytes match source");
    require(!composeLinearLayer(replacement.data(), 1, 1, 1, pixel.data(), 1, 1, 1,
                                0, 0, 0, 0, 1, 1, AaasBlendMode::None, 0.5f),
            "reject unsupported plane alpha with no-blend mode");
    require(!composeLinearLayer(source, source_width, source_height, source_stride,
                                target, target_width, target_height, target_stride,
                                0, 0, target_width, 0, 1, 1,
                                AaasBlendMode::Premultiplied, 1.0f),
            "reject destination rectangle outside visible extent");

    // A full odd-sized image copy exercises the final row and column with
    // independently padded source and destination pitches.
    constexpr size_t odd_width = 3, odd_height = 3;
    constexpr size_t odd_source_stride = 5, odd_target_stride = 4;
    std::array<uint8_t, odd_source_stride * odd_height * 4> odd_source{};
    std::array<uint8_t, odd_target_stride * odd_height * 4> odd_target{};
    odd_source.fill(0xE1);
    odd_target.fill(0x6B);
    for (size_t y = 0; y < odd_height; ++y) {
        for (size_t x = 0; x < odd_width; ++x) {
            uint8_t* p = odd_source.data() + (y * odd_source_stride + x) * 4;
            p[0] = static_cast<uint8_t>(10 + y * 30 + x);
            p[1] = static_cast<uint8_t>(20 + y * 30 + x);
            p[2] = static_cast<uint8_t>(30 + y * 30 + x);
            p[3] = 255;
        }
    }
    require(composeLinearLayer(odd_source.data(), odd_width, odd_height,
                               odd_source_stride, odd_target.data(), odd_width,
                               odd_height, odd_target_stride, 0, 0, 0, 0,
                               odd_width, odd_height, AaasBlendMode::None, 1.0f),
            "copy all visible pixels through odd final row and column");
    for (size_t y = 0; y < odd_height; ++y) {
        for (size_t x = 0; x < odd_width; ++x) {
            const uint8_t* s = odd_source.data() + (y * odd_source_stride + x) * 4;
            const uint8_t* d = odd_target.data() + (y * odd_target_stride + x) * 4;
            require(std::memcmp(s, d, 4) == 0,
                    "odd-sized copy preserves each visible pixel");
        }
        const uint8_t* pad = odd_target.data() + (y * odd_target_stride + odd_width) * 4;
        require(std::all_of(pad, pad + 4, [](uint8_t v) { return v == 0x6B; }),
                "odd-sized copy leaves destination row padding unchanged");
    }
    require(odd_source[(2 * odd_source_stride + odd_width) * 4] == 0xE1,
            "odd-sized copy does not read source padding as visible data");
    require(!composeLinearLayer(odd_source.data(), SIZE_MAX, odd_height,
                                odd_source_stride, odd_target.data(), odd_width,
                                odd_height, odd_target_stride, 0, 0, 0, 0,
                                odd_width, odd_height, AaasBlendMode::None, 1.0f),
            "reject overflowing source row extent before access");

    munmap(source, source_size);
    munmap(target, target_size);
    close(source_alias_fd);
    close(source_fd);
    close(target_fd);
    std::puts("mixed composition tests passed; backing identity, blend pixels, odd rows, strides, and bounds verified");
}
