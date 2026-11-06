CC ?= cc
QT_CXX ?= c++
CFLAGS += -std=c11 -O2 -g -Wall -Wextra -Werror -D_GNU_SOURCE
BUILD := build
PROTOCOL := ext-data-control-v1.xml
PKGS := wayland-client
CPPFLAGS += $(shell pkg-config --cflags $(PKGS))
LDLIBS += $(shell pkg-config --libs $(PKGS))

.PHONY: all clean
all: $(BUILD)/aaas-wayland-clipboard $(BUILD)/qt-clipboard-probe $(BUILD)/wayland-source-probe

$(BUILD):
	mkdir -p $@

$(BUILD)/ext-data-control-v1-client-protocol.h: $(PROTOCOL) | $(BUILD)
	wayland-scanner client-header $< $@

$(BUILD)/ext-data-control-v1-protocol.c: $(PROTOCOL) | $(BUILD)
	wayland-scanner private-code $< $@

$(BUILD)/aaas-wayland-clipboard: wayland_clipboard.c $(BUILD)/ext-data-control-v1-protocol.c $(BUILD)/ext-data-control-v1-client-protocol.h
	$(CC) $(CFLAGS) $(CPPFLAGS) -I$(BUILD) wayland_clipboard.c $(BUILD)/ext-data-control-v1-protocol.c -o $@ $(LDLIBS)

$(BUILD)/qt-clipboard-probe: qt_clipboard_probe.cpp | $(BUILD)
	$(QT_CXX) -std=c++17 -O2 -fPIC -Wall -Wextra -Werror $$(pkg-config --cflags Qt6Widgets) $< -o $@ $$(pkg-config --libs Qt6Widgets)

$(BUILD)/wayland-source-probe: wayland_source_probe.c $(BUILD)/ext-data-control-v1-protocol.c $(BUILD)/ext-data-control-v1-client-protocol.h
	$(CC) $(CFLAGS) $(CPPFLAGS) -I$(BUILD) $< $(BUILD)/ext-data-control-v1-protocol.c -o $@ $(LDLIBS)

clean:
	rm -rf $(BUILD)
