/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: $AAAS_WORKSPACE/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/drm/common/aidl -h $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen -o $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl/android/hardware/graphics/composer3/IComposer.aidl
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
#include <aidl/android/hardware/graphics/composer3/Capability.h>
#include <aidl/android/hardware/graphics/composer3/IComposerClient.h>
#ifdef BINDER_STABILITY_SUPPORT
#include <android/binder_stability.h>
#endif  // BINDER_STABILITY_SUPPORT

namespace aidl::android::hardware::graphics::composer3 {
class IComposerClient;
}  // namespace aidl::android::hardware::graphics::composer3
namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace composer3 {
class IComposerDelegator;

class IComposer : public ::ndk::ICInterface {
public:
  typedef IComposerDelegator DefaultDelegator;
  static const char* descriptor;
  IComposer();
  virtual ~IComposer();

  enum : int32_t { EX_NO_RESOURCES = 6 };
  static constexpr uint32_t TRANSACTION_createClient = FIRST_CALL_TRANSACTION + 0;
  static constexpr uint32_t TRANSACTION_getCapabilities = FIRST_CALL_TRANSACTION + 1;

  static std::shared_ptr<IComposer> fromBinder(const ::ndk::SpAIBinder& binder);
  static binder_status_t writeToParcel(AParcel* parcel, const std::shared_ptr<IComposer>& instance);
  static binder_status_t readFromParcel(const AParcel* parcel, std::shared_ptr<IComposer>* instance);
  static bool setDefaultImpl(const std::shared_ptr<IComposer>& impl);
  static const std::shared_ptr<IComposer>& getDefaultImpl();
  virtual ::ndk::ScopedAStatus createClient(std::shared_ptr<::aidl::android::hardware::graphics::composer3::IComposerClient>* _aidl_return) = 0;
  virtual ::ndk::ScopedAStatus getCapabilities(std::vector<::aidl::android::hardware::graphics::composer3::Capability>* _aidl_return) = 0;
private:
  static std::shared_ptr<IComposer> default_impl;
};
class IComposerDefault : public IComposer {
public:
  ::ndk::ScopedAStatus createClient(std::shared_ptr<::aidl::android::hardware::graphics::composer3::IComposerClient>* _aidl_return) override;
  ::ndk::ScopedAStatus getCapabilities(std::vector<::aidl::android::hardware::graphics::composer3::Capability>* _aidl_return) override;
  ::ndk::SpAIBinder asBinder() override;
  bool isRemote() override;
};
}  // namespace composer3
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
