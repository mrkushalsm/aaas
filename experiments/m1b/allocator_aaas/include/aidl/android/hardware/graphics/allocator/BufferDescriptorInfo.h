/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: $AAAS_WORKSPACE/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/allocator/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/common/aidl -h experiments/m1b/allocator_aaas/include -o experiments/m1b/allocator_aaas/include $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/allocator/aidl/android/hardware/graphics/allocator/BufferDescriptorInfo.aidl
 *
 * DO NOT CHECK THIS FILE INTO A CODE TREE (e.g. git, etc..).
 * ALWAYS GENERATE THIS FILE FROM UPDATED AIDL COMPILER
 * AS A BUILD INTERMEDIATE ONLY. THIS IS NOT SOURCE CODE.
 */
#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>
#include <android/binder_interface_utils.h>
#include <android/binder_parcelable_utils.h>
#include <android/binder_to_string.h>
#include <aidl/android/hardware/graphics/common/BufferUsage.h>
#include <aidl/android/hardware/graphics/common/ExtendableType.h>
#include <aidl/android/hardware/graphics/common/PixelFormat.h>
#ifdef BINDER_STABILITY_SUPPORT
#include <android/binder_stability.h>
#endif  // BINDER_STABILITY_SUPPORT

namespace aidl::android::hardware::graphics::common {
class ExtendableType;
}  // namespace aidl::android::hardware::graphics::common
namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace allocator {
class BufferDescriptorInfo {
public:
  typedef std::false_type fixed_size;
  static const char* descriptor;

  std::array<uint8_t, 128> name = {{}};
  int32_t width = 0;
  int32_t height = 0;
  int32_t layerCount = 0;
  ::aidl::android::hardware::graphics::common::PixelFormat format = ::aidl::android::hardware::graphics::common::PixelFormat::UNSPECIFIED;
  ::aidl::android::hardware::graphics::common::BufferUsage usage = ::aidl::android::hardware::graphics::common::BufferUsage::CPU_READ_NEVER;
  int64_t reservedSize = 0L;
  std::vector<::aidl::android::hardware::graphics::common::ExtendableType> additionalOptions;

  binder_status_t readFromParcel(const AParcel* parcel);
  binder_status_t writeToParcel(AParcel* parcel) const;

  inline bool operator==(const BufferDescriptorInfo& _rhs) const {
    return std::tie(name, width, height, layerCount, format, usage, reservedSize, additionalOptions) == std::tie(_rhs.name, _rhs.width, _rhs.height, _rhs.layerCount, _rhs.format, _rhs.usage, _rhs.reservedSize, _rhs.additionalOptions);
  }
  inline bool operator<(const BufferDescriptorInfo& _rhs) const {
    return std::tie(name, width, height, layerCount, format, usage, reservedSize, additionalOptions) < std::tie(_rhs.name, _rhs.width, _rhs.height, _rhs.layerCount, _rhs.format, _rhs.usage, _rhs.reservedSize, _rhs.additionalOptions);
  }
  inline bool operator!=(const BufferDescriptorInfo& _rhs) const {
    return !(*this == _rhs);
  }
  inline bool operator>(const BufferDescriptorInfo& _rhs) const {
    return _rhs < *this;
  }
  inline bool operator>=(const BufferDescriptorInfo& _rhs) const {
    return !(*this < _rhs);
  }
  inline bool operator<=(const BufferDescriptorInfo& _rhs) const {
    return !(_rhs < *this);
  }

  static const ::ndk::parcelable_stability_t _aidl_stability = ::ndk::STABILITY_VINTF;
  inline std::string toString() const {
    std::ostringstream _aidl_os;
    _aidl_os << "BufferDescriptorInfo{";
    _aidl_os << "name: " << ::android::internal::ToString(name);
    _aidl_os << ", width: " << ::android::internal::ToString(width);
    _aidl_os << ", height: " << ::android::internal::ToString(height);
    _aidl_os << ", layerCount: " << ::android::internal::ToString(layerCount);
    _aidl_os << ", format: " << ::android::internal::ToString(format);
    _aidl_os << ", usage: " << ::android::internal::ToString(usage);
    _aidl_os << ", reservedSize: " << ::android::internal::ToString(reservedSize);
    _aidl_os << ", additionalOptions: " << ::android::internal::ToString(additionalOptions);
    _aidl_os << "}";
    return _aidl_os.str();
  }
};
}  // namespace allocator
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
