/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: $AAAS_WORKSPACE/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/allocator/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/common/aidl -h experiments/m1b/allocator_aaas/include -o experiments/m1b/allocator_aaas/include $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/allocator/aidl/android/hardware/graphics/allocator/AllocationResult.aidl
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
#include <aidl/android/hardware/common/NativeHandle.h>
#ifdef BINDER_STABILITY_SUPPORT
#include <android/binder_stability.h>
#endif  // BINDER_STABILITY_SUPPORT

namespace aidl::android::hardware::common {
class NativeHandle;
}  // namespace aidl::android::hardware::common
namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace allocator {
class AllocationResult {
public:
  typedef std::false_type fixed_size;
  static const char* descriptor;

  int32_t stride = 0;
  std::vector<::aidl::android::hardware::common::NativeHandle> buffers;

  binder_status_t readFromParcel(const AParcel* parcel);
  binder_status_t writeToParcel(AParcel* parcel) const;

  inline bool operator==(const AllocationResult& _rhs) const {
    return std::tie(stride, buffers) == std::tie(_rhs.stride, _rhs.buffers);
  }
  inline bool operator<(const AllocationResult& _rhs) const {
    return std::tie(stride, buffers) < std::tie(_rhs.stride, _rhs.buffers);
  }
  inline bool operator!=(const AllocationResult& _rhs) const {
    return !(*this == _rhs);
  }
  inline bool operator>(const AllocationResult& _rhs) const {
    return _rhs < *this;
  }
  inline bool operator>=(const AllocationResult& _rhs) const {
    return !(*this < _rhs);
  }
  inline bool operator<=(const AllocationResult& _rhs) const {
    return !(_rhs < *this);
  }

  static const ::ndk::parcelable_stability_t _aidl_stability = ::ndk::STABILITY_VINTF;
  inline std::string toString() const {
    std::ostringstream _aidl_os;
    _aidl_os << "AllocationResult{";
    _aidl_os << "stride: " << ::android::internal::ToString(stride);
    _aidl_os << ", buffers: " << ::android::internal::ToString(buffers);
    _aidl_os << "}";
    return _aidl_os.str();
  }
};
}  // namespace allocator
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
