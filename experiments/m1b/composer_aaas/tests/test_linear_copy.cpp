#include "../linear_copy.h"

#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

static void require(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main() {
    constexpr size_t width = 3;
    constexpr size_t height = 2;
    constexpr size_t source_stride = 5;
    constexpr size_t destination_stride = 6;
    constexpr size_t bpp = 4;
    const size_t source_size = source_stride * height * bpp;
    const size_t destination_size = destination_stride * height * bpp;

    int source_fd = memfd_create("aaas-copy-source", MFD_CLOEXEC);
    int destination_fd = memfd_create("aaas-copy-destination", MFD_CLOEXEC);
    require(source_fd >= 0 && destination_fd >= 0, "create independent memfds");
    require(ftruncate(source_fd, source_size) == 0, "size source backing");
    require(ftruncate(destination_fd, destination_size) == 0, "size destination backing");
    struct stat source_stat = {}, destination_stat = {};
    require(fstat(source_fd, &source_stat) == 0 && fstat(destination_fd, &destination_stat) == 0,
            "stat backing objects");
    require(source_stat.st_dev != destination_stat.st_dev ||
                source_stat.st_ino != destination_stat.st_ino,
            "source and destination are distinct backing objects");

    auto* source = static_cast<unsigned char*>(mmap(nullptr, source_size,
            PROT_READ | PROT_WRITE, MAP_SHARED, source_fd, 0));
    auto* destination = static_cast<unsigned char*>(mmap(nullptr, destination_size,
            PROT_READ | PROT_WRITE, MAP_SHARED, destination_fd, 0));
    require(source != MAP_FAILED && destination != MAP_FAILED, "map distinct backing objects");
    std::memset(source, 0x3C, source_size);
    std::memset(destination, 0xA5, destination_size);

    for (size_t y = 0; y < height; ++y) {
        for (size_t x = 0; x < width * bpp; ++x) {
            source[y * source_stride * bpp + x] = static_cast<unsigned char>(1 + y * 32 + x);
        }
    }

    require(copyLinearRows(source, source_stride, destination, destination_stride,
                           width, height, bpp), "copy visible rows across distinct backings");
    for (size_t y = 0; y < height; ++y) {
        const size_t source_row = y * source_stride * bpp;
        const size_t destination_row = y * destination_stride * bpp;
        require(std::memcmp(source + source_row, destination + destination_row,
                            width * bpp) == 0,
                "visible row pixels copied exactly");
        for (size_t x = width * bpp; x < destination_stride * bpp; ++x) {
            require(destination[destination_row + x] == 0xA5,
                    "destination row padding remains untouched");
        }
    }

    require(!copyLinearRows(source, width - 1, destination, destination_stride,
                            width, height, bpp), "reject source stride smaller than width");
    require(!copyLinearRows(source, source_stride, destination, width - 1,
                            width, height, bpp), "reject destination stride smaller than width");
    require(!copyLinearRows(nullptr, source_stride, destination, destination_stride,
                            width, height, bpp), "reject null source");

    munmap(source, source_size);
    munmap(destination, destination_size);
    close(source_fd);
    close(destination_fd);
    std::puts("linear copy tests passed; distinct memfd backing, stride, pixels, and errors verified");
    return 0;
}
