/*
 * This file is auto-generated.  DO NOT MODIFY.
 * Using: $AAAS_WORKSPACE/sources/prebuilts-build-tools-qpr2/linux-x86/bin/aidl --lang=ndk --stability=vintf --structured -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/common/aidl -I $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/drm/common/aidl -h $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen -o $AAAS_REPOSITORY/experiments/m1b/composer_aaas/aidl_gen $AAAS_WORKSPACE/sources/hardware-interfaces-qpr2/graphics/composer/aidl/android/hardware/graphics/composer3/IComposerCallback.aidl
 *
 * DO NOT CHECK THIS FILE INTO A CODE TREE (e.g. git, etc..).
 * ALWAYS GENERATE THIS FILE FROM UPDATED AIDL COMPILER
 * AS A BUILD INTERMEDIATE ONLY. THIS IS NOT SOURCE CODE.
 */
#pragma once

#include "aidl/android/hardware/graphics/composer3/IComposerCallback.h"

#include <android/binder_ibinder.h>

namespace aidl {
namespace android {
namespace hardware {
namespace graphics {
namespace composer3 {
class BpComposerCallback : public ::ndk::BpCInterface<IComposerCallback> {
public:
  explicit BpComposerCallback(const ::ndk::SpAIBinder& binder);
  virtual ~BpComposerCallback();

  ::ndk::ScopedAStatus onHotplug(int64_t in_display, bool in_connected) override __attribute__((deprecated(": Use instead onHotplugEvent")));
  ::ndk::ScopedAStatus onRefresh(int64_t in_display) override;
  ::ndk::ScopedAStatus onSeamlessPossible(int64_t in_display) override;
  ::ndk::ScopedAStatus onVsync(int64_t in_display, int64_t in_timestamp, int32_t in_vsyncPeriodNanos) override;
  ::ndk::ScopedAStatus onVsyncPeriodTimingChanged(int64_t in_display, const ::aidl::android::hardware::graphics::composer3::VsyncPeriodChangeTimeline& in_updatedTimeline) override;
  ::ndk::ScopedAStatus onVsyncIdle(int64_t in_display) override;
  ::ndk::ScopedAStatus onRefreshRateChangedDebug(const ::aidl::android::hardware::graphics::composer3::RefreshRateChangedDebugData& in_data) override;
  ::ndk::ScopedAStatus onHotplugEvent(int64_t in_display, ::aidl::android::hardware::graphics::common::DisplayHotplugEvent in_event) override;
  ::ndk::ScopedAStatus onHdcpLevelsChanged(int64_t in_display, const ::aidl::android::hardware::drm::HdcpLevels& in_levels) override;
};
}  // namespace composer3
}  // namespace graphics
}  // namespace hardware
}  // namespace android
}  // namespace aidl
