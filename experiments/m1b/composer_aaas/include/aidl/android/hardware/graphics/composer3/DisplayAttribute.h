/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: $AAAS_WORKSPACE/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/drm/common/aidl -h $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen -o $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl/android/hardware/graphics/composer3/DisplayAttribute.aidl
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
enum class DisplayAttribute : int32_t {
  INVALID = 0,
  WIDTH = 1,
  HEIGHT = 2,
  VSYNC_PERIOD = 3,
  DPI_X = 4,
  DPI_Y = 5,
  CONFIG_GROUP = 7,
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
[[nodiscard]] static inline std::string toString(DisplayAttribute val) {
  switch(val) {
  case DisplayAttribute::INVALID:
    return "INVALID";
  case DisplayAttribute::WIDTH:
    return "WIDTH";
  case DisplayAttribute::HEIGHT:
    return "HEIGHT";
  case DisplayAttribute::VSYNC_PERIOD:
    return "VSYNC_PERIOD";
  case DisplayAttribute::DPI_X:
    return "DPI_X";
  case DisplayAttribute::DPI_Y:
    return "DPI_Y";
  case DisplayAttribute::CONFIG_GROUP:
    return "CONFIG_GROUP";
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
constexpr inline std::array<aidl::android::hardware::graphics::composer3::DisplayAttribute, 7> enum_values<aidl::android::hardware::graphics::composer3::DisplayAttribute> = {
  aidl::android::hardware::graphics::composer3::DisplayAttribute::INVALID,
  aidl::android::hardware::graphics::composer3::DisplayAttribute::WIDTH,
  aidl::android::hardware::graphics::composer3::DisplayAttribute::HEIGHT,
  aidl::android::hardware::graphics::composer3::DisplayAttribute::VSYNC_PERIOD,
  aidl::android::hardware::graphics::composer3::DisplayAttribute::DPI_X,
  aidl::android::hardware::graphics::composer3::DisplayAttribute::DPI_Y,
  aidl::android::hardware::graphics::composer3::DisplayAttribute::CONFIG_GROUP,
};
#pragma clang diagnostic pop
}  // namespace internal
}  // namespace ndk
