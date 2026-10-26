#include "gpu_presenter.h"
#include "wire_v2.h"
#include "sync_util.h"

#include "xdg-shell-client-protocol.h"
#include "linux-dmabuf-client-protocol.h"
#include "presentation-time-client-protocol.h"
#include "linux-drm-syncobj-client-protocol.h"

#include <wayland-client.h>
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

#define MAX_SLOTS 32

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
    }
}

static void registry_global_remove(void *data, struct wl_registry *r, uint32_t n) {
    (void)data; (void)r; (void)n;
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

static void xdg_surface_configure(void *data, struct xdg_surface *xs, uint32_t serial) {
    presenter_app *a = data;
    xdg_surface_ack_configure(xs, serial);
    uint32_t prev_w = a->w;
    uint32_t prev_h = a->h;
    uint32_t w = a->w ? a->w : 640;
    uint32_t h = a->h ? a->h : 480;
    if (w > 1920) w = 1920;
    if (h > 1080) h = 1080;
    a->w = w;
    a->h = h;

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

static void buffer_released(void *data, struct wl_buffer *buf) {
    presenter_slot *s = data;
    presenter_app *a = s->app;

    int release_fence_fd = -1;
    uint32_t flags = 0;

    if (s->explicit_sync_used && s->release_timeline_handle) {
        // Export release point from the slot's timeline to a sync_file FD!
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

    char extra[64];
    snprintf(extra, sizeof(extra), "\"fence\":%s,\"point\":%llu",
             (flags & AAAS_V2_FLAG_RELEASE_FENCE) ? "\"exported\"" : "\"none\"",
             (unsigned long long)s->release_point);
    log_presenter_event("buffer_release", s->gen, s->id, extra);

    a->released++;
    wl_buffer_destroy(buf);
    if (s->staging_bo) {
        gbm_bo_destroy(s->staging_bo);
        s->staging_bo = NULL;
    }
    s->wl = NULL;
    s->active = 0;
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
                buffer_released(s, s->wl);
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
        aaas_v2_msg resp = {
            .magic = AAAS_V2_MAGIC,
            .version = AAAS_V2_VERSION,
            .type = AAAS_V2_RESIZE,
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

    if (is_memfd && a->gbm) {
        if (acquire_fence_fd >= 0 && sync_file_wait(acquire_fence_fd, 2000) != 1) {
            for (unsigned i = 0; i < nfds; i++) close(fds[i]);
            a->rejected++;
            log_presenter_event("acquire_fence_timeout", m.generation, m.id, NULL);
            return;
        }
        struct timespec t0, t1;
        clock_gettime(CLOCK_MONOTONIC, &t0);

        stage_bo = gbm_bo_create(a->gbm, m.width, m.height, m.format, GBM_BO_USE_LINEAR);
        if (stage_bo) {
            uint32_t stage_stride = gbm_bo_get_stride(stage_bo);
            size_t src_size = (size_t)m.stride[0] * m.height;
            void *src_map = mmap(NULL, src_size, PROT_READ, MAP_SHARED, dma_fd, 0);
            if (src_map != MAP_FAILED) {
                uint32_t map_stride = 0;
                void *map_data = NULL;
                void *dst_map = gbm_bo_map(stage_bo, 0, 0, m.width, m.height,
                                           GBM_BO_TRANSFER_WRITE, &map_stride, &map_data);
                if (dst_map) {
                    for (uint32_t y = 0; y < m.height; y++) {
                        memcpy((char*)dst_map + y * map_stride,
                               (char*)src_map + y * m.stride[0],
                               m.width * 4);
                    }
                    gbm_bo_unmap(stage_bo, map_data);
                }
                munmap(src_map, src_size);
            }
            close(dma_fd);
            dma_fd = gbm_bo_get_fd(stage_bo);
            m.stride[0] = stage_stride;
            m.modifier = gbm_bo_get_modifier(stage_bo);

            clock_gettime(CLOCK_MONOTONIC, &t1);
            uint64_t copy_us = ((uint64_t)(t1.tv_sec - t0.tv_sec) * 1000000ULL +
                                (t1.tv_nsec - t0.tv_nsec) / 1000ULL);
            char copy_json[128];
            snprintf(copy_json, sizeof(copy_json),
                     "\"fallback\":\"cpu_staging_copy\",\"overhead_us\":%llu",
                     (unsigned long long)copy_us);
            log_presenter_event("staging_copy", m.generation, m.id, copy_json);
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

int aaas_run_gpu_presenter(const aaas_presenter_config *config) {
    presenter_app app = {
        .sock = config->sock,
        .w = config->initial_width ? config->initial_width : 640,
        .h = config->initial_height ? config->initial_height : 480,
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
    while (!app.closed) {
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

        struct pollfd p[2] = {
            { .fd = wl_display_get_fd(app.display), .events = POLLIN },
            { .fd = app.sock, .events = POLLIN }
        };
        int r = poll(p, 2, 200);
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

        check_release_timelines(&app);

        if (p[1].revents & POLLIN) {
            handle_incoming_buffer(&app);
        }
        if (p[1].revents & (POLLHUP | POLLERR)) {
            log_presenter_event("producer_disconnect", app.gen, 0, NULL);
            break;
        }
    }

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
    char summary_extra[256];
    snprintf(summary_extra, sizeof(summary_extra),
             "\"imports\":%llu,\"submissions\":%llu,\"releases\":%llu,\"rejected\":%llu,"
             "\"presented\":%llu,\"discarded\":%llu,\"explicit_sync_frames\":%llu,"
             "\"maxrss_kib\":%ld,\"user_us\":%ld,\"system_us\":%ld",
             (unsigned long long)app.imported, (unsigned long long)app.submitted,
             (unsigned long long)app.released, (unsigned long long)app.rejected,
             (unsigned long long)app.presented, (unsigned long long)app.discarded,
             (unsigned long long)app.explicit_sync_frames,
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
