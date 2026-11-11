/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: $AAAS_WORKSPACE/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/drm/common/aidl -h $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen -o $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl/android/hardware/graphics/composer3/Composition.aidl
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
namespace composer3 {
enum class Composition : int32_t {
  INVALID = 0,
  CLIENT = 1,
  DEVICE = 2,
  SOLID_COLOR = 3,
  CURSOR = 4,
  SIDEBAND = 5,
  DISPLAY_DECORATION = 6,
  REFRESH_RATE_INDICATOR = 7,
};

}  // namespace composer3
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace composer3 {
[[nodiscard]] static inline std::string toString(Composition val) {
  switch(val) {
  case Composition::INVALID:
    return "INVALID";
  case Composition::CLIENT:
    return "CLIENT";
  case Composition::DEVICE:
    return "DEVICE";
  case Composition::SOLID_COLOR:
    return "SOLID_COLOR";
  case Composition::CURSOR:
    return "CURSOR";
  case Composition::SIDEBAND:
    return "SIDEBAND";
  case Composition::DISPLAY_DECORATION:
    return "DISPLAY_DECORATION";
  case Composition::REFRESH_RATE_INDICATOR:
    return "REFRESH_RATE_INDICATOR";
  default:
    return std::to_string(static_cast<int32_t>(val));
  }
}
}  // namespace composer3
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
namespace ndk {
namespace internal {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc++17-extensions"
template <>
constexpr inline std::array<aidl::android::hardware::graphics::composer3::Composition, 8> enum_values<aidl::android::hardware::graphics::composer3::Composition> = {
  aidl::android::hardware::graphics::composer3::Composition::INVALID,
  aidl::android::hardware::graphics::composer3::Composition::CLIENT,
  aidl::android::hardware::graphics::composer3::Composition::DEVICE,
  aidl::android::hardware::graphics::composer3::Composition::SOLID_COLOR,
  aidl::android::hardware::graphics::composer3::Composition::CURSOR,
  aidl::android::hardware::graphics::composer3::Composition::SIDEBAND,
  aidl::android::hardware::graphics::composer3::Composition::DISPLAY_DECORATION,
  aidl::android::hardware::graphics::composer3::Composition::REFRESH_RATE_INDICATOR,
};
#pragma clang diagnostic pop
}  // namespace internal
}  // namespace ndk
