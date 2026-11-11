/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: $AAAS_WORKSPACE/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/drm/common/aidl -h $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen -o $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl/android/hardware/graphics/common/HdrConversionCapability.aidl
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
#include <aidl/android/hardware/graphics/common/Hdr.h>
#ifdef BINDER_STABILITY_SUPPORT
#include <android/binder_stability.h>
#endif  // BINDER_STABILITY_SUPPORT

namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace common {
class HdrConversionCapability {
public:
  typedef std::false_type fixed_size;
  static const char* descriptor;

  ::aidl::android::hardware::graphics::common::Hdr sourceType = ::aidl::android::hardware::graphics::common::Hdr(0);
  ::aidl::android::hardware::graphics::common::Hdr outputType = ::aidl::android::hardware::graphics::common::Hdr(0);
  bool addsLatency = false;

  binder_status_t readFromParcel(const AParcel* parcel);
  binder_status_t writeToParcel(AParcel* parcel) const;

  inline bool operator==(const HdrConversionCapability& _rhs) const {
    return std::tie(sourceType, outputType, addsLatency) == std::tie(_rhs.sourceType, _rhs.outputType, _rhs.addsLatency);
  }
  inline bool operator<(const HdrConversionCapability& _rhs) const {
    return std::tie(sourceType, outputType, addsLatency) < std::tie(_rhs.sourceType, _rhs.outputType, _rhs.addsLatency);
  }
  inline bool operator!=(const HdrConversionCapability& _rhs) const {
    return !(*this == _rhs);
  }
  inline bool operator>(const HdrConversionCapability& _rhs) const {
    return _rhs < *this;
  }
  inline bool operator>=(const HdrConversionCapability& _rhs) const {
    return !(*this < _rhs);
  }
  inline bool operator<=(const HdrConversionCapability& _rhs) const {
    return !(_rhs < *this);
  }

  static const ::ndk::parcelable_stability_t _aidl_stability = ::ndk::STABILITY_VINTF;
  inline std::string toString() const {
    std::ostringstream _aidl_os;
    _aidl_os << "HdrConversionCapability{";
    _aidl_os << "sourceType: " << ::android::internal::ToString(sourceType);
    _aidl_os << ", outputType: " << ::android::internal::ToString(outputType);
    _aidl_os << ", addsLatency: " << ::android::internal::ToString(addsLatency);
    _aidl_os << "}";
    return _aidl_os.str();
  }
};
}  // namespace common
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
