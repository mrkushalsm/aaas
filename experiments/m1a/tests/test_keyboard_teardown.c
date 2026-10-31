#include <poll.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include <wayland-client-protocol.h>
#include <wayland-server-protocol.h>
#include <wayland-client.h>
#include <wayland-server.h>
#include <xkbcommon/xkbcommon.h>

typedef struct test_server {
    struct wl_display *display;
    struct wl_resource *keyboard;
    struct wl_resource *surface;
    atomic_int send_enter;
    atomic_int entered;
    atomic_int running;
} test_server;

typedef struct test_client {
    struct wl_display *display;
    struct wl_registry *registry;
    struct wl_compositor *compositor;
    struct wl_seat *seat;
    struct wl_surface *surface;
    struct wl_keyboard *keyboard;
    struct xkb_context *context;
    struct xkb_keymap *keymap;
    struct xkb_state *state;
    unsigned enter_callbacks;
} test_client;

static void resource_destroy_request(struct wl_client *client,
                                     struct wl_resource *resource) {
    (void)client;
    wl_resource_destroy(resource);
}

static void resource_destroy_notify(struct wl_resource *resource) {
    (void)resource;
}

static void surface_destroy(struct wl_client *client, struct wl_resource *resource) {
    (void)client;
    wl_resource_destroy(resource);
}

static const struct wl_surface_interface surface_impl = {
    .destroy = surface_destroy,
};

static void compositor_create_surface(struct wl_client *client,
                                      struct wl_resource *resource, uint32_t id) {
    test_server *server = wl_resource_get_user_data(resource);
    server->surface = wl_resource_create(client, &wl_surface_interface, 4, id);
    if (!server->surface) abort();
    wl_resource_set_implementation(server->surface, &surface_impl, server, NULL);
}

static const struct wl_compositor_interface compositor_impl = {
    .create_surface = compositor_create_surface,
};

static void seat_get_keyboard(struct wl_client *client,
                              struct wl_resource *resource, uint32_t id) {
    test_server *server = wl_resource_get_user_data(resource);
    server->keyboard = wl_resource_create(client, &wl_keyboard_interface, 4, id);
    if (!server->keyboard) abort();
    wl_resource_set_implementation(server->keyboard, NULL, server,
                                   resource_destroy_notify);
}

static const struct wl_seat_interface seat_impl = {
    .get_keyboard = seat_get_keyboard,
    .release = resource_destroy_request,
};

static void bind_compositor(struct wl_client *client, void *data, uint32_t version,
                            uint32_t id) {
    struct wl_resource *resource = wl_resource_create(
        client, &wl_compositor_interface, version < 4 ? version : 4, id);
    if (!resource) abort();
    wl_resource_set_implementation(resource, &compositor_impl, data,
                                   resource_destroy_notify);
}

static void bind_seat(struct wl_client *client, void *data, uint32_t version,
                      uint32_t id) {
    struct wl_resource *resource = wl_resource_create(
        client, &wl_seat_interface, version < 4 ? version : 4, id);
    if (!resource) abort();
    wl_resource_set_implementation(resource, &seat_impl, data,
                                   resource_destroy_notify);
    wl_seat_send_capabilities(resource, WL_SEAT_CAPABILITY_KEYBOARD);
}

static void *server_main(void *opaque) {
    test_server *server = opaque;
    struct wl_event_loop *loop = wl_display_get_event_loop(server->display);
    while (atomic_load(&server->running)) {
        if (wl_event_loop_dispatch(loop, 2) < 0) break;
        if (atomic_exchange(&server->send_enter, 0)) {
            struct wl_array keys;
            wl_array_init(&keys);
            if (!server->keyboard || !server->surface) abort();
            wl_keyboard_send_enter(server->keyboard, 7, server->surface, &keys);
            wl_array_release(&keys);
            atomic_store(&server->entered, 1);
        }
        wl_display_flush_clients(server->display);
    }
    return NULL;
}

static void registry_global(void *data, struct wl_registry *registry, uint32_t name,
                             const char *interface, uint32_t version) {
    test_client *client = data;
    if (!strcmp(interface, wl_compositor_interface.name)) {
        client->compositor = wl_registry_bind(registry, name,
            &wl_compositor_interface, version < 4 ? version : 4);
    } else if (!strcmp(interface, wl_seat_interface.name)) {
        client->seat = wl_registry_bind(registry, name, &wl_seat_interface,
            version < 4 ? version : 4);
    }
}

static void registry_remove(void *data, struct wl_registry *registry, uint32_t name) {
    (void)data; (void)registry; (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_global,
    .global_remove = registry_remove,
};

static void keyboard_keymap(void *data, struct wl_keyboard *keyboard,
                            uint32_t format, int32_t fd, uint32_t size) {
    (void)data; (void)keyboard; (void)format; (void)size;
    close(fd);
}

static void keyboard_enter(void *data, struct wl_keyboard *keyboard, uint32_t serial,
                           struct wl_surface *surface, struct wl_array *keys) {
    (void)keyboard; (void)serial; (void)surface; (void)keys;
    test_client *client = data;
    client->enter_callbacks++;
    /* Same class of access made by aaas_android_meta_state(). */
    (void)xkb_state_mod_name_is_active(client->state, "Shift",
                                       XKB_STATE_MODS_EFFECTIVE);
}

static void keyboard_leave(void *data, struct wl_keyboard *keyboard, uint32_t serial,
                           struct wl_surface *surface) {
    (void)data; (void)keyboard; (void)serial; (void)surface;
}

static void keyboard_key(void *data, struct wl_keyboard *keyboard, uint32_t serial,
                         uint32_t time, uint32_t key, uint32_t state) {
    (void)data; (void)keyboard; (void)serial; (void)time; (void)key; (void)state;
}

static void keyboard_modifiers(void *data, struct wl_keyboard *keyboard,
                               uint32_t serial, uint32_t depressed, uint32_t latched,
                               uint32_t locked, uint32_t group) {
    (void)data; (void)keyboard; (void)serial; (void)depressed;
    (void)latched; (void)locked; (void)group;
}

static void keyboard_repeat_info(void *data, struct wl_keyboard *keyboard,
                                 int32_t rate, int32_t delay) {
    (void)data; (void)keyboard; (void)rate; (void)delay;
}

static const struct wl_keyboard_listener keyboard_listener = {
    .keymap = keyboard_keymap,
    .enter = keyboard_enter,
    .leave = keyboard_leave,
    .key = keyboard_key,
    .modifiers = keyboard_modifiers,
    .repeat_info = keyboard_repeat_info,
};

static int read_one_event_without_dispatch(struct wl_display *display) {
    int fd = wl_display_get_fd(display);
    struct pollfd pfd = {.fd = fd, .events = POLLIN};
    if (wl_display_prepare_read(display) != 0) return -1;
    if (wl_display_flush(display) < 0 && errno != EAGAIN) {
        wl_display_cancel_read(display);
        return -1;
    }
    if (poll(&pfd, 1, 2000) <= 0) {
        wl_display_cancel_read(display);
        return -1;
    }
    return wl_display_read_events(display);
}

int main(int argc, char **argv) {
    int dispatch_control = argc == 2 && !strcmp(argv[1], "--dispatch-control");
    test_server server = {0};
    test_client client = {0};
    int fds[2];
    pthread_t thread;
    if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, fds) != 0) return 2;
    server.display = wl_display_create();
    if (!server.display) return 2;
    wl_global_create(server.display, &wl_compositor_interface, 4, &server,
                     bind_compositor);
    wl_global_create(server.display, &wl_seat_interface, 4, &server, bind_seat);
    if (!wl_client_create(server.display, fds[0])) return 2;
    atomic_store(&server.running, 1);
    if (pthread_create(&thread, NULL, server_main, &server) != 0) return 2;

    client.display = wl_display_connect_to_fd(fds[1]);
    if (!client.display) return 2;
    client.registry = wl_display_get_registry(client.display);
    wl_registry_add_listener(client.registry, &registry_listener, &client);
    if (wl_display_roundtrip(client.display) < 0 || !client.compositor || !client.seat)
        return 2;
    client.surface = wl_compositor_create_surface(client.compositor);
    client.keyboard = wl_seat_get_keyboard(client.seat);
    wl_keyboard_add_listener(client.keyboard, &keyboard_listener, &client);
    if (wl_display_roundtrip(client.display) < 0) return 2;

    client.context = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    client.keymap = xkb_keymap_new_from_names(client.context, NULL,
                                               XKB_KEYMAP_COMPILE_NO_FLAGS);
    client.state = xkb_state_new(client.keymap);
    if (!client.context || !client.keymap || !client.state) return 2;

    atomic_store(&server.send_enter, 1);
    for (int i = 0; i < 100 && !atomic_load(&server.entered); ++i) usleep(1000);
    if (!atomic_load(&server.entered) || read_one_event_without_dispatch(client.display) < 0)
        return 2;

    if (dispatch_control) {
        if (wl_display_dispatch_pending(client.display) < 0 ||
            client.enter_callbacks != 1) {
            fprintf(stderr, "control did not dispatch the queued keyboard enter\n");
            return 1;
        }
    }

    /* Match presenter teardown: destroy the event source before XKB state. */
    wl_keyboard_destroy(client.keyboard);
    client.keyboard = NULL;
    xkb_state_unref(client.state);
    client.state = NULL;
    xkb_keymap_unref(client.keymap);
    client.keymap = NULL;
    xkb_context_unref(client.context);
    client.context = NULL;
    if (wl_display_dispatch_pending(client.display) < 0) return 2;
    if (client.enter_callbacks != (dispatch_control ? 1U : 0U)) {
        fprintf(stderr, "queued keyboard enter ran after proxy teardown\n");
        return 1;
    }

    wl_surface_destroy(client.surface);
    wl_seat_destroy(client.seat);
    wl_compositor_destroy(client.compositor);
    wl_registry_destroy(client.registry);
    wl_display_disconnect(client.display);
    atomic_store(&server.running, 0);
    pthread_join(thread, NULL);
    wl_display_destroy_clients(server.display);
    wl_display_destroy(server.display);
    puts(dispatch_control
        ? "control delivered queued enter before teardown; XKB state remained live"
        : "queued wl_keyboard.enter discarded after proxy teardown; XKB state released safely");
    return 0;
}
