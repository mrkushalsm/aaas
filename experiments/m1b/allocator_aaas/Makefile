CXX := clang++
TARGET ?= x86_64-linux-android
WORKSPACE_ROOT ?= /run/media/mrkus/Aaas/aaas-workspace
ROOTFS ?= $(WORKSPACE_ROOT)/rootfs_m1b1
TOOLCHAIN_LIBCXX ?= $(WORKSPACE_ROOT)/toolchain/libc++
OUT_DIR ?= $(WORKSPACE_ROOT)/tmp
BIN ?= $(OUT_DIR)/android.hardware.graphics.allocator-service.aaas

CXXFLAGS := -target $(TARGET) -std=c++17 -nostdlib -nostdinc++ -fno-rtti \
  -D__BIONIC__ '-D__INTRODUCED_IN(n)=' -D__ANDROID_API__=35 \
  -I $(TOOLCHAIN_LIBCXX)/usr/include/c++/v1 \
  -I include \
  -I include/aidl \
  -I ../composer_aaas/include \
  -I ../composer_aaas/include/aidl

LDFLAGS := -L $(ROOTFS)/system/lib64 \
  -L $(ROOTFS)/system/lib64/bootstrap \
  -lc -lc++ -lbinder_ndk \
  -l:android.hardware.graphics.allocator-V2-ndk.so \
  -l:android.hardware.graphics.common-V6-ndk.so \
  -l:android.hardware.common-V2-ndk.so \
  -Wl,-dynamic-linker,/system/bin/linker64

all: $(BIN)

$(BIN): allocator_service.cpp
	@mkdir -p $(OUT_DIR)
	$(CXX) $(CXXFLAGS) $< $(LDFLAGS) -o $@

clean:
	rm -f $(BIN)

.PHONY: all clean
