CC ?= cc
CFLAGS += -std=c11 -O2 -g -Wall -Wextra -Werror -D_GNU_SOURCE
BUILD = build
XML = /usr/share/qt6/wayland/protocols
LOCAL_XML = protocols
PKGS = wayland-client gbm libdrm egl glesv2 xkbcommon
CPPFLAGS += -Isrc -I$(BUILD) $(shell pkg-config --cflags $(PKGS))
LDLIBS += $(shell pkg-config --libs $(PKGS)) -lm

PROTOCOLS_HDR = \
	$(BUILD)/xdg-shell-client-protocol.h \
	$(BUILD)/linux-dmabuf-client-protocol.h \
	$(BUILD)/presentation-time-client-protocol.h \
	$(BUILD)/linux-drm-syncobj-client-protocol.h

PROTOCOLS_SRC = \
	$(BUILD)/xdg-shell-protocol.c \
	$(BUILD)/linux-dmabuf-protocol.c \
	$(BUILD)/presentation-time-protocol.c \
	$(BUILD)/linux-drm-syncobj-protocol.c

all: $(BUILD)/aaas-m1a $(BUILD)/aaas-m1a1 $(BUILD)/wayland-host-presenter

$(BUILD):
	mkdir -p $@

$(BUILD)/xdg-shell-client-protocol.h: $(XML)/xdg-shell/xdg-shell.xml | $(BUILD)
	wayland-scanner client-header $< $@

$(BUILD)/xdg-shell-protocol.c: $(XML)/xdg-shell/xdg-shell.xml | $(BUILD)
	wayland-scanner private-code $< $@

$(BUILD)/linux-dmabuf-client-protocol.h: $(XML)/linux-dmabuf/linux-dmabuf-unstable-v1.xml | $(BUILD)
	wayland-scanner client-header $< $@

$(BUILD)/linux-dmabuf-protocol.c: $(XML)/linux-dmabuf/linux-dmabuf-unstable-v1.xml | $(BUILD)
	wayland-scanner private-code $< $@

$(BUILD)/presentation-time-client-protocol.h: $(XML)/presentation-time/presentation-time.xml | $(BUILD)
	wayland-scanner client-header $< $@

$(BUILD)/presentation-time-protocol.c: $(XML)/presentation-time/presentation-time.xml | $(BUILD)
	wayland-scanner private-code $< $@

$(BUILD)/linux-drm-syncobj-client-protocol.h: $(LOCAL_XML)/linux-drm-syncobj-v1.xml | $(BUILD)
	wayland-scanner client-header $< $@

$(BUILD)/linux-drm-syncobj-protocol.c: $(LOCAL_XML)/linux-drm-syncobj-v1.xml | $(BUILD)
	wayland-scanner private-code $< $@

# Original M1A baseline (v1)
$(BUILD)/aaas-m1a: src/main.c src/wire.c $(BUILD)/xdg-shell-protocol.c $(BUILD)/linux-dmabuf-protocol.c $(BUILD)/presentation-time-protocol.c $(PROTOCOLS_HDR) | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) src/main.c src/wire.c $(BUILD)/xdg-shell-protocol.c $(BUILD)/linux-dmabuf-protocol.c $(BUILD)/presentation-time-protocol.c -o $@ $(LDLIBS)

# New M1A.1 GPU Explicit Sync (v2)
$(BUILD)/aaas-m1a1: src/main_v2.c src/gpu_producer.c src/gpu_presenter.c src/wire_v2.c src/sync_util.c src/input_v1.c src/input_map.c $(PROTOCOLS_SRC) $(PROTOCOLS_HDR) | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) src/main_v2.c src/gpu_producer.c src/gpu_presenter.c src/wire_v2.c src/sync_util.c src/input_v1.c src/input_map.c $(PROTOCOLS_SRC) -o $@ $(LDLIBS)

# Standalone Host Wayland Presenter for Android Container
$(BUILD)/wayland-host-presenter: src/wayland_host_presenter.c src/gpu_presenter.c src/keyboard_map.c src/keyboard_map.h src/input_v1.h src/wire_v2.c src/sync_util.c src/input_v1.c src/input_map.c $(PROTOCOLS_SRC) $(PROTOCOLS_HDR) | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) src/wayland_host_presenter.c src/gpu_presenter.c src/keyboard_map.c src/wire_v2.c src/sync_util.c src/input_v1.c src/input_map.c $(PROTOCOLS_SRC) -o $@ $(LDLIBS)

# Tests
$(BUILD)/test-wire: tests/wire.c src/wire.c | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@

$(BUILD)/test-wire-v2: tests/test_wire_v2.c src/wire_v2.c src/sync_util.c | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(LDLIBS)

$(BUILD)/test-sync-util: tests/test_sync_util.c src/sync_util.c | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(LDLIBS)

$(BUILD)/test-stress: tests/test_stress.c src/wire_v2.c src/sync_util.c | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(LDLIBS) -lpthread

$(BUILD)/test-input-map: tests/test_input_map.c src/input_map.c | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(LDLIBS)

$(BUILD)/test-input-v1: tests/test_input_v1.c src/input_v1.c | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@

$(BUILD)/test-keyboard-map: tests/test_keyboard_map.c src/keyboard_map.c | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(shell pkg-config --libs xkbcommon)

$(BUILD)/test-input-state: tests/test_input_state.c src/input_state.c src/input_v1.c | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@

test: $(BUILD)/test-wire $(BUILD)/test-wire-v2 $(BUILD)/test-sync-util $(BUILD)/test-stress $(BUILD)/test-input-map $(BUILD)/test-input-v1 $(BUILD)/test-input-state $(BUILD)/test-keyboard-map
	$(BUILD)/test-wire
	$(BUILD)/test-wire-v2
	$(BUILD)/test-sync-util
	$(BUILD)/test-stress
	$(BUILD)/test-input-map
	$(BUILD)/test-input-v1
	$(BUILD)/test-input-state
	$(BUILD)/test-keyboard-map

clean:
	rm -rf $(BUILD)

.PHONY: all test clean
