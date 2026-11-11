/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: $AAAS_WORKSPACE/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/drm/common/aidl -h $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen -o $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl/android/hardware/graphics/common/BlendMode.aidl
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
enum class BlendMode : int32_t {
  INVALID = 0,
  NONE = 1,
  PREMULTIPLIED = 2,
  COVERAGE = 3,
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
[[nodiscard]] static inline std::string toString(BlendMode val) {
  switch(val) {
  case BlendMode::INVALID:
    return "INVALID";
  case BlendMode::NONE:
    return "NONE";
  case BlendMode::PREMULTIPLIED:
    return "PREMULTIPLIED";
  case BlendMode::COVERAGE:
    return "COVERAGE";
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
constexpr inline std::array<aidl::android::hardware::graphics::common::BlendMode, 4> enum_values<aidl::android::hardware::graphics::common::BlendMode> = {
  aidl::android::hardware::graphics::common::BlendMode::INVALID,
  aidl::android::hardware::graphics::common::BlendMode::NONE,
  aidl::android::hardware::graphics::common::BlendMode::PREMULTIPLIED,
  aidl::android::hardware::graphics::common::BlendMode::COVERAGE,
};
#pragma clang diagnostic pop
}  // namespace internal
}  // namespace ndk
