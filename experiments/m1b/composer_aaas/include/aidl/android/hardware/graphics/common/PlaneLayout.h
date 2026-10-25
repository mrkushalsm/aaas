/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: /run/media/mrkus/Homework/aaas-workspace/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/composer/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/common/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/common/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/drm/common/aidl -h /home/mrkus/Work/personal/projects/aaas/experiments/m1b/composer_aaas/aidl_gen -o /home/mrkus/Work/personal/projects/aaas/experiments/m1b/composer_aaas/aidl_gen /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/common/aidl/android/hardware/graphics/common/PlaneLayout.aidl
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
#include <aidl/android/hardware/graphics/common/PlaneLayoutComponent.h>
#ifdef BINDER_STABILITY_SUPPORT
#include <android/binder_stability.h>
#endif  // BINDER_STABILITY_SUPPORT

namespace aidl::android::hardware::graphics::common {
class PlaneLayoutComponent;
}  // namespace aidl::android::hardware::graphics::common
namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace common {
class PlaneLayout {
public:
  typedef std::false_type fixed_size;
  static const char* descriptor;

  std::vector<::aidl::android::hardware::graphics::common::PlaneLayoutComponent> components;
  int64_t offsetInBytes = 0L;
  int64_t sampleIncrementInBits = 0L;
  int64_t strideInBytes = 0L;
  int64_t widthInSamples = 0L;
  int64_t heightInSamples = 0L;
  int64_t totalSizeInBytes = 0L;
  int64_t horizontalSubsampling = 0L;
  int64_t verticalSubsampling = 0L;

  binder_status_t readFromParcel(const AParcel* parcel);
  binder_status_t writeToParcel(AParcel* parcel) const;

  inline bool operator==(const PlaneLayout& _rhs) const {
    return std::tie(components, offsetInBytes, sampleIncrementInBits, strideInBytes, widthInSamples, heightInSamples, totalSizeInBytes, horizontalSubsampling, verticalSubsampling) == std::tie(_rhs.components, _rhs.offsetInBytes, _rhs.sampleIncrementInBits, _rhs.strideInBytes, _rhs.widthInSamples, _rhs.heightInSamples, _rhs.totalSizeInBytes, _rhs.horizontalSubsampling, _rhs.verticalSubsampling);
  }
  inline bool operator<(const PlaneLayout& _rhs) const {
    return std::tie(components, offsetInBytes, sampleIncrementInBits, strideInBytes, widthInSamples, heightInSamples, totalSizeInBytes, horizontalSubsampling, verticalSubsampling) < std::tie(_rhs.components, _rhs.offsetInBytes, _rhs.sampleIncrementInBits, _rhs.strideInBytes, _rhs.widthInSamples, _rhs.heightInSamples, _rhs.totalSizeInBytes, _rhs.horizontalSubsampling, _rhs.verticalSubsampling);
  }
  inline bool operator!=(const PlaneLayout& _rhs) const {
    return !(*this == _rhs);
  }
  inline bool operator>(const PlaneLayout& _rhs) const {
    return _rhs < *this;
  }
  inline bool operator>=(const PlaneLayout& _rhs) const {
    return !(*this < _rhs);
  }
  inline bool operator<=(const PlaneLayout& _rhs) const {
    return !(_rhs < *this);
  }

  static const ::ndk::parcelable_stability_t _aidl_stability = ::ndk::STABILITY_VINTF;
  inline std::string toString() const {
    std::ostringstream _aidl_os;
    _aidl_os << "PlaneLayout{";
    _aidl_os << "components: " << ::android::internal::ToString(components);
    _aidl_os << ", offsetInBytes: " << ::android::internal::ToString(offsetInBytes);
    _aidl_os << ", sampleIncrementInBits: " << ::android::internal::ToString(sampleIncrementInBits);
    _aidl_os << ", strideInBytes: " << ::android::internal::ToString(strideInBytes);
    _aidl_os << ", widthInSamples: " << ::android::internal::ToString(widthInSamples);
    _aidl_os << ", heightInSamples: " << ::android::internal::ToString(heightInSamples);
    _aidl_os << ", totalSizeInBytes: " << ::android::internal::ToString(totalSizeInBytes);
    _aidl_os << ", horizontalSubsampling: " << ::android::internal::ToString(horizontalSubsampling);
    _aidl_os << ", verticalSubsampling: " << ::android::internal::ToString(verticalSubsampling);
    _aidl_os << "}";
    return _aidl_os.str();
  }
};
}  // namespace common
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
