CC ?= cc
CFLAGS += -std=c11 -O2 -g -Wall -Wextra -Werror -D_GNU_SOURCE
BUILD = build
XML = /usr/share/qt6/wayland/protocols
PKGS = wayland-client gbm libdrm
CPPFLAGS += -Isrc -I$(BUILD) $(shell pkg-config --cflags $(PKGS))
LDLIBS += $(shell pkg-config --libs $(PKGS))
all: $(BUILD)/aaas-m1a
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
$(BUILD)/aaas-m1a: src/main.c src/wire.c $(BUILD)/xdg-shell-protocol.c $(BUILD)/linux-dmabuf-protocol.c $(BUILD)/presentation-time-protocol.c
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(LDLIBS)
$(BUILD)/test-wire: tests/wire.c src/wire.c | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@
test: $(BUILD)/test-wire
	$(BUILD)/test-wire
clean:
	rm -rf $(BUILD)
.PHONY: all test clean
