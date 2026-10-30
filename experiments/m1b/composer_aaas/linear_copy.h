#ifndef AAAS_LINEAR_COPY_H
#define AAAS_LINEAR_COPY_H

#include <cstddef>
#include <cstring>
#include <limits>

// Copy the visible pixels of a linear buffer while respecting pixel strides.
// The caller owns format validation, mapping lifetime, and DMA-BUF cache sync.
inline bool copyLinearRows(const void* source, size_t source_stride_pixels,
                           void* destination, size_t destination_stride_pixels,
                           size_t width_pixels, size_t height_pixels,
                           size_t bytes_per_pixel) {
    if (!source || !destination || width_pixels == 0 || height_pixels == 0 ||
        bytes_per_pixel == 0 || source_stride_pixels < width_pixels ||
        destination_stride_pixels < width_pixels ||
        width_pixels > std::numeric_limits<size_t>::max() / bytes_per_pixel ||
        source_stride_pixels > std::numeric_limits<size_t>::max() / bytes_per_pixel ||
        destination_stride_pixels > std::numeric_limits<size_t>::max() / bytes_per_pixel ||
        height_pixels > std::numeric_limits<size_t>::max() /
                            (source_stride_pixels * bytes_per_pixel) ||
        height_pixels > std::numeric_limits<size_t>::max() /
                            (destination_stride_pixels * bytes_per_pixel)) {
        return false;
    }

    const size_t row_bytes = width_pixels * bytes_per_pixel;
    const size_t source_stride_bytes = source_stride_pixels * bytes_per_pixel;
    const size_t destination_stride_bytes = destination_stride_pixels * bytes_per_pixel;
    const auto* src = static_cast<const unsigned char*>(source);
    auto* dst = static_cast<unsigned char*>(destination);
    for (size_t row = 0; row < height_pixels; ++row) {
        std::memcpy(dst + row * destination_stride_bytes,
                    src + row * source_stride_bytes, row_bytes);
    }
    return true;
}

#endif
