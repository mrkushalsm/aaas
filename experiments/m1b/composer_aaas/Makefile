CXX := clang++
TARGET ?= x86_64-linux-android
WORKSPACE_ROOT ?= /run/media/mrkus/Homework/aaas-workspace
ROOTFS ?= $(WORKSPACE_ROOT)/rootfs_m1b1
TOOLCHAIN_LIBCXX ?= $(WORKSPACE_ROOT)/toolchain/libc++
OUT_DIR ?= $(WORKSPACE_ROOT)/tmp
BIN ?= $(OUT_DIR)/android.hardware.graphics.composer3-service.aaas
AAAS_DISPLAY_WIDTH ?= 1280
AAAS_DISPLAY_HEIGHT ?= 720

SRCS := composer_service.cpp aaas_transport.cpp ../../m1a/src/wire_v2.c

CXXFLAGS := -target $(TARGET) -std=c++17 -nostdlib -nostdinc++ -fno-rtti \
  -D__BIONIC__ '-D__INTRODUCED_IN(n)=' -D__ANDROID_API__=35 \
  -DAAAS_DISPLAY_WIDTH=$(AAAS_DISPLAY_WIDTH) \
  -DAAAS_DISPLAY_HEIGHT=$(AAAS_DISPLAY_HEIGHT) \
  -I $(TOOLCHAIN_LIBCXX)/usr/include/c++/v1 \
  -I include \
  -I include/aidl \
  -I ../../m1a/src

LDFLAGS := -L $(ROOTFS)/system/lib64 \
  -L $(ROOTFS)/system/lib64/bootstrap \
  -lc -lc++ -lbinder_ndk \
  -l:android.hardware.graphics.composer3-V4-ndk.so \
  -l:android.hardware.graphics.common-V6-ndk.so \
  -l:android.hardware.common-V2-ndk.so \
  -l:android.hardware.drm.common-V1-ndk.so \
  -Wl,-dynamic-linker,/system/bin/linker64

all: $(BIN)

$(BIN): $(SRCS)
	@mkdir -p $(OUT_DIR)
	$(CXX) $(CXXFLAGS) $(SRCS) $(LDFLAGS) -o $@

clean:
	rm -f $(BIN)

.PHONY: all clean
