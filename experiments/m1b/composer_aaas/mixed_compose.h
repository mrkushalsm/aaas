#ifndef AAAS_MIXED_COMPOSE_H
#define AAAS_MIXED_COMPOSE_H

#include <cstddef>
#include <cstdint>
#include <limits>

enum class AaasBlendMode : int {
    None = 1,
    Premultiplied = 2,
    Coverage = 3,
};

// Blend one unscaled, untransformed RGBA/BGRA layer over a linear target.
// Both buffers use byte-addressed 4-byte pixels and pixel strides. The caller
// validates matching formats, fences, DMA_BUF_IOCTL_SYNC, and mapping extent.
inline bool composeLinearLayer(const void* source, size_t source_width,
                               size_t source_height, size_t source_stride_pixels,
                               void* destination, size_t destination_width,
                               size_t destination_height,
                               size_t destination_stride_pixels,
                               size_t source_x, size_t source_y,
                               size_t destination_x, size_t destination_y,
                               size_t width, size_t height,
                               AaasBlendMode blend_mode, float plane_alpha) {
    if (!source || !destination || source_width == 0 || source_height == 0 ||
        destination_width == 0 || destination_height == 0 ||
        source_stride_pixels == 0 || destination_stride_pixels == 0 ||
        width == 0 || height == 0 ||
        plane_alpha != plane_alpha || plane_alpha < 0.0f || plane_alpha > 1.0f ||
        source_stride_pixels < source_width ||
        destination_stride_pixels < destination_width ||
        source_x > source_width || width > source_width - source_x ||
        source_y > source_height || height > source_height - source_y ||
        destination_x > destination_width || width > destination_width - destination_x ||
        destination_y > destination_height || height > destination_height - destination_y ||
        source_stride_pixels > std::numeric_limits<size_t>::max() / 4 ||
        destination_stride_pixels > std::numeric_limits<size_t>::max() / 4 ||
        source_height > std::numeric_limits<size_t>::max() /
                                (source_stride_pixels * 4) ||
        destination_height > std::numeric_limits<size_t>::max() /
                                     (destination_stride_pixels * 4)) {
        return false;
    }
    if (blend_mode == AaasBlendMode::None && plane_alpha != 1.0f) return false;
    if (blend_mode != AaasBlendMode::None &&
        blend_mode != AaasBlendMode::Premultiplied &&
        blend_mode != AaasBlendMode::Coverage) return false;

    const auto* src = static_cast<const uint8_t*>(source);
    auto* dst = static_cast<uint8_t*>(destination);
    const size_t src_pitch = source_stride_pixels * 4;
    const size_t dst_pitch = destination_stride_pixels * 4;
    for (size_t row = 0; row < height; ++row) {
        const uint8_t* src_row = src + (source_y + row) * src_pitch + source_x * 4;
        uint8_t* dst_row = dst + (destination_y + row) * dst_pitch + destination_x * 4;
        for (size_t column = 0; column < width; ++column) {
            const uint8_t* s = src_row + column * 4;
            uint8_t* d = dst_row + column * 4;
            if (blend_mode == AaasBlendMode::None) {
                d[0] = s[0]; d[1] = s[1]; d[2] = s[2]; d[3] = s[3];
                continue;
            }
            const float source_alpha = (static_cast<float>(s[3]) / 255.0f) * plane_alpha;
            const float destination_weight = 1.0f - source_alpha;
            for (size_t channel = 0; channel < 3; ++channel) {
                float source_color = static_cast<float>(s[channel]) / 255.0f;
                if (blend_mode == AaasBlendMode::Coverage) source_color *= source_alpha;
                else source_color *= plane_alpha;
                const float destination_color = static_cast<float>(d[channel]) / 255.0f;
                const float result = source_color + destination_color * destination_weight;
                const float bounded = result < 0.0f ? 0.0f : (result > 1.0f ? 1.0f : result);
                d[channel] = static_cast<uint8_t>(bounded * 255.0f + 0.5f);
            }
            const float destination_alpha = static_cast<float>(d[3]) / 255.0f;
            const float result_alpha = source_alpha + destination_alpha * destination_weight;
            const float bounded_alpha = result_alpha < 0.0f ? 0.0f
                    : (result_alpha > 1.0f ? 1.0f : result_alpha);
            d[3] = static_cast<uint8_t>(bounded_alpha * 255.0f + 0.5f);
        }
    }
    return true;
}

// Independent scalar oracle used by deterministic tests and the opt-in live
// Mixed-composition diagnostic. It checks visible pixels only, leaving row
// padding outside the Android display's visible extent unspecified.
inline bool verifyLinearLayerResult(const void* client_target,
                                    size_t width, size_t height,
                                    size_t client_stride_pixels,
                                    const void* layer, size_t layer_width,
                                    size_t layer_height,
                                    size_t layer_stride_pixels,
                                    size_t source_x, size_t source_y,
                                    size_t destination_x, size_t destination_y,
                                    size_t layer_visible_width,
                                    size_t layer_visible_height,
                                    AaasBlendMode blend_mode,
                                    float plane_alpha,
                                    const void* output,
                                    size_t output_stride_pixels) {
    if (!client_target || !layer || !output || width == 0 || height == 0 ||
        layer_width == 0 || layer_height == 0 || layer_visible_width == 0 ||
        layer_visible_height == 0 ||
        client_stride_pixels < width || output_stride_pixels < width ||
        layer_stride_pixels < layer_width ||
        destination_x > width || layer_visible_width > width - destination_x ||
        destination_y > height || layer_visible_height > height - destination_y ||
        source_x > layer_width || layer_visible_width > layer_width - source_x ||
        source_y > layer_height || layer_visible_height > layer_height - source_y ||
        client_stride_pixels > std::numeric_limits<size_t>::max() / 4 ||
        output_stride_pixels > std::numeric_limits<size_t>::max() / 4 ||
        layer_stride_pixels > std::numeric_limits<size_t>::max() / 4 ||
        height > std::numeric_limits<size_t>::max() / (client_stride_pixels * 4) ||
        height > std::numeric_limits<size_t>::max() / (output_stride_pixels * 4) ||
        layer_height > std::numeric_limits<size_t>::max() / (layer_stride_pixels * 4) ||
        plane_alpha != plane_alpha || plane_alpha < 0.0f || plane_alpha > 1.0f ||
        (blend_mode != AaasBlendMode::None &&
         blend_mode != AaasBlendMode::Premultiplied &&
         blend_mode != AaasBlendMode::Coverage) ||
        (blend_mode == AaasBlendMode::None && plane_alpha != 1.0f)) return false;
    const auto* base = static_cast<const uint8_t*>(client_target);
    const auto* overlay = static_cast<const uint8_t*>(layer);
    const auto* actual = static_cast<const uint8_t*>(output);
    for (size_t y = 0; y < height; ++y) {
        const uint8_t* base_row = base + y * client_stride_pixels * 4;
        const uint8_t* actual_row = actual + y * output_stride_pixels * 4;
        for (size_t x = 0; x < width; ++x) {
            const uint8_t* expected = base_row + x * 4;
            uint8_t composed[4] = {expected[0], expected[1], expected[2], expected[3]};
            if (x >= destination_x && x - destination_x < layer_visible_width &&
                y >= destination_y && y - destination_y < layer_visible_height) {
                const size_t lx = source_x + x - destination_x;
                const size_t ly = source_y + y - destination_y;
                const uint8_t* src = overlay + ly * layer_stride_pixels * 4 + lx * 4;
                if (blend_mode == AaasBlendMode::None) {
                    composed[0] = src[0]; composed[1] = src[1];
                    composed[2] = src[2]; composed[3] = src[3];
                } else {
                    const double alpha = (static_cast<double>(src[3]) / 255.0) * plane_alpha;
                    const double inverse = 1.0 - alpha;
                    for (size_t c = 0; c < 3; ++c) {
                        double source_color = static_cast<double>(src[c]) / 255.0;
                        source_color *= blend_mode == AaasBlendMode::Coverage
                                ? alpha : plane_alpha;
                        const double dst_color = static_cast<double>(composed[c]) / 255.0;
                        const double value = (source_color + dst_color * inverse) * 255.0;
                        composed[c] = static_cast<uint8_t>(value < 0.0 ? 0.0
                                : (value > 255.0 ? 255.0 : value + 0.5));
                    }
                    const double old_alpha = static_cast<double>(composed[3]) / 255.0;
                    const double value = (alpha + old_alpha * inverse) * 255.0;
                    composed[3] = static_cast<uint8_t>(value < 0.0 ? 0.0
                            : (value > 255.0 ? 255.0 : value + 0.5));
                }
            }
            const uint8_t* got = actual_row + x * 4;
            if (got[0] != composed[0] || got[1] != composed[1] ||
                got[2] != composed[2] || got[3] != composed[3]) return false;
        }
    }
    return true;
}

#endif
