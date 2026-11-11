CLANGXX ?= clang++
CXX := $(CLANGXX)
HOST_CXX ?= c++
HOST_MULTIARCH := $(shell $(HOST_CXX) -print-multiarch 2>/dev/null)
CLANG_MAJOR := $(shell $(CXX) -dumpversion 2>/dev/null | cut -d. -f1)
LLD_PATH := $(shell command -v ld.lld 2>/dev/null || \
	command -v ld.lld-$(CLANG_MAJOR) 2>/dev/null)
TARGET ?= x86_64-linux-android
XDG_DATA_HOME ?= $(HOME)/.local/share
WORKSPACE_ROOT ?= $(XDG_DATA_HOME)/aaas/workspace
ROOTFS ?= $(WORKSPACE_ROOT)/rootfs_m1b1
TOOLCHAIN_LIBCXX ?= $(WORKSPACE_ROOT)/toolchain/libc++
OUT_DIR ?= $(WORKSPACE_ROOT)/tmp
BUILD_DIR ?= build
BIN ?= $(OUT_DIR)/android.hardware.graphics.composer3-service.aaas
AAAS_DISPLAY_WIDTH ?= 1280
AAAS_DISPLAY_HEIGHT ?= 720
AAAS_ENABLE_VIRTUAL_DISPLAY ?= 0
AAAS_VIRTUAL_DISPLAY_MAX_COUNT ?= 64

SRCS := composer_service.cpp aaas_transport.cpp ../../m1a/src/wire_v2.c
HEADERS := aaas_transport.h linear_copy.h mixed_compose.h virtual_transport_pool.h

CXXFLAGS := -target $(TARGET) -std=c++17 -nostdlib -nostdinc++ -fno-rtti \
  -D__BIONIC__ '-D__INTRODUCED_IN(n)=' -D__ANDROID_API__=35 \
  -DAAAS_DISPLAY_WIDTH=$(AAAS_DISPLAY_WIDTH) \
  -DAAAS_DISPLAY_HEIGHT=$(AAAS_DISPLAY_HEIGHT) \
  -I $(TOOLCHAIN_LIBCXX)/usr/include/c++/v1 \
  -I include \
  -I include/aidl \
  -I ../../m1a/src
ifneq ($(strip $(HOST_MULTIARCH)),)
ifneq ($(wildcard /usr/include/$(HOST_MULTIARCH)),)
CXXFLAGS += -isystem /usr/include/$(HOST_MULTIARCH)
endif
endif
CXXFLAGS += -B$(BUILD_DIR)

ifeq ($(AAAS_ENABLE_VIRTUAL_DISPLAY),1)
CXXFLAGS += -DAAAS_ENABLE_VIRTUAL_DISPLAY=1 \
  -DAAAS_VIRTUAL_DISPLAY_MAX_COUNT=$(AAAS_VIRTUAL_DISPLAY_MAX_COUNT) \
  -DAAAS_VIRTUAL_DISPLAY_ENDPOINT_DIR=\"/dev/aaas/virtual-endpoints\"
endif

ifeq ($(AAAS_ENABLE_MIXED_COMPOSITION_TEST),1)
CXXFLAGS += -DAAAS_ENABLE_MIXED_COMPOSITION_TEST=1
endif
ifeq ($(AAAS_ENABLE_MIXED_DIRECT_IMPORT_TEST),1)
CXXFLAGS += -DAAAS_ENABLE_MIXED_DIRECT_IMPORT_TEST=1
endif

LDFLAGS := -L $(ROOTFS)/system/lib64 \
  -L $(ROOTFS)/system/lib64/bootstrap \
  -lc -lc++ -lbinder_ndk \
  -l:android.hardware.graphics.composer3-V4-ndk.so \
  -l:android.hardware.graphics.common-V6-ndk.so \
  -l:android.hardware.common-V2-ndk.so \
  -l:android.hardware.drm.common-V1-ndk.so \
  -Wl,-dynamic-linker,/system/bin/linker64

all: $(BIN)

$(BUILD_DIR)/test-linear-copy: tests/test_linear_copy.cpp linear_copy.h
	@mkdir -p $(BUILD_DIR)
	$(HOST_CXX) -std=c++17 -O2 -Wall -Wextra -Werror -I. $< -o $@

$(BUILD_DIR)/test-virtual-transport-pool: tests/test_virtual_transport_pool.cpp virtual_transport_pool.h
	@mkdir -p $(BUILD_DIR)
	$(HOST_CXX) -std=c++17 -O2 -Wall -Wextra -Werror -I. $< -o $@

$(BUILD_DIR)/test-mixed-compose: tests/test_mixed_compose.cpp mixed_compose.h
	@mkdir -p $(BUILD_DIR)
	$(HOST_CXX) -std=c++17 -O2 -Wall -Wextra -Werror -I. $< -o $@

test: $(BUILD_DIR)/test-linear-copy $(BUILD_DIR)/test-virtual-transport-pool $(BUILD_DIR)/test-mixed-compose
	$(BUILD_DIR)/test-linear-copy
	$(BUILD_DIR)/test-virtual-transport-pool
	$(BUILD_DIR)/test-mixed-compose

$(BIN): FORCE $(SRCS) $(HEADERS) Makefile
	@mkdir -p $(OUT_DIR) $(BUILD_DIR)
	@test -n "$(LLD_PATH)" || { echo "missing ld.lld (install LLD matching Clang $(CLANG_MAJOR))" >&2; exit 1; }
	@ln -sf "$(LLD_PATH)" "$(BUILD_DIR)/ld.lld"
	$(CXX) $(CXXFLAGS) $(SRCS) $(LDFLAGS) -o $@

FORCE:

clean:
	rm -f $(BIN)

.PHONY: all clean test FORCE
