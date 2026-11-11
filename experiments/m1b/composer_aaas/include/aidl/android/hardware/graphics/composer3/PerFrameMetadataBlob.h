/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: $AAAS_WORKSPACE/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/drm/common/aidl -h $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen -o $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl/android/hardware/graphics/composer3/PerFrameMetadataBlob.aidl
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
#include <aidl/android/hardware/graphics/composer3/PerFrameMetadataKey.h>
#ifdef BINDER_STABILITY_SUPPORT
#include <android/binder_stability.h>
#endif  // BINDER_STABILITY_SUPPORT

namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace composer3 {
class PerFrameMetadataBlob {
public:
  typedef std::false_type fixed_size;
  static const char* descriptor;

  ::aidl::android::hardware::graphics::composer3::PerFrameMetadataKey key = ::aidl::android::hardware::graphics::composer3::PerFrameMetadataKey(0);
  std::vector<uint8_t> blob;

  binder_status_t readFromParcel(const AParcel* parcel);
  binder_status_t writeToParcel(AParcel* parcel) const;

  inline bool operator==(const PerFrameMetadataBlob& _rhs) const {
    return std::tie(key, blob) == std::tie(_rhs.key, _rhs.blob);
  }
  inline bool operator<(const PerFrameMetadataBlob& _rhs) const {
    return std::tie(key, blob) < std::tie(_rhs.key, _rhs.blob);
  }
  inline bool operator!=(const PerFrameMetadataBlob& _rhs) const {
    return !(*this == _rhs);
  }
  inline bool operator>(const PerFrameMetadataBlob& _rhs) const {
    return _rhs < *this;
  }
  inline bool operator>=(const PerFrameMetadataBlob& _rhs) const {
    return !(*this < _rhs);
  }
  inline bool operator<=(const PerFrameMetadataBlob& _rhs) const {
    return !(_rhs < *this);
  }

  static const ::ndk::parcelable_stability_t _aidl_stability = ::ndk::STABILITY_VINTF;
  inline std::string toString() const {
    std::ostringstream _aidl_os;
    _aidl_os << "PerFrameMetadataBlob{";
    _aidl_os << "key: " << ::android::internal::ToString(key);
    _aidl_os << ", blob: " << ::android::internal::ToString(blob);
    _aidl_os << "}";
    return _aidl_os.str();
  }
};
}  // namespace composer3
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
