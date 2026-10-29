#include "gpu_presenter.h"
#include "input_map.h"
#include "input_v1.h"
#include "keyboard_map.h"
#include "wire_v2.h"
#include "sync_util.h"

#include "xdg-shell-client-protocol.h"
#include "linux-dmabuf-client-protocol.h"
#include "presentation-time-client-protocol.h"
#include "linux-drm-syncobj-client-protocol.h"

#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>
#include <drm_fourcc.h>
#include <gbm.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <errno.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <sys/resource.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <linux/dma-buf.h>
#include <math.h>

#define MAX_SLOTS 32
#define INPUT_QUEUE_CAP 64u

typedef struct presenter_app presenter_app;

typedef struct {
    struct wl_buffer *wl;
    presenter_app *app;
    uint32_t id;
    uint32_t gen;
    int active;

    /* DRM syncobj per-slot release timeline */
    uint32_t release_timeline_handle;
    uint64_t release_point;
    struct wp_linux_drm_syncobj_timeline_v1 *release_timeline;
    bool explicit_sync_used;

    /* Staging BO for linear memfd fallback */
    struct gbm_bo *staging_bo;
} presenter_slot;

struct presenter_app {
    int sock;
    uint32_t w, h, gen;
    int configured;
    int closed;
    int copy_complete_enabled;

    int drm_fd;
    struct gbm_device *gbm;

    /* Wayland globals */
    struct wl_display *display;
    struct wl_registry *registry;
    struct wl_compositor *compositor;
    struct xdg_wm_base *wm_base;
    struct zwp_linux_dmabuf_v1 *dmabuf;
    struct wp_presentation *presentation;
    struct wp_linux_drm_syncobj_manager_v1 *syncobj_mgr;

    /* Surface objects */
    struct wl_surface *surface;
    struct xdg_surface *xdg_surf;
    struct xdg_toplevel *toplevel;
    struct wp_linux_drm_syncobj_surface_v1 *syncobj_surface;

    /* Acquire timeline */
    uint32_t acquire_timeline_handle;
    uint64_t acquire_point;
    struct wp_linux_drm_syncobj_timeline_v1 *acquire_timeline;

    /* Supported modifier table */
    uint64_t supported_modifiers[512];
    unsigned num_modifiers;

    /* Buffer slots */
    presenter_slot slots[MAX_SLOTS];

    /* Accounting */
    uint64_t imported;
    uint64_t submitted;
    uint64_t released;
    uint64_t rejected;
    uint64_t presented;
    uint64_t discarded;
    uint64_t explicit_sync_frames;

    /* Wayland pointer input */
    struct wl_seat *seat;
    struct wl_pointer *pointer;
    struct wl_keyboard *keyboard;
    struct xkb_context *xkb_context;
    struct xkb_keymap *xkb_keymap;
    struct xkb_state *xkb_state;
    int keyboard_focus;
    int keyboard_protocol_ready;
    uint32_t keyboard_repeat_rate;
    uint32_t keyboard_repeat_delay;
    uint32_t repeat_key;
    uint32_t repeat_count;
    uint64_t repeat_start_ns, repeat_next_ns;
    uint32_t repeat_android_keycode, repeat_keysym, repeat_unicode;
    uint8_t pressed_keys[768];
    uint32_t pressed_android_keycodes[768];
    aaas_input_keyboard_msg keyboard_queue[128];
    uint32_t keyboard_queue_head, keyboard_queue_count;
    uint32_t seat_name;
    double pointer_x;
    double pointer_y;
    int pointer_focus;
    int content_focus;
    uint32_t focus_generation;
    uint32_t pressed_buttons;
    int32_t last_input_x;
    int32_t last_input_y;

    /*
     * Private input transport.  The Android display can be a different size
     * from the Wayland surface, so keep the last accepted buffer geometry.
     */
    uint32_t display_w;
    uint32_t display_h;
    int input_listen_fd;
    int input_fd;
    uint64_t input_session_id;
    uint32_t input_sequence;
    uint64_t input_sent;
    uint64_t input_dropped;
    int keyboard_v2_enabled;

    /*
     * Latched Wayland pointer data for a single wl_pointer.frame.  Keeping the
     * frame grouping explicit avoids double counting axis_value120,
     * axis_discrete, and smooth axis data in a scroll burst.
     */
    uint32_t axis_source;
    int have_axis_source;
    uint32_t axis_seen_mask;
    uint32_t axis_stop_mask;
    int32_t axis_value120[2];
    uint32_t axis_value120_mask;
    int32_t axis_discrete[2];
    uint32_t axis_discrete_mask;
    double axis_smooth[2];
    uint64_t input_queued;

    /* Bounded non-blocking outbound queue for input relay. */
    aaas_input_msg input_queue[INPUT_QUEUE_CAP];
    uint32_t input_queue_head;
    uint32_t input_queue_tail;
    uint32_t input_queue_count;
};

static void log_presenter_event(const char *event, uint32_t gen, uint32_t id,
                                const char *extra_json) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    uint64_t t_ns = (uint64_t)t.tv_sec * 1000000000ULL + (uint64_t)t.tv_nsec;
    if (extra_json && *extra_json) {
        fprintf(stderr, "{\"t_ns\":%llu,\"role\":\"presenter\",\"event\":\"%s\","
                        "\"generation\":%u,\"id\":%u,%s}\n",
                (unsigned long long)t_ns, event, gen, id, extra_json);
    } else {
        fprintf(stderr, "{\"t_ns\":%llu,\"role\":\"presenter\",\"event\":\"%s\","
                        "\"generation\":%u,\"id\":%u}\n",
                (unsigned long long)t_ns, event, gen, id);
    }
}

static uint64_t monotonic_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ULL + (uint64_t)t.tv_nsec;
}

static uint32_t button_mask(uint32_t button) {
    switch (button) {
    case AAAS_INPUT_BUTTON_LEFT: return 1u << 0;
    case AAAS_INPUT_BUTTON_RIGHT: return 1u << 1;
    case AAAS_INPUT_BUTTON_MIDDLE: return 1u << 2;
    default: return 0;
    }
}

static aaas_mapped_point map_surface_point(presenter_app *a, double sx, double sy) {
    uint32_t display_w = a->display_w ? a->display_w : a->w;
    uint32_t display_h = a->display_h ? a->display_h : a->h;
    return aaas_map_surface_to_display(sx, sy, a->w, a->h, display_w, display_h);
}

/*
 * Bounded outbound queue for input relay.  The queue protects the Composer3
 * release-fence path from block/transient-buffer stalls: all sends are
 * nonblocking and we drop the least critical (motion/hover/scroll) packets
 * rather than stalling the presenter loop.
 */
static void input_queue_flush(presenter_app *a) {
    if (a->input_fd < 0) return;
    for (;;) {
        if (!a->input_queue_count && !a->keyboard_queue_count) return;
        aaas_input_msg *pi = a->input_queue_count ? &a->input_queue[a->input_queue_head] : NULL;
        aaas_input_keyboard_msg *ki = a->keyboard_queue_count
            ? &a->keyboard_queue[a->keyboard_queue_head] : NULL;
        uint32_t ps=UINT32_MAX, ks=UINT32_MAX;
        if(pi) { memcpy(&ps,(const uint8_t*)pi+12,sizeof(ps)); ps=le32toh(ps); }
        if(ki) { memcpy(&ks,(const uint8_t*)ki+12,sizeof(ks)); ks=le32toh(ks); }
        bool send_key=ki && (!pi || ks<ps);
        const void *item=send_key?(const void*)ki:(const void*)pi;
        size_t item_size=send_key?sizeof(*ki):sizeof(*pi);
        ssize_t n = send(a->input_fd, item, item_size, MSG_DONTWAIT | MSG_NOSIGNAL);
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
            return;
        }
        if (n != (ssize_t)item_size) {
            int saved_errno = errno;
            a->input_dropped++;
            char extra[96];
            uint32_t failed_type=AAAS_INPUT_KEY;
            if(!send_key) { aaas_input_msg failed; aaas_input_from_wire(&failed,pi); failed_type=failed.type; }
            snprintf(extra, sizeof(extra), "\"input_type\":%u,\"errno\":%d",
                     failed_type, saved_errno);
            log_presenter_event("input_flush_failed", a->gen, 0, extra);
            close(a->input_fd);
            a->input_fd = -1;
            a->input_queue_head = 0;
            a->input_queue_tail = 0;
            a->input_queue_count = 0;
            a->keyboard_queue_head=0; a->keyboard_queue_count=0;
            a->keyboard_v2_enabled=0;
            return;
        }
        a->input_sent++;
        if(send_key) { a->keyboard_queue_head=(a->keyboard_queue_head+1)%128; a->keyboard_queue_count--; }
        else { a->input_queue_head=(a->input_queue_head+1)%INPUT_QUEUE_CAP; a->input_queue_count--; }
    }
}

static void input_send_packet(presenter_app *a, uint16_t type, int32_t x, int32_t y,
                              uint32_t button, uint32_t state, uint32_t flags,
                              uint32_t axis_h) {
    if (a->input_fd < 0 || a->input_session_id == 0) {
        if (type == AAAS_INPUT_BUTTON || type == AAAS_INPUT_FOCUS) {
            log_presenter_event("input_no_adapter", a->gen, 0, NULL);
        }
        return;
    }

    aaas_input_msg host = {
        .magic = AAAS_INPUT_MAGIC,
        .version = AAAS_INPUT_VERSION,
        .type = type,
        .length = AAAS_INPUT_MSG_SIZE,
        .sequence = ++a->input_sequence,
        .display_id = 0,
        .display_generation = a->gen ? a->gen : 1,
        .timestamp_ns = monotonic_ns(),
        .session_id = a->input_session_id,
        .x = x,
        .y = y,
        .button = button,
        .state = state,
        .focus_generation = a->focus_generation,
        .flags = flags,
        .reserved = axis_h,
    };
    aaas_input_msg wire;
    aaas_input_to_wire(&wire, &host);

    if ((type == AAAS_INPUT_MOTION || type == AAAS_INPUT_HOVER) &&
        a->input_queue_count > 0) {
        uint32_t slot = (a->input_queue_head + a->input_queue_count - 1) % INPUT_QUEUE_CAP;
        aaas_input_msg pending;
        aaas_input_from_wire(&pending, &a->input_queue[slot]);
        if (pending.type == type && pending.button == button) {
            a->input_queue[slot] = wire;
            a->input_dropped++;
            log_presenter_event("input_motion_coalesced", a->gen,
                                host.sequence, NULL);
            return;
        }
    }
    if (a->input_queue_count >= INPUT_QUEUE_CAP) {
        int evicted = 0;
        if (type == AAAS_INPUT_BUTTON || type == AAAS_INPUT_FOCUS ||
            type == AAAS_INPUT_SHUTDOWN) {
            for (uint32_t i = 0; i < a->input_queue_count; i++) {
                uint32_t slot = (a->input_queue_head + i) % INPUT_QUEUE_CAP;
                aaas_input_msg pending;
                aaas_input_from_wire(&pending, &a->input_queue[slot]);
                if (pending.type == AAAS_INPUT_MOTION || pending.type == AAAS_INPUT_HOVER ||
                    pending.type == AAAS_INPUT_SCROLL || pending.type == AAAS_INPUT_AXIS_STOP) {
                    for (uint32_t j = i; j + 1 < a->input_queue_count; j++) {
                        uint32_t to = (a->input_queue_head + j) % INPUT_QUEUE_CAP;
                        uint32_t from = (a->input_queue_head + j + 1) % INPUT_QUEUE_CAP;
                        a->input_queue[to] = a->input_queue[from];
                    }
                    a->input_queue_count--;
                    a->input_queue_tail = (a->input_queue_head + a->input_queue_count) % INPUT_QUEUE_CAP;
                    a->input_dropped++;
                    evicted = 1;
                    break;
                }
            }
        }
        if (!evicted) {
            a->input_dropped++;
            char extra[128];
            snprintf(extra, sizeof(extra), "\"input_type\":%u,\"queue_count\":%u",
                     (unsigned)type, a->input_queue_count);
            log_presenter_event("input_queue_full", a->gen, host.sequence, extra);
            return;
        }
    }

    uint32_t slot = (a->input_queue_head + a->input_queue_count) % INPUT_QUEUE_CAP;
    a->input_queue[slot] = wire;
    a->input_queue_count++;
    a->input_queued++;
    input_queue_flush(a);

    char extra[256];
    snprintf(extra, sizeof(extra),
             "\"input_type\":%u,\"x\":%d,\"y\":%d,\"button\":%u,\"state\":%u,"
             "\"display_generation\":%u,\"focus_generation\":%u,\"sequence\":%u",
             (unsigned)type, x, y, button, state, host.display_generation,
             host.focus_generation, host.sequence);
    log_presenter_event("input_sent", a->gen, host.sequence, extra);
}

static void input_keyboard_flush(presenter_app *a) {
    input_queue_flush(a);
}

static void input_send_keyboard(presenter_app *a, uint16_t type, uint32_t evdev,
                                uint32_t keycode, uint32_t state, uint32_t meta,
                                uint32_t keysym, uint32_t unicode, uint32_t repeat) {
    if (!a->keyboard_v2_enabled || a->input_fd < 0 || !a->input_session_id) return;
    if (a->keyboard_queue_count == 128) {
        log_presenter_event("keyboard_queue_full", a->gen, 0, NULL);
        return;
    }
    aaas_input_keyboard_msg h = {
        .magic=AAAS_INPUT_MAGIC, .version=AAAS_INPUT_KEYBOARD_VERSION, .type=type,
        .length=AAAS_INPUT_KEYBOARD_MSG_SIZE, .sequence=++a->input_sequence,
        .display_id=0, .display_generation=a->gen ? a->gen : 1,
        .timestamp_ns=monotonic_ns(), .session_id=a->input_session_id,
        .focus_generation=a->focus_generation, .evdev_key=evdev,
        .android_keycode=keycode, .state=state, .meta_state=meta,
        .repeat_count=repeat, .keysym=keysym, .unicode_scalar=unicode,
    };
    uint32_t tail=(a->keyboard_queue_head+a->keyboard_queue_count)%128;
    aaas_input_keyboard_to_wire(&a->keyboard_queue[tail], &h);
    a->keyboard_queue_count++;
    input_keyboard_flush(a);
    char extra[128];
    snprintf(extra,sizeof(extra),"\"key_type\":%u,\"key_state\":%u,\"sequence\":%u",
             type,state,h.sequence);
    log_presenter_event("keyboard_event_queued",a->gen,h.sequence,extra);
}

static void input_send_hello(presenter_app *a) {
    int32_t w = (int32_t)(a->display_w ? a->display_w : a->w);
    int32_t h = (int32_t)(a->display_h ? a->display_h : a->h);
    if (w <= 0 || h <= 0) {
        w = 1280;
        h = 720;
    }
    input_send_packet(a, AAAS_INPUT_HELLO, w, h, 0, 1, 0, 0);
}

static void input_release_buttons(presenter_app *a, const char *reason) {
    uint32_t pressed = a->pressed_buttons;
    if (!pressed) {
        return;
    }
    static const uint32_t buttons[] = {
        AAAS_INPUT_BUTTON_LEFT,
        AAAS_INPUT_BUTTON_RIGHT,
        AAAS_INPUT_BUTTON_MIDDLE,
    };
    for (unsigned i = 0; i < sizeof(buttons) / sizeof(buttons[0]); i++) {
        if (pressed & button_mask(buttons[i])) {
            input_send_packet(a, AAAS_INPUT_BUTTON, a->last_input_x, a->last_input_y,
                              buttons[i], AAAS_INPUT_BUTTON_RELEASED, 0, 0);
        }
    }
    a->pressed_buttons = 0;
    char extra[96];
    snprintf(extra, sizeof(extra), "\"reason\":\"%s\",\"buttons\":%u",
             reason, pressed);
    log_presenter_event("input_buttons_released", a->gen, 0, extra);
}

static void input_focus_enter(presenter_app *a, int32_t x, int32_t y) {
    a->focus_generation++;
    a->content_focus = 1;
    a->last_input_x = x;
    a->last_input_y = y;
    input_send_packet(a, AAAS_INPUT_FOCUS, x, y, 0, AAAS_INPUT_FOCUS_ENTER, 0, 0);
}

static void input_focus_leave(presenter_app *a, int32_t x, int32_t y) {
    a->focus_generation++;
    a->content_focus = 0;
    input_send_packet(a, AAAS_INPUT_FOCUS, x, y, 0, AAAS_INPUT_FOCUS_LEAVE, 0, 0);
}

static void pointer_enter(void *data, struct wl_pointer *pointer, uint32_t serial,
                          struct wl_surface *surface, wl_fixed_t sx, wl_fixed_t sy) {
    (void)pointer;
    (void)serial;
    presenter_app *a = data;
    if (surface != a->surface) {
        return;
    }
    a->pointer_focus = 1;
    a->pointer_x = wl_fixed_to_double(sx);
    a->pointer_y = wl_fixed_to_double(sy);
    aaas_mapped_point p = map_surface_point(a, a->pointer_x, a->pointer_y);
    if (p.inside) {
        input_focus_enter(a, p.x, p.y);
    } else {
        a->content_focus = 0;
    }
    char extra[192];
    snprintf(extra, sizeof(extra),
             "\"surface_x\":%.3f,\"surface_y\":%.3f,\"mapped\":%s,"
             "\"display_x\":%d,\"display_y\":%d",
             a->pointer_x, a->pointer_y, p.inside ? "true" : "false", p.x, p.y);
    log_presenter_event("input_pointer_enter", a->gen, 0, extra);
}

static void input_axis_clear(presenter_app *a);

static void pointer_leave(void *data, struct wl_pointer *pointer, uint32_t serial,
                          struct wl_surface *surface) {
    (void)pointer;
    (void)serial;
    presenter_app *a = data;
    if (surface != a->surface) {
        return;
    }
    a->pointer_focus = 0;
    input_axis_clear(a);
    if (a->pressed_buttons) {
        input_release_buttons(a, "pointer_leave");
    }
    if (a->content_focus) {
        input_focus_leave(a, a->last_input_x, a->last_input_y);
    }
    a->content_focus = 0;
    log_presenter_event("input_pointer_leave", a->gen, 0, NULL);
}

static void pointer_motion(void *data, struct wl_pointer *pointer, uint32_t time,
                           wl_fixed_t sx, wl_fixed_t sy) {
    (void)pointer;
    (void)time;
    presenter_app *a = data;
    a->pointer_x = wl_fixed_to_double(sx);
    a->pointer_y = wl_fixed_to_double(sy);
    if (!a->pointer_focus) {
        return;
    }

    aaas_mapped_point p = map_surface_point(a, a->pointer_x, a->pointer_y);
    if (p.inside) {
        if (!a->content_focus) {
            input_focus_enter(a, p.x, p.y);
        }
        a->last_input_x = p.x;
        a->last_input_y = p.y;
        /* Unpressed motion is only for the native Wayland cursor. The Android
         * adapter intentionally ignores it; forwarding every pointer sample
         * adds socket and polling work without changing Android UI state. */
        if (a->pressed_buttons) {
            input_send_packet(a, AAAS_INPUT_MOTION, p.x, p.y, 0, 0, 0, 0);
        }
    } else if (a->content_focus) {
        if (a->pressed_buttons) {
            input_release_buttons(a, "content_leave");
        }
        input_focus_leave(a, a->last_input_x, a->last_input_y);
    }
}

static void pointer_button(void *data, struct wl_pointer *pointer, uint32_t serial,
                           uint32_t time, uint32_t button, uint32_t state) {
    (void)pointer;
    (void)serial;
    (void)time;
    presenter_app *a = data;
    if (!a->pointer_focus) {
        return;
    }

    aaas_mapped_point p = map_surface_point(a, a->pointer_x, a->pointer_y);
    if (!p.inside) {
        if (a->content_focus) {
            if (a->pressed_buttons) {
                input_release_buttons(a, "button_outside");
            }
            input_focus_leave(a, a->last_input_x, a->last_input_y);
        }
        return;
    }
    if (!a->content_focus) {
        input_focus_enter(a, p.x, p.y);
    }
    a->last_input_x = p.x;
    a->last_input_y = p.y;

    uint32_t mask = button_mask(button);
    if (!mask) {
        char extra[64];
        snprintf(extra, sizeof(extra), "\"button\":%u", button);
        log_presenter_event("input_unsupported_button", a->gen, 0, extra);
        return;
    }

    if (state == WL_POINTER_BUTTON_STATE_PRESSED) {
        if (a->pressed_buttons & mask) {
            log_presenter_event("input_duplicate_press", a->gen, 0, NULL);
            return;
        }
        a->pressed_buttons |= mask;
        input_send_packet(a, AAAS_INPUT_BUTTON, p.x, p.y, button,
                          AAAS_INPUT_BUTTON_PRESSED, 0, 0);
    } else if (state == WL_POINTER_BUTTON_STATE_RELEASED) {
        if (!(a->pressed_buttons & mask)) {
            log_presenter_event("input_release_without_press", a->gen, 0, NULL);
            return;
        }
        a->pressed_buttons &= ~mask;
        input_send_packet(a, AAAS_INPUT_BUTTON, p.x, p.y, button,
                          AAAS_INPUT_BUTTON_RELEASED, 0, 0);
    } else {
        char extra[64];
        snprintf(extra, sizeof(extra), "\"state\":%u", state);
        log_presenter_event("input_bad_button_state", a->gen, 0, extra);
        return;
    }

    char extra[192];
    snprintf(extra, sizeof(extra),
             "\"button\":%u,\"state\":%u,\"surface_x\":%.3f,"
             "\"surface_y\":%.3f,\"surface_w\":%u,\"surface_h\":%u,"
             "\"display_x\":%d,\"display_y\":%d",
             button, state, a->pointer_x, a->pointer_y, a->w, a->h, p.x, p.y);
    log_presenter_event("input_pointer_button", a->gen, 0, extra);
}

static void pointer_axis(void *data, struct wl_pointer *pointer, uint32_t time,
                         uint32_t axis, wl_fixed_t value) {
    (void)pointer;
    (void)time;
    presenter_app *a = data;
    if (axis != WL_POINTER_AXIS_VERTICAL_SCROLL &&
        axis != WL_POINTER_AXIS_HORIZONTAL_SCROLL) {
        return;
    }
    unsigned idx = axis == WL_POINTER_AXIS_VERTICAL_SCROLL ? 0u : 1u;
    a->axis_seen_mask |= (1u << idx);
    a->axis_smooth[idx] += wl_fixed_to_double(value);
}

static void pointer_axis_value120(void *data, struct wl_pointer *pointer,
                                  uint32_t axis, int32_t value120) {
    (void)pointer;
    presenter_app *a = data;
    if (axis != WL_POINTER_AXIS_VERTICAL_SCROLL &&
        axis != WL_POINTER_AXIS_HORIZONTAL_SCROLL) {
        return;
    }
    unsigned idx = axis == WL_POINTER_AXIS_VERTICAL_SCROLL ? 0u : 1u;
    a->axis_value120[idx] += value120;
    a->axis_value120_mask |= (1u << idx);
}

static void pointer_axis_discrete(void *data, struct wl_pointer *pointer,
                                  uint32_t axis, int32_t discrete) {
    (void)pointer;
    presenter_app *a = data;
    if (axis != WL_POINTER_AXIS_VERTICAL_SCROLL &&
        axis != WL_POINTER_AXIS_HORIZONTAL_SCROLL) {
        return;
    }
    unsigned idx = axis == WL_POINTER_AXIS_VERTICAL_SCROLL ? 0u : 1u;
    a->axis_discrete[idx] += discrete;
    a->axis_discrete_mask |= (1u << idx);
}

static void input_axis_clear(presenter_app *a) {
    a->axis_source = 0;
    a->have_axis_source = 0;
    a->axis_seen_mask = 0;
    a->axis_stop_mask = 0;
    memset(a->axis_value120, 0, sizeof(a->axis_value120));
    memset(a->axis_discrete, 0, sizeof(a->axis_discrete));
    memset(a->axis_smooth, 0, sizeof(a->axis_smooth));
    a->axis_value120_mask = 0;
    a->axis_discrete_mask = 0;
}

static void input_axis_flush(presenter_app *a) {
    if (!a->axis_seen_mask && !a->axis_value120_mask && !a->axis_discrete_mask &&
        !a->axis_stop_mask) {
        input_axis_clear(a);
        return;
    }
    int32_t v = 0;
    int32_t h = 0;
    uint32_t flags = 0;
    if ((a->axis_value120_mask & 1u) && a->axis_value120[0] != 0) {
        v = -a->axis_value120[0];
        flags |= AAAS_INPUT_FLAG_AXIS_VALUE120;
    } else if ((a->axis_discrete_mask & 1u) && a->axis_discrete[0] != 0) {
        v = -a->axis_discrete[0] * 120;
        flags |= AAAS_INPUT_FLAG_AXIS_DISCRETE;
    } else if (a->axis_seen_mask & 1u) {
        v = -(int32_t)lround(a->axis_smooth[0] * 120.0);
        flags |= AAAS_INPUT_FLAG_AXIS_SMOOTH;
    }
    if ((a->axis_value120_mask & 2u) && a->axis_value120[1] != 0) {
        h = a->axis_value120[1];
        flags |= AAAS_INPUT_FLAG_AXIS_VALUE120;
    } else if ((a->axis_discrete_mask & 2u) && a->axis_discrete[1] != 0) {
        h = a->axis_discrete[1] * 120;
        flags |= AAAS_INPUT_FLAG_AXIS_DISCRETE;
    } else if (a->axis_seen_mask & 2u) {
        h = (int32_t)lround(a->axis_smooth[1] * 120.0);
        flags |= AAAS_INPUT_FLAG_AXIS_SMOOTH;
    }
    uint32_t source = a->axis_source;
    if (!a->have_axis_source) {
        source = AAAS_INPUT_AXIS_SOURCE_WHEEL;
    }
    if (!a->content_focus) {
        input_axis_clear(a);
        return;
    }
    if (v != 0 || h != 0) {
        input_send_packet(a, AAAS_INPUT_SCROLL, a->last_input_x, a->last_input_y,
                          source, (uint32_t)v, flags, (uint32_t)h);
    }
    if (a->axis_stop_mask & AAAS_INPUT_AXIS_VERTICAL) {
        input_send_packet(a, AAAS_INPUT_AXIS_STOP, a->last_input_x,
                          a->last_input_y, AAAS_INPUT_AXIS_VERTICAL, 0, 0, 0);
    }
    if (a->axis_stop_mask & AAAS_INPUT_AXIS_HORIZONTAL) {
        input_send_packet(a, AAAS_INPUT_AXIS_STOP, a->last_input_x,
                          a->last_input_y, AAAS_INPUT_AXIS_HORIZONTAL, 0, 0, 0);
    }
    input_axis_clear(a);
}

static void pointer_frame(void *data, struct wl_pointer *pointer) {
    (void)pointer;
    presenter_app *a = data;
    input_axis_flush(a);
}

static void pointer_axis_source(void *data, struct wl_pointer *pointer,
                                uint32_t axis_source) {
    (void)pointer;
    presenter_app *a = data;
    a->axis_source = axis_source;
    a->have_axis_source = 1;
}

static void pointer_axis_stop(void *data, struct wl_pointer *pointer,
                              uint32_t time, uint32_t axis) {
    (void)pointer;
    (void)time;
    presenter_app *a = data;
    if (axis != WL_POINTER_AXIS_VERTICAL_SCROLL &&
        axis != WL_POINTER_AXIS_HORIZONTAL_SCROLL) {
        return;
    }
    a->axis_stop_mask |= axis == WL_POINTER_AXIS_VERTICAL_SCROLL
            ? AAAS_INPUT_AXIS_VERTICAL : AAAS_INPUT_AXIS_HORIZONTAL;
}

static const struct wl_pointer_listener pointer_listener = {
    .enter = pointer_enter,
    .leave = pointer_leave,
    .motion = pointer_motion,
    .button = pointer_button,
    .axis = pointer_axis,
    .frame = pointer_frame,
    .axis_source = pointer_axis_source,
    .axis_stop = pointer_axis_stop,
    .axis_discrete = pointer_axis_discrete,
    .axis_value120 = pointer_axis_value120,
};

static void keyboard_send_focus(presenter_app *a, uint32_t state) {
    if (state == AAAS_INPUT_FOCUS_LEAVE) {
        for (uint32_t k=0;k<768;k++) if (a->pressed_keys[k]) {
            input_send_keyboard(a,AAAS_INPUT_KEY,k,a->pressed_android_keycodes[k],
                                AAAS_INPUT_KEY_RELEASED,aaas_android_meta_state(a->xkb_state),0,0,0);
            a->pressed_keys[k]=0;
            if(a->xkb_state) xkb_state_update_key(a->xkb_state,k+8,XKB_KEY_UP);
        }
        a->repeat_key=UINT32_MAX; a->repeat_count=0;
    }
    a->focus_generation++;
    input_send_keyboard(a,AAAS_INPUT_KEYBOARD_FOCUS,0,0,state,aaas_android_meta_state(a->xkb_state),0,0,0);
    a->keyboard_focus = state == AAAS_INPUT_FOCUS_ENTER;
}

static void keyboard_keymap(void *data, struct wl_keyboard *keyboard,
                            uint32_t format, int32_t fd, uint32_t size) {
    (void)keyboard;
    presenter_app *a=data;
    if (format != WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1 || size == 0 || size > 4*1024*1024) {
        if(fd>=0) close(fd);
        log_presenter_event("keyboard_keymap_rejected",a->gen,0,NULL); return;
    }
    if(fd<0) { log_presenter_event("keyboard_keymap_bad_fd",a->gen,0,NULL); return; }
    char *map=mmap(NULL,size,PROT_READ,MAP_PRIVATE,fd,0); close(fd);
    if(map==MAP_FAILED) { log_presenter_event("keyboard_keymap_mmap_failed",a->gen,0,NULL); return; }
    if(!memchr(map,'\0',size)) { munmap(map,size); log_presenter_event("keyboard_keymap_unterminated",a->gen,0,NULL); return; }
    if(!a->xkb_context) a->xkb_context=xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    struct xkb_keymap *km=a->xkb_context ? xkb_keymap_new_from_string(a->xkb_context,map,
        XKB_KEYMAP_FORMAT_TEXT_V1,XKB_KEYMAP_COMPILE_NO_FLAGS) : NULL;
    munmap(map,size);
    if(!km) { log_presenter_event("keyboard_keymap_compile_failed",a->gen,0,NULL); return; }
    struct xkb_state *xs=xkb_state_new(km);
    if(!xs) { xkb_keymap_unref(km); log_presenter_event("keyboard_state_create_failed",a->gen,0,NULL); return; }
    bool refocus=a->keyboard_focus;
    if(refocus) keyboard_send_focus(a,AAAS_INPUT_FOCUS_LEAVE);
    if(a->xkb_state) xkb_state_unref(a->xkb_state);
    if(a->xkb_keymap) xkb_keymap_unref(a->xkb_keymap);
    a->xkb_keymap=km; a->xkb_state=xs;
    if(refocus) keyboard_send_focus(a,AAAS_INPUT_FOCUS_ENTER);
    log_presenter_event("keyboard_keymap_ready",a->gen,0,NULL);
}

static void keyboard_key(void *data, struct wl_keyboard *kbd, uint32_t serial,
                         uint32_t time, uint32_t key, uint32_t state);

static void keyboard_enter(void *data, struct wl_keyboard *kbd, uint32_t serial,
                           struct wl_surface *surface, struct wl_array *keys) {
    (void)kbd;(void)serial;
    presenter_app *a=data;
    if(surface==a->surface && !a->keyboard_focus) {
        keyboard_send_focus(a,AAAS_INPUT_FOCUS_ENTER);
        uint32_t *held;
        wl_array_for_each(held,keys)
            keyboard_key(data,kbd,serial,0,*held,WL_KEYBOARD_KEY_STATE_PRESSED);
    }
}
static void keyboard_leave(void *data, struct wl_keyboard *kbd, uint32_t serial,
                           struct wl_surface *surface) {
    (void)kbd;(void)serial;(void)surface;
    presenter_app *a=data;
    if(a->keyboard_focus) keyboard_send_focus(a,AAAS_INPUT_FOCUS_LEAVE);
}
static void keyboard_key(void *data, struct wl_keyboard *kbd, uint32_t serial,
                         uint32_t time, uint32_t key, uint32_t state) {
    (void)kbd;(void)serial;(void)time;
    presenter_app *a=data;
    if(!a->keyboard_focus || !a->xkb_state || key>=768) return;
    xkb_keycode_t xkey=key+8;
    xkb_state_update_key(a->xkb_state,xkey,state==WL_KEYBOARD_KEY_STATE_PRESSED
        ? XKB_KEY_DOWN : XKB_KEY_UP);
    xkb_keysym_t sym=xkb_state_key_get_one_sym(a->xkb_state,xkey);
    uint32_t code=aaas_android_keycode_from_keysym(sym);
    if(!code) return;
    uint32_t meta=aaas_android_meta_state(a->xkb_state);
    uint32_t unicode=xkb_state_key_get_utf32(a->xkb_state,xkey);
    if(state==WL_KEYBOARD_KEY_STATE_PRESSED) {
        if(a->pressed_keys[key]) {
            a->repeat_count++;
            input_send_keyboard(a,AAAS_INPUT_KEY,key,code,AAAS_INPUT_KEY_PRESSED,meta,
                                (uint32_t)sym,unicode,a->repeat_count);
        } else {
            a->pressed_keys[key]=1; a->pressed_android_keycodes[key]=code;
            input_send_keyboard(a,AAAS_INPUT_KEY,key,code,AAAS_INPUT_KEY_PRESSED,meta,
                                (uint32_t)sym,unicode,0);
            if(a->keyboard_repeat_rate && code!=59 && code!=60 && code!=113 && code!=114 &&
               code!=57 && code!=58 && code!=115) {
                a->repeat_key=key; a->repeat_count=0;
                a->repeat_android_keycode=code; a->repeat_keysym=(uint32_t)sym;
                a->repeat_unicode=unicode;
                a->repeat_start_ns=monotonic_ns()+(uint64_t)a->keyboard_repeat_delay*1000000ULL;
                a->repeat_next_ns=a->repeat_start_ns;
            }
        }
    } else if(a->pressed_keys[key]) {
        input_send_keyboard(a,AAAS_INPUT_KEY,key,a->pressed_android_keycodes[key],
                            AAAS_INPUT_KEY_RELEASED,meta,(uint32_t)sym,unicode,0);
        a->pressed_keys[key]=0;
        if(a->repeat_key==key) { a->repeat_key=UINT32_MAX; a->repeat_count=0; }
    }
}
static void keyboard_modifiers(void *data, struct wl_keyboard *kbd, uint32_t serial,
                               uint32_t dep, uint32_t lat, uint32_t lock, uint32_t group) {
    (void)serial; presenter_app *a=data;
    if(a->xkb_state) xkb_state_update_mask(a->xkb_state,dep,lat,lock,0,0,group);
    (void)kbd;
}
static void keyboard_repeat_info(void *data, struct wl_keyboard *kbd, int32_t rate, int32_t delay) {
    (void)kbd; presenter_app *a=data;
    a->keyboard_repeat_rate=rate>0?(uint32_t)rate:0;
    a->keyboard_repeat_delay=delay>0?(uint32_t)delay:0;
    if(!a->keyboard_repeat_rate) a->repeat_key=UINT32_MAX;
    log_presenter_event("keyboard_repeat_info",a->gen,0,NULL);
}
static const struct wl_keyboard_listener keyboard_listener = {
    .keymap=keyboard_keymap,.enter=keyboard_enter,.leave=keyboard_leave,
    .key=keyboard_key,.modifiers=keyboard_modifiers,.repeat_info=keyboard_repeat_info,
};

static void keyboard_repeat_tick(presenter_app *a) {
    if(!a->keyboard_focus || !a->keyboard_repeat_rate || a->repeat_key>=768 ||
       !a->pressed_keys[a->repeat_key]) return;
    uint64_t now=monotonic_ns();
    if(now<a->repeat_next_ns) return;
    a->repeat_count++;
    input_send_keyboard(a,AAAS_INPUT_KEY,a->repeat_key,a->repeat_android_keycode,
        AAAS_INPUT_KEY_PRESSED,aaas_android_meta_state(a->xkb_state),a->repeat_keysym,
        a->repeat_unicode,a->repeat_count);
    a->repeat_next_ns=now+1000000000ULL/a->keyboard_repeat_rate;
}

static void destroy_keyboard(presenter_app *a) {
    if(a->keyboard) {
        if(a->keyboard_focus) keyboard_send_focus(a,AAAS_INPUT_FOCUS_LEAVE);
        if(wl_proxy_get_version((struct wl_proxy*)a->keyboard)>=WL_KEYBOARD_RELEASE_SINCE_VERSION)
            wl_keyboard_release(a->keyboard);
        else wl_keyboard_destroy(a->keyboard);
        a->keyboard=NULL;
    }
}

static void destroy_pointer(presenter_app *a) {
    if (!a->pointer) {
        return;
    }
    if (wl_proxy_get_version((struct wl_proxy *)a->pointer) >=
        WL_POINTER_RELEASE_SINCE_VERSION) {
        wl_pointer_release(a->pointer);
    } else {
        wl_pointer_destroy(a->pointer);
    }
    a->pointer = NULL;
}

static void seat_capabilities(void *data, struct wl_seat *seat, uint32_t caps) {
    presenter_app *a = data;
    bool pointer_capable = (caps & WL_SEAT_CAPABILITY_POINTER) != 0;
    bool keyboard_capable = (caps & WL_SEAT_CAPABILITY_KEYBOARD) != 0;
    char extra[128];
    snprintf(extra, sizeof(extra), "\"pointer_capable\":%s,\"keyboard_capable\":%s",
             pointer_capable ? "true" : "false", keyboard_capable ? "true" : "false");
    log_presenter_event("input_seat_capabilities", a->gen, 0, extra);

    if (pointer_capable) {
        if (!a->pointer) {
            a->pointer = wl_seat_get_pointer(seat);
            wl_pointer_add_listener(a->pointer, &pointer_listener, a);
            log_presenter_event("input_pointer_bound", a->gen, 0, NULL);
        }
    } else if (a->pointer) {
        if (a->pressed_buttons) {
            input_release_buttons(a, "pointer_removed");
        }
        if (a->content_focus) {
            input_focus_leave(a, a->last_input_x, a->last_input_y);
        }
        a->pointer_focus = 0;
        a->content_focus = 0;
        destroy_pointer(a);
        log_presenter_event("input_pointer_unbound", a->gen, 0, NULL);
    }
    if (keyboard_capable) {
        if (!a->keyboard) {
            a->keyboard=wl_seat_get_keyboard(seat);
            wl_keyboard_add_listener(a->keyboard,&keyboard_listener,a);
            log_presenter_event("input_keyboard_bound",a->gen,0,NULL);
        }
    } else if (a->keyboard) {
        destroy_keyboard(a);
        log_presenter_event("input_keyboard_unbound",a->gen,0,NULL);
    }
}

static void seat_name(void *data, struct wl_seat *seat, const char *name) {
    (void)seat;
    (void)name;
    presenter_app *a = data;
    log_presenter_event("input_seat_name", a->gen, 0, NULL);
}

static const struct wl_seat_listener seat_listener = {
    .capabilities = seat_capabilities,
    .name = seat_name,
};

static void dmabuf_format(void *data, struct zwp_linux_dmabuf_v1 *obj, uint32_t f) {
    (void)data; (void)obj; (void)f;
}

static void dmabuf_modifier(void *data, struct zwp_linux_dmabuf_v1 *obj,
                            uint32_t format, uint32_t hi, uint32_t lo) {
    (void)obj;
    presenter_app *a = data;
    uint64_t mod = ((uint64_t)hi << 32) | lo;
    if ((format == DRM_FORMAT_XRGB8888 || format == DRM_FORMAT_ARGB8888 ||
         format == DRM_FORMAT_RGBA8888 || format == DRM_FORMAT_ABGR8888) &&
        a->num_modifiers < 512) {
        a->supported_modifiers[a->num_modifiers++] = mod;
    }
}

static const struct zwp_linux_dmabuf_v1_listener dmabuf_listener = {
    .format = dmabuf_format,
    .modifier = dmabuf_modifier
};

static void registry_global(void *data, struct wl_registry *r, uint32_t name,
                            const char *iface, uint32_t ver) {
    presenter_app *a = data;
    if (strcmp(iface, "wl_compositor") == 0) {
        a->compositor = wl_registry_bind(r, name, &wl_compositor_interface, ver < 4 ? ver : 4);
    } else if (strcmp(iface, "xdg_wm_base") == 0) {
        a->wm_base = wl_registry_bind(r, name, &xdg_wm_base_interface, ver < 3 ? ver : 3);
    } else if (strcmp(iface, "wp_presentation") == 0) {
        a->presentation = wl_registry_bind(r, name, &wp_presentation_interface, 1);
    } else if (strcmp(iface, "zwp_linux_dmabuf_v1") == 0 && ver >= 3) {
        a->dmabuf = wl_registry_bind(r, name, &zwp_linux_dmabuf_v1_interface, 3);
    } else if (strcmp(iface, "wp_linux_drm_syncobj_manager_v1") == 0) {
        a->syncobj_mgr = wl_registry_bind(r, name, &wp_linux_drm_syncobj_manager_v1_interface, 1);
    } else if (strcmp(iface, "wl_seat") == 0) {
        a->seat_name = name;
        /* axis_value120 is available in wl_pointer v8; do not negotiate v9
         * until axis_relative_direction has a listener callback. */
        uint32_t bind_ver = ver < 8 ? ver : 8;
        a->seat = wl_registry_bind(r, name, &wl_seat_interface, bind_ver);
        wl_seat_add_listener(a->seat, &seat_listener, a);
    }
}

static void registry_global_remove(void *data, struct wl_registry *r, uint32_t n) {
    (void)r;
    presenter_app *a = data;
    if (n != a->seat_name || !a->seat) {
        return;
    }
    if (a->pointer) {
        if (a->pressed_buttons) {
            input_release_buttons(a, "seat_removed");
        }
        if (a->content_focus) {
            input_focus_leave(a, a->last_input_x, a->last_input_y);
        }
        a->pointer_focus = 0;
        a->content_focus = 0;
        destroy_pointer(a);
    }
    if (a->keyboard) destroy_keyboard(a);
    if (wl_proxy_get_version((struct wl_proxy *)a->seat) >=
        WL_SEAT_RELEASE_SINCE_VERSION) {
        wl_seat_release(a->seat);
    } else {
        wl_seat_destroy(a->seat);
    }
    a->seat = NULL;
    a->seat_name = 0;
    log_presenter_event("input_seat_removed", a->gen, 0, NULL);
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_global,
    .global_remove = registry_global_remove
};

static void xdg_wm_ping(void *data, struct xdg_wm_base *wm, uint32_t serial) {
    (void)data;
    xdg_wm_base_pong(wm, serial);
}

static const struct xdg_wm_base_listener wm_base_listener = {
    .ping = xdg_wm_ping
};

static void set_surface_opaque_region(presenter_app *a, uint32_t width,
                                      uint32_t height) {
    struct wl_region *region = wl_compositor_create_region(a->compositor);
    if (!region) {
        log_presenter_event("opaque_region_create_failed", a->gen, 0, NULL);
        return;
    }
    wl_region_add(region, 0, 0, (int32_t)width, (int32_t)height);
    wl_surface_set_opaque_region(a->surface, region);
    wl_region_destroy(region);
}

static void xdg_surface_configure(void *data, struct xdg_surface *xs, uint32_t serial) {
    presenter_app *a = data;
    xdg_surface_ack_configure(xs, serial);
    uint32_t prev_w = a->w;
    uint32_t prev_h = a->h;
    uint32_t w = a->w ? a->w : 640;
    uint32_t h = a->h ? a->h : 480;
    if (w > 1920) w = 1920;
    if (h > 1920) h = 1920;
    a->w = w;
    a->h = h;
    /* AaaS frames are complete Android display compositions, not translucent
     * overlays. Keep uninitialized startup alpha from exposing desktop pixels. */
    set_surface_opaque_region(a, w, h);

    bool initial = !a->configured;
    a->configured = 1;

    if (initial || w != prev_w || h != prev_h) {
        a->gen++;
        aaas_v2_msg m = {
            .magic = AAAS_V2_MAGIC,
            .version = AAAS_V2_VERSION,
            .type = AAAS_V2_RESIZE,
            .generation = a->gen,
            .width = w,
            .height = h,
        };
        if (aaas_v2_send(a->sock, &m, NULL, 0) != 0) {
            fprintf(stderr, "[AaaS Presenter] aaas_v2_send RESIZE failed: %s (errno=%d)\n", strerror(errno), errno);
            a->closed = 1;
        }
        char extra[64];
        snprintf(extra, sizeof(extra), "\"width\":%u,\"height\":%u", w, h);
        log_presenter_event("configure", a->gen, 0, extra);
    }
}

static const struct xdg_surface_listener xdg_surf_listener = {
    .configure = xdg_surface_configure
};

static void toplevel_configure(void *data, struct xdg_toplevel *t,
                               int32_t w, int32_t h, struct wl_array *states) {
    (void)t; (void)states;
    presenter_app *a = data;
    if (w > 0) a->w = (uint32_t)w;
    if (h > 0) a->h = (uint32_t)h;
}

static void toplevel_close(void *data, struct xdg_toplevel *t) {
    (void)t;
    presenter_app *a = data;
    a->closed = 1;
    log_presenter_event("close_requested", a->gen, 0, NULL);
}

static const struct xdg_toplevel_listener toplevel_listener = {
    .configure = toplevel_configure,
    .close = toplevel_close
};

static void finalize_buffer_release(presenter_slot *s, bool release_point_signaled) {
    presenter_app *a = s->app;

    int release_fence_fd = -1;
    uint32_t flags = 0;

    if (s->explicit_sync_used && s->release_timeline_handle) {
        /* Reaching this function means the explicit release point is complete. */
        int r = syncobj_timeline_export_sync_file(a->drm_fd,
                                                  s->release_timeline_handle,
                                                  s->release_point,
                                                  &release_fence_fd);
        if (r == 0 && release_fence_fd >= 0) {
            flags |= AAAS_V2_FLAG_RELEASE_FENCE;
        }
    }

    aaas_v2_msg m = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_RELEASE,
        .flags = flags,
        .generation = s->gen,
        .id = s->id,
    };

    int send_fds[1] = { release_fence_fd };
    unsigned nfds = (release_fence_fd >= 0) ? 1 : 0;
    if (aaas_v2_send(a->sock, &m, send_fds, nfds) != 0) {
        a->closed = 1;
    }
    if (release_fence_fd >= 0) {
        close(release_fence_fd);
    }

    char extra[96];
    snprintf(extra, sizeof(extra), "\"fence\":%s,\"point\":%llu,\"timeline_signaled\":%s",
             (flags & AAAS_V2_FLAG_RELEASE_FENCE) ? "\"exported\"" : "\"none\"",
             (unsigned long long)s->release_point,
             release_point_signaled ? "true" : "false");
    log_presenter_event("buffer_release", s->gen, s->id, extra);

    a->released++;
    if (s->staging_bo) {
        gbm_bo_destroy(s->staging_bo);
        s->staging_bo = NULL;
    }
    s->wl = NULL;
    s->active = 0;
    s->explicit_sync_used = false;
}

static void buffer_released(void *data, struct wl_buffer *buf) {
    presenter_slot *s = data;
    if (!s->active || s->wl != buf) {
        return;
    }

    if (s->explicit_sync_used && s->release_timeline_handle &&
        syncobj_timeline_wait(s->app->drm_fd, s->release_timeline_handle,
                              s->release_point, 0) != 0) {
        /* wl_buffer.release retires the protocol object, but with explicit
         * sync it does not prove the compositor's GPU read has completed.
         * Keep the transport slot in flight until the release point signals. */
        s->wl = NULL;
        wl_buffer_destroy(buf);
        char extra[80];
        snprintf(extra, sizeof(extra), "\"point\":%llu",
                 (unsigned long long)s->release_point);
        log_presenter_event("buffer_release_waiting_for_timeline", s->gen,
                            s->id, extra);
        return;
    }

    wl_buffer_destroy(buf);
    s->wl = NULL;
    finalize_buffer_release(s, s->explicit_sync_used &&
                               s->release_timeline_handle != 0);
}

static const struct wl_buffer_listener buffer_listener = {
    .release = buffer_released
};

static void check_release_timelines(presenter_app *a) {
    if (a->drm_fd < 0) return;
    for (int i = 0; i < MAX_SLOTS; i++) {
        presenter_slot *s = &a->slots[i];
        if (s->active && s->explicit_sync_used && s->release_timeline_handle) {
            if (syncobj_timeline_wait(a->drm_fd, s->release_timeline_handle, s->release_point, 0) == 0) {
                if (s->wl) {
                    wl_buffer_destroy(s->wl);
                    s->wl = NULL;
                }
                finalize_buffer_release(s, true);
            }
        }
    }
}

static void pres_sync_output(void *data, struct wp_presentation_feedback *f, struct wl_output *o) {
    (void)data; (void)f; (void)o;
}

static void pres_presented(void *data, struct wp_presentation_feedback *f,
                           uint32_t tv_sec_hi, uint32_t tv_sec_lo, uint32_t tv_nsec,
                           uint32_t refresh, uint32_t seq_hi, uint32_t seq_lo, uint32_t flags) {
    (void)tv_sec_hi; (void)tv_sec_lo; (void)tv_nsec; (void)refresh; (void)seq_hi; (void)seq_lo;
    presenter_app *a = data;
    a->presented++;
    char extra[64];
    snprintf(extra, sizeof(extra), "\"flags\":%u", flags);
    log_presenter_event("frame_presented", a->gen, 0, extra);
    check_release_timelines(a);
    wp_presentation_feedback_destroy(f);
}

static void pres_discarded(void *data, struct wp_presentation_feedback *f) {
    presenter_app *a = data;
    a->discarded++;
    log_presenter_event("frame_discarded", a->gen, 0, NULL);
    wp_presentation_feedback_destroy(f);
}

static const struct wp_presentation_feedback_listener pres_feedback_listener = {
    .sync_output = pres_sync_output,
    .presented = pres_presented,
    .discarded = pres_discarded
};

static int modifier_supported(presenter_app *a, uint64_t mod) {
    if (mod == DRM_FORMAT_MOD_LINEAR || mod == DRM_FORMAT_MOD_INVALID) return 1;
    for (unsigned i = 0; i < a->num_modifiers; i++) {
        if (a->supported_modifiers[i] == mod) return 1;
    }
    return 0;
}

static void handle_incoming_buffer(presenter_app *a) {
    aaas_v2_msg m;
    int fds[AAAS_V2_MAX_FDS];
    unsigned nfds = 0;
    int r = aaas_v2_recv(a->sock, &m, fds, &nfds);
    if (r <= 0) {
        a->closed = 1;
        log_presenter_event(r < 0 ? "invalid_message" : "producer_disconnect", a->gen, 0, NULL);
        return;
    }

    if (m.type == AAAS_V2_HELLO) {
        a->copy_complete_enabled =
            (m.flags & AAAS_V2_FLAG_COPY_COMPLETE) != 0 && a->gbm != NULL;
        aaas_v2_msg resp = {
            .magic = AAAS_V2_MAGIC,
            .version = AAAS_V2_VERSION,
            .type = AAAS_V2_RESIZE,
            .flags = a->copy_complete_enabled ? AAAS_V2_FLAG_COPY_COMPLETE : 0,
            .generation = a->gen ? a->gen : 1,
            .width = a->w ? a->w : 1280,
            .height = a->h ? a->h : 720,
        };
        aaas_v2_send(a->sock, &resp, NULL, 0);
        log_presenter_event("producer_hello_ack", resp.generation, 0, NULL);
        return;
    }

    bool format_ok = (m.format == DRM_FORMAT_XRGB8888 || m.format == DRM_FORMAT_ARGB8888 ||
                      m.format == DRM_FORMAT_RGBA8888 || m.format == DRM_FORMAT_ABGR8888);
    if (!a->configured && a->w && a->h) {
        a->configured = 1;
    }
    if (a->gen == 0 && m.generation > 0) {
        a->gen = m.generation;
    }

    bool gen_ok = (m.generation == a->gen || a->gen == 0 || m.generation == 0 ||
                   (m.width == a->w && m.height == a->h && m.generation <= a->gen));
    bool dim_ok = (m.width == a->w && m.height == a->h);

    if (m.type != AAAS_V2_BUFFER || !format_ok || !gen_ok || !dim_ok ||
        !modifier_supported(a, m.modifier)) {
        for (unsigned i = 0; i < nfds; i++) close(fds[i]);
        a->rejected++;
        log_presenter_event("rejected_stale_or_format", m.generation, m.id, NULL);
        return;
    }

    check_release_timelines(a);

    a->display_w = m.width;
    a->display_h = m.height;

    // Find available slot
    presenter_slot *s = NULL;
    for (int i = 0; i < MAX_SLOTS; i++) {
        if (a->slots[i].active && a->slots[i].gen == m.generation && a->slots[i].id == m.id) {
            for (unsigned j = 0; j < nfds; j++) close(fds[j]);
            a->rejected++;
            log_presenter_event("duplicate_inflight_buffer", m.generation, m.id, NULL);
            return;
        }
        if (!a->slots[i].active && !s) {
            s = &a->slots[i];
        }
    }
    if (!s) {
        for (unsigned j = 0; j < nfds; j++) close(fds[j]);
        a->rejected++;
        log_presenter_event("slot_registry_exhausted", m.generation, m.id, NULL);
        return;
    }

    int dma_fd = fds[0];
    int acquire_fence_fd = (m.flags & AAAS_V2_FLAG_EXPLICIT_SYNC && nfds > 1) ? fds[1] : -1;

    if ((m.flags & AAAS_V2_FLAG_EXPLICIT_SYNC) &&
        (acquire_fence_fd < 0 || !sync_file_is_valid(acquire_fence_fd))) {
        for (unsigned i = 0; i < nfds; i++) close(fds[i]);
        a->rejected++;
        log_presenter_event("invalid_acquire_fence", m.generation, m.id, NULL);
        return;
    }

    struct gbm_bo *stage_bo = NULL;
    char link[128], path[64];
    snprintf(path, sizeof(path), "/proc/self/fd/%d", dma_fd);
    ssize_t llen = readlink(path, link, sizeof(link) - 1);
    bool is_memfd = (llen > 0 && strncmp(link, "/memfd:", 7) == 0);

    if ((is_memfd || a->copy_complete_enabled) && a->gbm) {
        if (acquire_fence_fd >= 0 && sync_file_wait(acquire_fence_fd, 2000) != 1) {
            for (unsigned i = 0; i < nfds; i++) close(fds[i]);
            a->rejected++;
            log_presenter_event("acquire_fence_timeout", m.generation, m.id, NULL);
            return;
        }
        struct timespec t0, t1;
        clock_gettime(CLOCK_MONOTONIC, &t0);

        uint64_t src_size64 = (uint64_t)m.stride[0] * m.height;
        bool source_sync_started = false;
        bool copied = false;
        void *src_map = MAP_FAILED;
        uint32_t stage_stride = 0;
        uint32_t map_stride = 0;
        void *map_data = NULL;
        void *dst_map = NULL;
        if (m.stride[0] >= m.width * 4 && src_size64 > 0 &&
            src_size64 <= SIZE_MAX) {
            stage_bo = gbm_bo_create(a->gbm, m.width, m.height, m.format,
                                     GBM_BO_USE_LINEAR);
            if (stage_bo) {
                stage_stride = gbm_bo_get_stride(stage_bo);
                if (is_memfd) {
                    source_sync_started = true;
                } else {
                    struct dma_buf_sync sync = {
                        .flags = DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ,
                    };
                    source_sync_started = ioctl(dma_fd, DMA_BUF_IOCTL_SYNC,
                                                &sync) == 0;
                }
                if (source_sync_started) {
                    src_map = mmap(NULL, (size_t)src_size64, PROT_READ,
                                   MAP_SHARED, dma_fd, 0);
                }
                if (src_map != MAP_FAILED) {
                    dst_map = gbm_bo_map(stage_bo, 0, 0, m.width, m.height,
                                         GBM_BO_TRANSFER_WRITE,
                                         &map_stride, &map_data);
                    if (dst_map && map_stride >= m.width * 4) {
                        for (uint32_t y = 0; y < m.height; y++) {
                            memcpy((char*)dst_map + (size_t)y * map_stride,
                                   (char*)src_map + (size_t)y * m.stride[0],
                                   (size_t)m.width * 4);
                        }
                        copied = true;
                    }
                    if (dst_map) gbm_bo_unmap(stage_bo, map_data);
                    munmap(src_map, (size_t)src_size64);
                }
                if (!is_memfd && source_sync_started) {
                    struct dma_buf_sync sync = {
                        .flags = DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ,
                    };
                    if (ioctl(dma_fd, DMA_BUF_IOCTL_SYNC, &sync) != 0) {
                        copied = false;
                    }
                }
            }
        }

        int stage_fd = copied ? gbm_bo_get_fd(stage_bo) : -1;
        if (stage_fd >= 0) {
            close(dma_fd);
            dma_fd = stage_fd;
            m.stride[0] = stage_stride;
            m.modifier = gbm_bo_get_modifier(stage_bo);
            if (acquire_fence_fd >= 0) {
                close(acquire_fence_fd);
                acquire_fence_fd = -1;
                m.flags &= ~AAAS_V2_FLAG_EXPLICIT_SYNC;
            }

            clock_gettime(CLOCK_MONOTONIC, &t1);
            int64_t copy_ns =
                ((int64_t)t1.tv_sec - (int64_t)t0.tv_sec) * 1000000000LL +
                ((int64_t)t1.tv_nsec - (int64_t)t0.tv_nsec);
            uint64_t copy_us = copy_ns > 0 ? (uint64_t)copy_ns / 1000ULL : 0;
            char copy_json[128];
            snprintf(copy_json, sizeof(copy_json),
                     "\"fallback\":\"cpu_staging_copy\",\"overhead_us\":%llu",
                     (unsigned long long)copy_us);
            log_presenter_event("staging_copy", m.generation, m.id, copy_json);

            if (a->copy_complete_enabled) {
                aaas_v2_msg copied_msg = {
                    .magic = AAAS_V2_MAGIC,
                    .version = AAAS_V2_VERSION,
                    .type = AAAS_V2_COPY_COMPLETE,
                    .generation = m.generation,
                    .id = m.id,
                };
                if (aaas_v2_send(a->sock, &copied_msg, NULL, 0) != 0) {
                    close(dma_fd);
                    gbm_bo_destroy(stage_bo);
                    a->closed = 1;
                    a->rejected++;
                    log_presenter_event("copy_complete_send_failed", m.generation,
                                        m.id, NULL);
                    return;
                }
                log_presenter_event("source_copy_complete", m.generation, m.id, NULL);
            }
        } else {
            if (stage_bo) {
                gbm_bo_destroy(stage_bo);
                stage_bo = NULL;
            }
            char copy_json[96];
            snprintf(copy_json, sizeof(copy_json), "\"errno\":%d", errno);
            log_presenter_event("staging_copy_unavailable", m.generation, m.id,
                                copy_json);
        }
    }

    // Import DMA-BUF into Wayland wl_buffer
    struct zwp_linux_buffer_params_v1 *params =
        zwp_linux_dmabuf_v1_create_params(a->dmabuf);
    zwp_linux_buffer_params_v1_add(params, dma_fd, 0, m.offset[0], m.stride[0],
                                   (uint32_t)(m.modifier >> 32), (uint32_t)m.modifier);
    // Optional diagnostic capture. Keep production presentation free of the
    // synchronous readback and disk writes performed by this probe.
    const char *frame_dump_dir = getenv("AAAS_FRAME_DUMP_DIR");
    const char *frame_dump_every = getenv("AAAS_FRAME_DUMP_EVERY");
    unsigned dump_every = frame_dump_every ? (unsigned)strtoul(frame_dump_every, NULL, 10) : 1;
    if (frame_dump_dir && frame_dump_dir[0] && dump_every && m.id % dump_every == 0) {
        if (acquire_fence_fd >= 0 && sync_file_wait(acquire_fence_fd, 2000) != 1) {
            close(dma_fd);
            close(acquire_fence_fd);
            if (stage_bo) gbm_bo_destroy(stage_bo);
            zwp_linux_buffer_params_v1_destroy(params);
            a->rejected++;
            log_presenter_event("capture_acquire_timeout", m.generation, m.id, NULL);
            return;
        }
        size_t map_sz = (size_t)m.stride[0] * m.height;
        void *map_ptr = mmap(NULL, map_sz, PROT_READ, MAP_SHARED, dma_fd, 0);
        if (map_ptr != MAP_FAILED) {
            char ppm_path[256];
            snprintf(ppm_path, sizeof(ppm_path), "%s/frame_%u.ppm", frame_dump_dir, m.id);
            FILE *fp = fopen(ppm_path, "wb");
            if (fp) {
                fprintf(fp, "P6\n%u %u\n255\n", m.width, m.height);
                const uint8_t *src = (const uint8_t*)map_ptr;
                for (uint32_t y = 0; y < m.height; y++) {
                    const uint8_t *row = src + y * m.stride[0];
                    for (uint32_t x = 0; x < m.width; x++) {
                        uint8_t r = row[x * 4 + 0];
                        uint8_t g = row[x * 4 + 1];
                        uint8_t b = row[x * 4 + 2];
                        fputc(r, fp);
                        fputc(g, fp);
                        fputc(b, fp);
                    }
                }
                fclose(fp);
                fprintf(stderr, "[AaaS Presenter] Dumped frame %u to %s\n", m.id, ppm_path);
            }
            munmap(map_ptr, map_sz);
        }
    }

    /* Opt-in alpha-plane probe for diagnosing transparent/partial client
     * targets. It is disabled in normal runs and does not write frame data. */
    const char *alpha_trace = getenv("AAAS_FRAME_ALPHA_TRACE");
    if (alpha_trace && alpha_trace[0] == '1') {
        if (acquire_fence_fd >= 0 && sync_file_wait(acquire_fence_fd, 2000) != 1) {
            close(dma_fd);
            close(acquire_fence_fd);
            if (stage_bo) gbm_bo_destroy(stage_bo);
            zwp_linux_buffer_params_v1_destroy(params);
            a->rejected++;
            log_presenter_event("alpha_trace_acquire_timeout", m.generation, m.id, NULL);
            return;
        }
        size_t map_sz = (size_t)m.stride[0] * m.height;
        const uint8_t *map_ptr = mmap(NULL, map_sz, PROT_READ, MAP_SHARED, dma_fd, 0);
        if (map_ptr != MAP_FAILED) {
            uint8_t alpha_min = 255, alpha_max = 0;
            uint64_t alpha_zero = 0, alpha_partial = 0;
            for (uint32_t y = 0; y < m.height; y++) {
                const uint8_t *row = map_ptr + (size_t)y * m.stride[0];
                for (uint32_t x = 0; x < m.width; x++) {
                    uint8_t alpha = row[(size_t)x * 4 + 3];
                    if (alpha < alpha_min) alpha_min = alpha;
                    if (alpha > alpha_max) alpha_max = alpha;
                    if (alpha == 0) alpha_zero++;
                    else if (alpha != 255) alpha_partial++;
                }
            }
            char alpha_json[224];
            snprintf(alpha_json, sizeof(alpha_json),
                     "\"width\":%u,\"height\":%u,\"stride_bytes\":%u,"
                     "\"format\":%u,\"alpha_min\":%u,\"alpha_max\":%u,"
                     "\"alpha_zero_pixels\":%llu,\"alpha_partial_pixels\":%llu",
                     m.width, m.height, m.stride[0], m.format, alpha_min, alpha_max,
                     (unsigned long long)alpha_zero, (unsigned long long)alpha_partial);
            log_presenter_event("frame_alpha", m.generation, m.id, alpha_json);
            munmap((void *)map_ptr, map_sz);
        } else {
            char alpha_json[64];
            snprintf(alpha_json, sizeof(alpha_json), "\"errno\":%d", errno);
            log_presenter_event("frame_alpha_map_failed", m.generation, m.id,
                                alpha_json);
        }
    }

    close(dma_fd);

    struct wl_buffer *wl_buf =
        zwp_linux_buffer_params_v1_create_immed(params, m.width, m.height, m.format, 0);
    zwp_linux_buffer_params_v1_destroy(params);

    if (!wl_buf) {
        if (acquire_fence_fd >= 0) close(acquire_fence_fd);
        if (stage_bo) gbm_bo_destroy(stage_bo);
        a->rejected++;
        log_presenter_event("dmabuf_import_failed", m.generation, m.id, NULL);
        return;
    }

    s->wl = wl_buf;
    s->app = a;
    s->id = m.id;
    s->gen = m.generation;
    s->active = 1;
    s->explicit_sync_used = false;
    s->staging_bo = stage_bo;
    wl_buffer_add_listener(wl_buf, &buffer_listener, s);
    a->imported++;

    // Explicit synchronization using linux-drm-syncobj-v1
    if (a->syncobj_surface && a->acquire_timeline) {
        // 1. Advance acquire timeline point
        a->acquire_point++;
        if (acquire_fence_fd >= 0) {
            syncobj_timeline_import_sync_file(a->drm_fd, a->acquire_timeline_handle,
                                              a->acquire_point, acquire_fence_fd);
            close(acquire_fence_fd);
            acquire_fence_fd = -1;
        } else {
            // Buffer submitted without fence: immediately signal acquire point to satisfy protocol
            syncobj_timeline_signal(a->drm_fd, a->acquire_timeline_handle, a->acquire_point);
        }

        wp_linux_drm_syncobj_surface_v1_set_acquire_point(
            a->syncobj_surface, a->acquire_timeline,
            (uint32_t)(a->acquire_point >> 32), (uint32_t)a->acquire_point);

        // 2. Initialize per-slot release timeline if needed
        if (!s->release_timeline_handle) {
            syncobj_create_timeline(a->drm_fd, &s->release_timeline_handle);
            int release_fd = -1;
            syncobj_handle_to_fd(a->drm_fd, s->release_timeline_handle, &release_fd);
            s->release_timeline =
                wp_linux_drm_syncobj_manager_v1_import_timeline(a->syncobj_mgr, release_fd);
            close(release_fd);
            s->release_point = 0;
        }

        // 3. Advance slot release point and set on surface
        s->release_point++;
        wp_linux_drm_syncobj_surface_v1_set_release_point(
            a->syncobj_surface, s->release_timeline,
            (uint32_t)(s->release_point >> 32), (uint32_t)s->release_point);

        s->explicit_sync_used = true;
        a->explicit_sync_frames++;
    } else if (acquire_fence_fd >= 0) {
        close(acquire_fence_fd);
    }

    // Attach, damage, and commit
    wl_surface_attach(a->surface, wl_buf, 0, 0);
    wl_surface_damage_buffer(a->surface, 0, 0, m.width, m.height);

    if (a->presentation) {
        struct wp_presentation_feedback *fb =
            wp_presentation_feedback(a->presentation, a->surface);
        wp_presentation_feedback_add_listener(fb, &pres_feedback_listener, a);
    }

    wl_surface_commit(a->surface);
    a->submitted++;

    char extra[128];
    snprintf(extra, sizeof(extra),
             "\"explicit_sync\":%s,\"acquire_point\":%llu,\"release_point\":%llu",
             s->explicit_sync_used ? "true" : "false",
             (unsigned long long)a->acquire_point,
             (unsigned long long)s->release_point);
    log_presenter_event("frame_committed", m.generation, m.id, extra);
}

static void input_adapter_accept(presenter_app *a) {
    int fd = accept4(a->input_listen_fd, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
    if (fd < 0) {
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
            char extra[64];
            snprintf(extra, sizeof(extra), "\"errno\":%d", errno);
            log_presenter_event("input_accept_failed", a->gen, 0, extra);
        }
        return;
    }
    if (a->input_fd >= 0) {
        close(a->input_fd);
        a->input_fd = -1;
        log_presenter_event("input_adapter_replaced", a->gen, 0, NULL);
    }
    a->input_fd = fd;
    a->keyboard_v2_enabled=0;
    a->keyboard_queue_head=0; a->keyboard_queue_count=0;
    a->input_sequence = 0;
    a->input_dropped = 0;
    log_presenter_event("input_adapter_connected", a->gen, 0, NULL);
    input_send_hello(a);
    if (a->content_focus) {
        /* The adapter may have connected after the pointer entered. */
        input_send_packet(a, AAAS_INPUT_FOCUS, a->last_input_x, a->last_input_y,
                          0, AAAS_INPUT_FOCUS_ENTER, 0, 0);
    }
}

static void input_adapter_read(presenter_app *a) {
    aaas_input_msg wire;
    ssize_t n = recv(a->input_fd, &wire, sizeof(wire), MSG_TRUNC);
    if (n <= 0) {
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            return;
        }
        log_presenter_event(n < 0 ? "input_adapter_error" : "input_adapter_disconnect",
                            a->gen, 0, NULL);
        close(a->input_fd);
        a->input_fd = -1;
        a->keyboard_v2_enabled=0;
        a->keyboard_queue_head=0; a->keyboard_queue_count=0;
        return;
    }
    if (n != (ssize_t)sizeof(wire)) {
        char extra[64];
        snprintf(extra, sizeof(extra), "\"length\":%ld", (long)n);
        log_presenter_event("input_invalid_adapter_message", a->gen, 0, extra);
        return;
    }
    aaas_input_msg host;
    aaas_input_from_wire(&host, &wire);
    char why[64] = {0};
    if (aaas_input_validate(&host, a->input_session_id, 0, why, sizeof(why)) != 0) {
        char extra[128];
        snprintf(extra, sizeof(extra), "\"reason\":\"%s\"", why);
        log_presenter_event("input_invalid_adapter_message", a->gen, 0, extra);
        return;
    }
    if (host.type == AAAS_INPUT_HELLO && (host.flags & AAAS_INPUT_FLAG_ACK)) {
        a->keyboard_v2_enabled = (host.flags & AAAS_INPUT_FLAG_KEYBOARD_V2) != 0;
        char extra[64];
        snprintf(extra,sizeof(extra),"\"keyboard_v2\":%s",a->keyboard_v2_enabled?"true":"false");
        log_presenter_event("input_adapter_ready", a->gen, 0, extra);
        if (a->keyboard_v2_enabled && a->keyboard_focus)
            keyboard_send_focus(a, AAAS_INPUT_FOCUS_ENTER);
    } else {
        log_presenter_event("input_adapter_message", a->gen, host.sequence, NULL);
    }
}

static void input_teardown(presenter_app *a) {
    if (a->keyboard_focus) keyboard_send_focus(a, AAAS_INPUT_FOCUS_LEAVE);
    input_keyboard_flush(a);
    if (a->pressed_buttons) {
        input_release_buttons(a, "teardown");
    }
    if (a->content_focus) {
        input_focus_leave(a, a->last_input_x, a->last_input_y);
    }
    if (a->input_fd >= 0) {
        input_send_packet(a, AAAS_INPUT_SHUTDOWN, a->last_input_x, a->last_input_y,
                          0, 0, 0, 0);
        close(a->input_fd);
        a->input_fd = -1;
        a->keyboard_v2_enabled=0;
        a->keyboard_queue_head=0; a->keyboard_queue_count=0;
    }
    if (a->xkb_state) xkb_state_unref(a->xkb_state);
    if (a->xkb_keymap) xkb_keymap_unref(a->xkb_keymap);
    if (a->xkb_context) xkb_context_unref(a->xkb_context);
}

int aaas_run_gpu_presenter(const aaas_presenter_config *config) {
    presenter_app app = {
        .sock = config->sock,
        .w = config->initial_width ? config->initial_width : 640,
        .h = config->initial_height ? config->initial_height : 480,
        .input_listen_fd = config->input_listen_fd,
        .input_fd = -1,
        .input_session_id = config->input_session_id,
        .repeat_key = UINT32_MAX,
    };

    app.display = wl_display_connect(NULL);
    if (!app.display) {
        perror("wl_display_connect");
        return 2;
    }

    app.registry = wl_display_get_registry(app.display);
    wl_registry_add_listener(app.registry, &registry_listener, &app);
    if (wl_display_roundtrip(app.display) < 0 || !app.compositor || !app.wm_base || !app.dmabuf) {
        fprintf(stderr, "Required Wayland globals missing\n");
        wl_display_disconnect(app.display);
        return 2;
    }

    zwp_linux_dmabuf_v1_add_listener(app.dmabuf, &dmabuf_listener, &app);
    xdg_wm_base_add_listener(app.wm_base, &wm_base_listener, &app);
    wl_display_roundtrip(app.display);

    if (!app.num_modifiers) {
        fprintf(stderr, "No DRM XRGB8888 modifiers advertised by compositor\n");
        return 2;
    }

    // Open DRM device for syncobjs if syncobj_mgr is advertised
    const char *node = config->drm_node ? config->drm_node : "/dev/dri/renderD129";
    app.drm_fd = open(node, O_RDWR | O_CLOEXEC);
    if (app.drm_fd < 0) {
        node = "/dev/dri/renderD128";
        app.drm_fd = open(node, O_RDWR | O_CLOEXEC);
    }
    if (app.drm_fd >= 0) {
        app.gbm = gbm_create_device(app.drm_fd);
    }

    bool explicit_sync_available = (app.syncobj_mgr != NULL && app.drm_fd >= 0 && !config->force_implicit_sync);
    char cap_extra[128];
    snprintf(cap_extra, sizeof(cap_extra),
             "\"explicit_sync_capable\":%s,\"modifiers_count\":%u",
             explicit_sync_available ? "true" : "false", app.num_modifiers);
    log_presenter_event("capabilities", 0, 0, cap_extra);

    app.surface = wl_compositor_create_surface(app.compositor);
    app.xdg_surf = xdg_wm_base_get_xdg_surface(app.wm_base, app.surface);
    xdg_surface_add_listener(app.xdg_surf, &xdg_surf_listener, &app);
    app.toplevel = xdg_surface_get_toplevel(app.xdg_surf);
    xdg_toplevel_add_listener(app.toplevel, &toplevel_listener, &app);
    xdg_toplevel_set_title(app.toplevel, config->title ? config->title : "AaaS M1A.1 GPU Presenter");

    // Initialize explicit sync surface and acquire timeline
    if (explicit_sync_available) {
        app.syncobj_surface =
            wp_linux_drm_syncobj_manager_v1_get_surface(app.syncobj_mgr, app.surface);

        syncobj_create_timeline(app.drm_fd, &app.acquire_timeline_handle);
        int acq_fd = -1;
        syncobj_handle_to_fd(app.drm_fd, app.acquire_timeline_handle, &acq_fd);
        app.acquire_timeline =
            wp_linux_drm_syncobj_manager_v1_import_timeline(app.syncobj_mgr, acq_fd);
        close(acq_fd);
        app.acquire_point = 0;
    }

    wl_surface_commit(app.surface);
    wl_display_roundtrip(app.display);

    // Event loop
    while (!app.closed && (!config->running || *config->running)) {
        if (config->max_frames > 0 && app.submitted >= config->max_frames) {
            break;
        }

        while (wl_display_prepare_read(app.display) != 0) {
            if (wl_display_dispatch_pending(app.display) < 0) {
                log_presenter_event("compositor_disconnect", app.gen, 0, NULL);
                app.closed = 1;
                break;
            }
        }
        if (app.closed) break;

        if (wl_display_flush(app.display) < 0 && errno != EAGAIN) {
            wl_display_cancel_read(app.display);
            log_presenter_event("compositor_disconnect", app.gen, 0, NULL);
            break;
        }

        struct pollfd p[4] = {
            { .fd = wl_display_get_fd(app.display), .events = POLLIN },
            { .fd = app.sock, .events = POLLIN },
        };
        nfds_t nfds = 2;
        int input_listen_idx = -1;
        int input_idx = -1;
        if (app.input_listen_fd >= 0) {
            input_listen_idx = (int)nfds;
            p[nfds].fd = app.input_listen_fd;
            p[nfds].events = POLLIN;
            nfds++;
        }
        if (app.input_fd >= 0) {
            input_idx = (int)nfds;
            p[nfds].fd = app.input_fd;
            p[nfds].events = POLLIN;
            if (app.input_queue_count > 0 || app.keyboard_queue_count > 0) {
                p[nfds].events |= POLLOUT;
            }
            nfds++;
        }

        int timeout_ms=200;
        if(app.keyboard_repeat_rate && app.repeat_key<768 && app.repeat_next_ns) {
            uint64_t now=monotonic_ns();
            int due=now>=app.repeat_next_ns?0:(int)((app.repeat_next_ns-now+999999ULL)/1000000ULL);
            if(due<timeout_ms) timeout_ms=due;
        }
        int r = poll(p, nfds, timeout_ms);
        if (r < 0) {
            wl_display_cancel_read(app.display);
            if (errno == EINTR) continue;
            break;
        }

        if (p[0].revents & POLLIN) {
            if (wl_display_read_events(app.display) < 0) {
                log_presenter_event("compositor_disconnect", app.gen, 0, NULL);
                break;
            }
            wl_display_dispatch_pending(app.display);
        } else {
            wl_display_cancel_read(app.display);
        }

        if (p[0].revents & (POLLHUP | POLLERR)) {
            log_presenter_event("compositor_disconnect", app.gen, 0, NULL);
            break;
        }

        if (input_idx >= 0 && (p[input_idx].revents & POLLIN)) {
            input_adapter_read(&app);
        }
        if (input_idx >= 0 && app.input_fd >= 0 &&
            (p[input_idx].revents & POLLOUT)) {
            input_queue_flush(&app);
            input_keyboard_flush(&app);
        }
        if (input_idx >= 0 && app.input_fd >= 0 &&
            (p[input_idx].revents & (POLLHUP | POLLERR))) {
            log_presenter_event("input_adapter_disconnect", app.gen, 0, NULL);
            close(app.input_fd);
            app.input_fd = -1;
            app.keyboard_v2_enabled=0;
            app.keyboard_queue_head=0; app.keyboard_queue_count=0;
        }
        keyboard_repeat_tick(&app);
        if (input_listen_idx >= 0 && (p[input_listen_idx].revents & POLLIN)) {
            input_adapter_accept(&app);
        }

        check_release_timelines(&app);

        if (p[1].revents & POLLIN) {
            handle_incoming_buffer(&app);
        }
        if (p[1].revents & (POLLHUP | POLLERR)) {
            log_presenter_event("producer_disconnect", app.gen, 0, NULL);
            break;
        }
    }

    input_teardown(&app);

    // Teardown notification
    aaas_v2_msg close_msg = {
        .magic = AAAS_V2_MAGIC,
        .version = AAAS_V2_VERSION,
        .type = AAAS_V2_CLOSE,
        .generation = app.gen,
    };
    aaas_v2_send(app.sock, &close_msg, NULL, 0);

    struct rusage usage;
    getrusage(RUSAGE_SELF, &usage);
    char summary_extra[320];
    snprintf(summary_extra, sizeof(summary_extra),
             "\"imports\":%llu,\"submissions\":%llu,\"releases\":%llu,\"rejected\":%llu,"
             "\"presented\":%llu,\"discarded\":%llu,\"explicit_sync_frames\":%llu,"
             "\"input_sent\":%llu,\"input_dropped\":%llu,"
             "\"maxrss_kib\":%ld,\"user_us\":%ld,\"system_us\":%ld",
             (unsigned long long)app.imported, (unsigned long long)app.submitted,
             (unsigned long long)app.released, (unsigned long long)app.rejected,
             (unsigned long long)app.presented, (unsigned long long)app.discarded,
             (unsigned long long)app.explicit_sync_frames,
             (unsigned long long)app.input_sent,
             (unsigned long long)app.input_dropped,
             usage.ru_maxrss,
             usage.ru_utime.tv_sec * 1000000L + usage.ru_utime.tv_usec,
             usage.ru_stime.tv_sec * 1000000L + usage.ru_stime.tv_usec);
    log_presenter_event("summary", app.gen, 0, summary_extra);

    // Cleanup buffer slots and syncobjs
    for (int i = 0; i < MAX_SLOTS; i++) {
        if (app.slots[i].wl) wl_buffer_destroy(app.slots[i].wl);
        if (app.slots[i].release_timeline) {
            wp_linux_drm_syncobj_timeline_v1_destroy(app.slots[i].release_timeline);
        }
        if (app.slots[i].release_timeline_handle && app.drm_fd >= 0) {
            syncobj_destroy(app.drm_fd, app.slots[i].release_timeline_handle);
        }
    }

    if (app.acquire_timeline) {
        wp_linux_drm_syncobj_timeline_v1_destroy(app.acquire_timeline);
    }
    if (app.acquire_timeline_handle && app.drm_fd >= 0) {
        syncobj_destroy(app.drm_fd, app.acquire_timeline_handle);
    }
    if (app.syncobj_surface) {
        wp_linux_drm_syncobj_surface_v1_destroy(app.syncobj_surface);
    }
    if (app.syncobj_mgr) {
        wp_linux_drm_syncobj_manager_v1_destroy(app.syncobj_mgr);
    }
    if (app.gbm) {
        gbm_device_destroy(app.gbm);
    }
    if (app.drm_fd >= 0) {
        close(app.drm_fd);
    }

    if (app.pointer) {
        destroy_pointer(&app);
    }
    if (app.seat) {
        if (wl_proxy_get_version((struct wl_proxy *)app.seat) >=
            WL_SEAT_RELEASE_SINCE_VERSION) {
            wl_seat_release(app.seat);
        } else {
            wl_seat_destroy(app.seat);
        }
        app.seat = NULL;
    }

    xdg_toplevel_destroy(app.toplevel);
    xdg_surface_destroy(app.xdg_surf);
    wl_surface_destroy(app.surface);
    zwp_linux_dmabuf_v1_destroy(app.dmabuf);
    if (app.presentation) wp_presentation_destroy(app.presentation);
    xdg_wm_base_destroy(app.wm_base);
    wl_compositor_destroy(app.compositor);
    wl_registry_destroy(app.registry);
    wl_display_disconnect(app.display);

    return (app.imported > 0 && app.released > 0) ? 0 : 1;
}
