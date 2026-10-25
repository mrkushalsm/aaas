/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: /run/media/mrkus/Homework/aaas-workspace/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/composer/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/common/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/common/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/drm/common/aidl -h /home/mrkus/Work/personal/projects/aaas/experiments/m1b/composer_aaas/aidl_gen -o /home/mrkus/Work/personal/projects/aaas/experiments/m1b/composer_aaas/aidl_gen /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/composer/aidl/android/hardware/graphics/composer3/ReleaseFences.aidl
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
#include <aidl/android/hardware/graphics/composer3/ReleaseFences.h>
#ifdef BINDER_STABILITY_SUPPORT
#include <android/binder_stability.h>
#endif  // BINDER_STABILITY_SUPPORT

namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace composer3 {
class ReleaseFences {
public:
  typedef std::false_type fixed_size;
  static const char* descriptor;

  class Layer {
  public:
    typedef std::false_type fixed_size;
    static const char* descriptor;

    int64_t layer = 0L;
    ::ndk::ScopedFileDescriptor fence;

    binder_status_t readFromParcel(const AParcel* parcel);
    binder_status_t writeToParcel(AParcel* parcel) const;

    inline bool operator==(const Layer& _rhs) const {
      return std::tie(layer, fence) == std::tie(_rhs.layer, _rhs.fence);
    }
    inline bool operator<(const Layer& _rhs) const {
      return std::tie(layer, fence) < std::tie(_rhs.layer, _rhs.fence);
    }
    inline bool operator!=(const Layer& _rhs) const {
      return !(*this == _rhs);
    }
    inline bool operator>(const Layer& _rhs) const {
      return _rhs < *this;
    }
    inline bool operator>=(const Layer& _rhs) const {
      return !(*this < _rhs);
    }
    inline bool operator<=(const Layer& _rhs) const {
      return !(_rhs < *this);
    }

    static const ::ndk::parcelable_stability_t _aidl_stability = ::ndk::STABILITY_VINTF;
    inline std::string toString() const {
      std::ostringstream _aidl_os;
      _aidl_os << "Layer{";
      _aidl_os << "layer: " << ::android::internal::ToString(layer);
      _aidl_os << ", fence: " << ::android::internal::ToString(fence);
      _aidl_os << "}";
      return _aidl_os.str();
    }
  };
  int64_t display = 0L;
  std::vector<::aidl::android::hardware::graphics::composer3::ReleaseFences::Layer> layers;

  binder_status_t readFromParcel(const AParcel* parcel);
  binder_status_t writeToParcel(AParcel* parcel) const;

  inline bool operator==(const ReleaseFences& _rhs) const {
    return std::tie(display, layers) == std::tie(_rhs.display, _rhs.layers);
  }
  inline bool operator<(const ReleaseFences& _rhs) const {
    return std::tie(display, layers) < std::tie(_rhs.display, _rhs.layers);
  }
  inline bool operator!=(const ReleaseFences& _rhs) const {
    return !(*this == _rhs);
  }
  inline bool operator>(const ReleaseFences& _rhs) const {
    return _rhs < *this;
  }
  inline bool operator>=(const ReleaseFences& _rhs) const {
    return !(*this < _rhs);
  }
  inline bool operator<=(const ReleaseFences& _rhs) const {
    return !(_rhs < *this);
  }

  static const ::ndk::parcelable_stability_t _aidl_stability = ::ndk::STABILITY_VINTF;
  inline std::string toString() const {
    std::ostringstream _aidl_os;
    _aidl_os << "ReleaseFences{";
    _aidl_os << "display: " << ::android::internal::ToString(display);
    _aidl_os << ", layers: " << ::android::internal::ToString(layers);
    _aidl_os << "}";
    return _aidl_os.str();
  }
};
}  // namespace composer3
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
