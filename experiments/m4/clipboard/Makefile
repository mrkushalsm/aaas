CC ?= cc
CFLAGS += -std=c11 -O2 -g -Wall -Wextra -Werror -D_GNU_SOURCE
BUILD := build
PROTOCOL := ext-data-control-v1.xml
PKGS := wayland-client
CPPFLAGS += $(shell pkg-config --cflags $(PKGS))
LDLIBS += $(shell pkg-config --libs $(PKGS))

.PHONY: all clean
all: $(BUILD)/aaas-wayland-clipboard

$(BUILD):
	mkdir -p $@

$(BUILD)/ext-data-control-v1-client-protocol.h: $(PROTOCOL) | $(BUILD)
	wayland-scanner client-header $< $@

$(BUILD)/ext-data-control-v1-protocol.c: $(PROTOCOL) | $(BUILD)
	wayland-scanner private-code $< $@

$(BUILD)/aaas-wayland-clipboard: wayland_clipboard.c $(BUILD)/ext-data-control-v1-protocol.c $(BUILD)/ext-data-control-v1-client-protocol.h
	$(CC) $(CFLAGS) $(CPPFLAGS) -I$(BUILD) wayland_clipboard.c $(BUILD)/ext-data-control-v1-protocol.c -o $@ $(LDLIBS)

clean:
	rm -rf $(BUILD)
