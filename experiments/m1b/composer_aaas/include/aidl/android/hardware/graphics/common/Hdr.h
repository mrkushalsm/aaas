/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: /run/media/mrkus/Homework/aaas-workspace/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/composer/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/common/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/common/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/drm/common/aidl -h /home/mrkus/Work/personal/projects/aaas/experiments/m1b/composer_aaas/aidl_gen -o /home/mrkus/Work/personal/projects/aaas/experiments/m1b/composer_aaas/aidl_gen /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/common/aidl/android/hardware/graphics/common/Hdr.aidl
 *
 * DO NOT CHECK THIS FILE INTO A CODE TREE (e.g. git, etc..).
 * ALWAYS GENERATE THIS FILE FROM UPDATED AIDL COMPILER
 * AS A BUILD INTERMEDIATE ONLY. THIS IS NOT SOURCE CODE.
 */
#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>
#include <android/binder_enums.h>
#ifdef BINDER_STABILITY_SUPPORT
#include <android/binder_stability.h>
#endif  // BINDER_STABILITY_SUPPORT

namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace common {
enum class Hdr : int32_t {
  INVALID = 0,
  DOLBY_VISION = 1,
  HDR10 = 2,
  HLG = 3,
  HDR10_PLUS = 4,
  DOLBY_VISION_4K30 = 5,
};

}  // namespace common
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace common {
[[nodiscard]] static inline std::string toString(Hdr val) {
  switch(val) {
  case Hdr::INVALID:
    return "INVALID";
  case Hdr::DOLBY_VISION:
    return "DOLBY_VISION";
  case Hdr::HDR10:
    return "HDR10";
  case Hdr::HLG:
    return "HLG";
  case Hdr::HDR10_PLUS:
    return "HDR10_PLUS";
  case Hdr::DOLBY_VISION_4K30:
    return "DOLBY_VISION_4K30";
  default:
    return std::to_string(static_cast<int32_t>(val));
  }
}
}  // namespace common
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
namespace ndk {
namespace internal {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc++17-extensions"
template <>
constexpr inline std::array<aidl::android::hardware::graphics::common::Hdr, 6> enum_values<aidl::android::hardware::graphics::common::Hdr> = {
  aidl::android::hardware::graphics::common::Hdr::INVALID,
  aidl::android::hardware::graphics::common::Hdr::DOLBY_VISION,
  aidl::android::hardware::graphics::common::Hdr::HDR10,
  aidl::android::hardware::graphics::common::Hdr::HLG,
  aidl::android::hardware::graphics::common::Hdr::HDR10_PLUS,
  aidl::android::hardware::graphics::common::Hdr::DOLBY_VISION_4K30,
};
#pragma clang diagnostic pop
}  // namespace internal
}  // namespace ndk
