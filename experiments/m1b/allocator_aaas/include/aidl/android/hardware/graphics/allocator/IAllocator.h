/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: /run/media/mrkus/Homework/aaas-workspace/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/allocator/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/common/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/common/aidl -h experiments/m1b/allocator_aaas/include -o experiments/m1b/allocator_aaas/include /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/allocator/aidl/android/hardware/graphics/allocator/IAllocator.aidl
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
#include <aidl/android/hardware/graphics/allocator/AllocationResult.h>
#include <aidl/android/hardware/graphics/allocator/BufferDescriptorInfo.h>
#ifdef BINDER_STABILITY_SUPPORT
#include <android/binder_stability.h>
#endif  // BINDER_STABILITY_SUPPORT

namespace aidl::android::hardware::graphics::allocator {
class AllocationResult;
class BufferDescriptorInfo;
}  // namespace aidl::android::hardware::graphics::allocator
namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace allocator {
class IAllocatorDelegator;

class IAllocator : public ::ndk::ICInterface {
public:
  typedef IAllocatorDelegator DefaultDelegator;
  static const char* descriptor;
  IAllocator();
  virtual ~IAllocator();

  static constexpr uint32_t TRANSACTION_allocate = FIRST_CALL_TRANSACTION + 0;
  static constexpr uint32_t TRANSACTION_allocate2 = FIRST_CALL_TRANSACTION + 1;
  static constexpr uint32_t TRANSACTION_isSupported = FIRST_CALL_TRANSACTION + 2;
  static constexpr uint32_t TRANSACTION_getIMapperLibrarySuffix = FIRST_CALL_TRANSACTION + 3;

  static std::shared_ptr<IAllocator> fromBinder(const ::ndk::SpAIBinder& binder);
  static binder_status_t writeToParcel(AParcel* parcel, const std::shared_ptr<IAllocator>& instance);
  static binder_status_t readFromParcel(const AParcel* parcel, std::shared_ptr<IAllocator>* instance);
  static bool setDefaultImpl(const std::shared_ptr<IAllocator>& impl);
  static const std::shared_ptr<IAllocator>& getDefaultImpl();
  virtual ::ndk::ScopedAStatus allocate(const std::vector<uint8_t>& in_descriptor, int32_t in_count, ::aidl::android::hardware::graphics::allocator::AllocationResult* _aidl_return) __attribute__((deprecated("As of android.hardware.graphics.allocator-V2 in combination with AIMAPPER_VERSION_5 this is deprecated & replaced with allocate2. If android.hardware.graphics.mapper@4 is still in use, however, this is still required to be implemented."))) = 0;
  virtual ::ndk::ScopedAStatus allocate2(const ::aidl::android::hardware::graphics::allocator::BufferDescriptorInfo& in_descriptor, int32_t in_count, ::aidl::android::hardware::graphics::allocator::AllocationResult* _aidl_return) = 0;
  virtual ::ndk::ScopedAStatus isSupported(const ::aidl::android::hardware::graphics::allocator::BufferDescriptorInfo& in_descriptor, bool* _aidl_return) = 0;
  virtual ::ndk::ScopedAStatus getIMapperLibrarySuffix(std::string* _aidl_return) = 0;
private:
  static std::shared_ptr<IAllocator> default_impl;
};
class IAllocatorDefault : public IAllocator {
public:
  ::ndk::ScopedAStatus allocate(const std::vector<uint8_t>& in_descriptor, int32_t in_count, ::aidl::android::hardware::graphics::allocator::AllocationResult* _aidl_return) override __attribute__((deprecated("As of android.hardware.graphics.allocator-V2 in combination with AIMAPPER_VERSION_5 this is deprecated & replaced with allocate2. If android.hardware.graphics.mapper@4 is still in use, however, this is still required to be implemented.")));
  ::ndk::ScopedAStatus allocate2(const ::aidl::android::hardware::graphics::allocator::BufferDescriptorInfo& in_descriptor, int32_t in_count, ::aidl::android::hardware::graphics::allocator::AllocationResult* _aidl_return) override;
  ::ndk::ScopedAStatus isSupported(const ::aidl::android::hardware::graphics::allocator::BufferDescriptorInfo& in_descriptor, bool* _aidl_return) override;
  ::ndk::ScopedAStatus getIMapperLibrarySuffix(std::string* _aidl_return) override;
  ::ndk::SpAIBinder asBinder() override;
  bool isRemote() override;
};
}  // namespace allocator
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
