CC := clang
TARGET ?= x86_64-linux-android
WORKSPACE_ROOT ?= /run/media/mrkus/Homework/aaas-workspace
ROOTFS ?= $(WORKSPACE_ROOT)/rootfs_m1b1
OUT_DIR ?= build
BIN ?= $(OUT_DIR)/aaas-input-adapter

SRCS := aaas_input_adapter.c ../../m1a/src/input_v1.c ../../m1a/src/input_state.c

CFLAGS := -target $(TARGET) -std=c11 -O2 -g -Wall -Wextra -Werror \
  -nostdlib -D_GNU_SOURCE -D__BIONIC__ '-D__INTRODUCED_IN(n)=' -D__ANDROID_API__=35 \
  -I ../../m1a/src

LDFLAGS := -L $(ROOTFS)/system/lib64 \
  -lc -Wl,-dynamic-linker,/system/bin/linker64

all: $(BIN)

$(BIN): $(SRCS)
	@mkdir -p $(OUT_DIR)
	$(CC) $(CFLAGS) $(SRCS) $(LDFLAGS) -o $@

clean:
	rm -f $(BIN)

.PHONY: all clean
