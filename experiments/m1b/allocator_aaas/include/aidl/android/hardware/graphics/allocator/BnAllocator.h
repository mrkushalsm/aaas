/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: /run/media/mrkus/Homework/aaas-workspace/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/allocator/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/common/aidl -I /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/common/aidl -h experiments/m1b/allocator_aaas/include -o experiments/m1b/allocator_aaas/include /run/media/mrkus/Homework/aaas-workspace/sources/hardware-interfaces-qpr2/graphics/allocator/aidl/android/hardware/graphics/allocator/IAllocator.aidl
 *
 * DO NOT CHECK THIS FILE INTO A CODE TREE (e.g. git, etc..).
 * ALWAYS GENERATE THIS FILE FROM UPDATED AIDL COMPILER
 * AS A BUILD INTERMEDIATE ONLY. THIS IS NOT SOURCE CODE.
 */
#pragma once

#include "aidl/android/hardware/graphics/allocator/IAllocator.h"

#include <android/binder_ibinder.h>
#include <cassert>

#ifndef __BIONIC__
#ifndef __assert2
#define __assert2(a,b,c,d) ((void)0)
#endif
#endif

namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace allocator {
class BnAllocator : public ::ndk::BnCInterface<IAllocator> {
public:
  BnAllocator();
  virtual ~BnAllocator();
protected:
  ::ndk::SpAIBinder createBinder() override;
private:
};
class IAllocatorDelegator : public BnAllocator {
public:
  explicit IAllocatorDelegator(const std::shared_ptr<IAllocator> &impl) : _impl(impl) {
  }

  ::ndk::ScopedAStatus allocate(const std::vector<uint8_t>& in_descriptor, int32_t in_count, ::aidl::android::hardware::graphics::allocator::AllocationResult* _aidl_return) override __attribute__((deprecated("As of android.hardware.graphics.allocator-V2 in combination with AIMAPPER_VERSION_5 this is deprecated & replaced with allocate2. If android.hardware.graphics.mapper@4 is still in use, however, this is still required to be implemented."))) {
    return _impl->allocate(in_descriptor, in_count, _aidl_return);
  }
  ::ndk::ScopedAStatus allocate2(const ::aidl::android::hardware::graphics::allocator::BufferDescriptorInfo& in_descriptor, int32_t in_count, ::aidl::android::hardware::graphics::allocator::AllocationResult* _aidl_return) override {
    return _impl->allocate2(in_descriptor, in_count, _aidl_return);
  }
  ::ndk::ScopedAStatus isSupported(const ::aidl::android::hardware::graphics::allocator::BufferDescriptorInfo& in_descriptor, bool* _aidl_return) override {
    return _impl->isSupported(in_descriptor, _aidl_return);
  }
  ::ndk::ScopedAStatus getIMapperLibrarySuffix(std::string* _aidl_return) override {
    return _impl->getIMapperLibrarySuffix(_aidl_return);
  }
protected:
private:
  std::shared_ptr<IAllocator> _impl;
};

}  // namespace allocator
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
