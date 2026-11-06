#include "ext-data-control-v1-client-protocol.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>

#define FIXTURE "Linux → Android\nΚαλημέρα 世界\n punctuation: !?"
#define MIME_UTF8 "text/plain;charset=utf-8"
#define MIME_TEXT "text/plain"
#define MIME_UTF8_STRING "UTF8_STRING"

struct probe {
    struct wl_display *display;
    struct wl_registry *registry;
    struct wl_seat *seat;
    struct ext_data_control_manager_v1 *manager;
    struct ext_data_control_device_v1 *device;
    struct ext_data_control_source_v1 *source;
    int sent;
    int cancelled;
};

static void send_data(void *data, struct ext_data_control_source_v1 *source,
                      const char *mime, int32_t fd) {
    (void)source;
    struct probe *p = data;
    if (!strcmp(mime, MIME_UTF8) || !strcmp(mime, MIME_TEXT) ||
        !strcmp(mime, MIME_UTF8_STRING)) {
        const char fixture[] = FIXTURE;
        size_t offset = 0;
        while (offset < sizeof(fixture) - 1) {
            ssize_t count = write(fd, fixture + offset, sizeof(fixture) - 1 - offset);
            if (count < 0 && errno == EINTR) continue;
            if (count <= 0) break;
            offset += (size_t)count;
        }
        p->sent = offset == sizeof(fixture) - 1;
    }
    close(fd);
}

static void source_cancelled(void *data,
                             struct ext_data_control_source_v1 *source) {
    (void)source;
    ((struct probe *)data)->cancelled = 1;
}

static const struct ext_data_control_source_v1_listener source_listener = {
    .send = send_data,
    .cancelled = source_cancelled,
};

static void seat_capabilities(void *data, struct wl_seat *seat, uint32_t caps) {
    (void)data; (void)seat; (void)caps;
}

static void seat_name(void *data, struct wl_seat *seat, const char *name) {
    (void)data; (void)seat; (void)name;
}

static const struct wl_seat_listener seat_listener = {
    .capabilities = seat_capabilities,
    .name = seat_name,
};

static void global(void *data, struct wl_registry *registry, uint32_t name,
                   const char *interface, uint32_t version) {
    struct probe *p = data;
    if (!strcmp(interface, "wl_seat") && !p->seat) {
        p->seat = wl_registry_bind(registry, name, &wl_seat_interface,
                                   version < 7 ? version : 7);
        wl_seat_add_listener(p->seat, &seat_listener, p);
    } else if (!strcmp(interface, "ext_data_control_manager_v1") && !p->manager) {
        p->manager = wl_registry_bind(registry, name,
                                      &ext_data_control_manager_v1_interface, 1);
    }
}

static void global_remove(void *data, struct wl_registry *registry, uint32_t name) {
    (void)data; (void)registry; (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = global,
    .global_remove = global_remove,
};

int main(void) {
    struct probe p = {0};
    p.display = wl_display_connect(NULL);
    if (!p.display) { perror("wl_display_connect"); return 2; }
    p.registry = wl_display_get_registry(p.display);
    wl_registry_add_listener(p.registry, &registry_listener, &p);
    if (wl_display_roundtrip(p.display) < 0 || !p.manager || !p.seat) {
        fprintf(stderr, "ext data-control clipboard is unavailable\n");
        return 2;
    }
    p.device = ext_data_control_manager_v1_get_data_device(p.manager, p.seat);
    p.source = ext_data_control_manager_v1_create_data_source(p.manager);
    if (!p.device || !p.source) return 2;
    ext_data_control_source_v1_add_listener(p.source, &source_listener, &p);
    ext_data_control_source_v1_offer(p.source, MIME_UTF8);
    ext_data_control_source_v1_offer(p.source, MIME_TEXT);
    ext_data_control_source_v1_offer(p.source, MIME_UTF8_STRING);
    ext_data_control_device_v1_set_selection(p.device, p.source);
    if (wl_display_roundtrip(p.display) < 0) return 2;
    fprintf(stderr, "probe clipboard source ready\n");
    while (!p.cancelled) {
        if (wl_display_dispatch(p.display) < 0) break;
    }
    fprintf(stderr, "probe source transfer=%s\n", p.sent ? "served" : "not-requested");
    if (p.source) ext_data_control_source_v1_destroy(p.source);
    if (p.device) ext_data_control_device_v1_destroy(p.device);
    if (p.manager) ext_data_control_manager_v1_destroy(p.manager);
    if (p.seat) wl_seat_release(p.seat);
    if (p.registry) wl_registry_destroy(p.registry);
    wl_display_disconnect(p.display);
    return p.sent ? 0 : 1;
}
