/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: $AAAS_WORKSPACE/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/drm/common/aidl -h $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen -o $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl/android/hardware/graphics/composer3/ContentType.aidl
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
enum class ContentType : int32_t {
  NONE = 0,
  GRAPHICS = 1,
  PHOTO = 2,
  CINEMA = 3,
  GAME = 4,
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
[[nodiscard]] static inline std::string toString(ContentType val) {
  switch(val) {
  case ContentType::NONE:
    return "NONE";
  case ContentType::GRAPHICS:
    return "GRAPHICS";
  case ContentType::PHOTO:
    return "PHOTO";
  case ContentType::CINEMA:
    return "CINEMA";
  case ContentType::GAME:
    return "GAME";
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
constexpr inline std::array<aidl::android::hardware::graphics::composer3::ContentType, 5> enum_values<aidl::android::hardware::graphics::composer3::ContentType> = {
  aidl::android::hardware::graphics::composer3::ContentType::NONE,
  aidl::android::hardware::graphics::composer3::ContentType::GRAPHICS,
  aidl::android::hardware::graphics::composer3::ContentType::PHOTO,
  aidl::android::hardware::graphics::composer3::ContentType::CINEMA,
  aidl::android::hardware::graphics::composer3::ContentType::GAME,
};
#pragma clang diagnostic pop
}  // namespace internal
}  // namespace ndk
