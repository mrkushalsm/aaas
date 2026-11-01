CC := clang
CXX := clang++
TARGET ?= x86_64-linux-android
WORKSPACE_ROOT ?= /run/media/mrkus/Homework/aaas-workspace
ROOTFS ?= $(WORKSPACE_ROOT)/rootfs_m1b1
OUT_DIR ?= build
BIN ?= $(OUT_DIR)/aaas-input-adapter

SRCS := aaas_input_adapter.c ../../m1a/src/input_v1.c ../../m1a/src/input_state.c \
        inject_binder.cpp

CFLAGS := -target $(TARGET) -std=c11 -O2 -g -Wall -Wextra -Werror \
  -nostdlib -D_GNU_SOURCE -D__BIONIC__ '-D__INTRODUCED_IN(n)=' -D__ANDROID_API__=35 \
  -I ../../m1a/src

CXXFLAGS := -target $(TARGET) -std=c++17 -O2 -g -Wall -Wextra -Werror \
  -nostdlib -nostdinc -fno-exceptions -fno-rtti -fno-threadsafe-statics \
  -D_GNU_SOURCE -D__BIONIC__ -D__ANDROID_API__=35 -D__ANDROID_MIN_SDK_VERSION__=35 \
  -isystem $(WORKSPACE_ROOT)/toolchain/libc++/usr/include/c++/v1 \
  -isystem /usr/lib/clang/23/include \
  -isystem $(WORKSPACE_ROOT)/sources/bionic-android16/libc/include \
  -isystem $(WORKSPACE_ROOT)/sources/bionic-android16/libc/kernel/android/uapi \
  -isystem $(WORKSPACE_ROOT)/sources/bionic-android16/libc/kernel/uapi \
  -isystem $(WORKSPACE_ROOT)/sources/bionic-android16/libc/kernel/uapi/asm-x86 \
  -I ../../m1a/src

CPPFLAGS := \
  -I $(WORKSPACE_ROOT)/sources/frameworks-native-qpr2/libs/binder/include \
  -I $(WORKSPACE_ROOT)/sources/core-android16/libutils/include \
  -I $(WORKSPACE_ROOT)/sources/libbase-android16/include \
  -I $(WORKSPACE_ROOT)/sources/logging-android16/liblog/include \
  -I $(WORKSPACE_ROOT)/sources/core-android16/libcutils/include

LDFLAGS := -target $(TARGET) -nostdlib -fuse-ld=lld \
  -Wl,-dynamic-linker,/system/bin/linker64 \
  -L $(ROOTFS)/system/lib64 \
  -lc++ -lbinder -lutils -lbase -llog -lcutils -lc -lm -ldl

all: $(BIN)

$(BIN): $(SRCS) ../../m1a/src/input_v1.h ../../m1a/src/input_state.h inject_binder.h mouse_event_sequence.h pointer_source.h pointer_injection_policy.h event_id.h
	@mkdir -p $(OUT_DIR)
	$(CC) $(CFLAGS) $(CPPFLAGS) -c aaas_input_adapter.c -o $(OUT_DIR)/adapter.o
	$(CC) $(CFLAGS) $(CPPFLAGS) -c ../../m1a/src/input_v1.c -o $(OUT_DIR)/input_v1.o
	$(CC) $(CFLAGS) $(CPPFLAGS) -c ../../m1a/src/input_state.c -o $(OUT_DIR)/input_state.o
	$(CXX) $(CXXFLAGS) $(CPPFLAGS) -c inject_binder.cpp -o $(OUT_DIR)/inject_binder.o
	$(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OUT_DIR)/adapter.o $(OUT_DIR)/input_v1.o $(OUT_DIR)/input_state.o $(OUT_DIR)/inject_binder.o $(LDFLAGS) -o $@

clean:
	rm -rf $(OUT_DIR)

test:
	@mkdir -p $(OUT_DIR)
	$(CC) -std=c11 -Wall -Wextra -Werror -I. tests/test_mouse_event_sequence.c -o $(OUT_DIR)/test-mouse-event-sequence
	$(OUT_DIR)/test-mouse-event-sequence

.PHONY: all clean test
