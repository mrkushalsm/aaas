#include "ext-data-control-v1-client-protocol.h"

#include <errno.h>
#include <dirent.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/inotify.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>

#define MAX_TEXT (64u * 1024u)
#define FRAME_HEADER "AASCLIP1\n"
#define MIME_UTF8 "text/plain;charset=utf-8"
#define MIME_TEXT "text/plain"
#define MIME_UTF8_STRING "UTF8_STRING"

struct bridge {
    struct wl_display *display;
    struct wl_registry *registry;
    struct wl_seat *seat;
    struct ext_data_control_manager_v1 *manager;
    struct ext_data_control_device_v1 *device;
    struct ext_data_control_offer_v1 *offer;
    struct ext_data_control_source_v1 *source;
    char **offer_mimes;
    size_t offer_mime_count;
    char *ipc_dir;
    char *host_file;
    char *request_file;
    uid_t android_uid;
    uint64_t generation;
    char *active_text;
    size_t active_length;
    char *last_local_text;
    size_t last_local_length;
    bool last_local_known;
    bool last_local_clear;
    int inotify_fd;
    int watch_id;
    bool ready;
    bool failed;
};

static volatile sig_atomic_t running = 1;

static void stop_signal(int signal_number) {
    (void)signal_number;
    running = 0;
}

static bool valid_utf8(const unsigned char *s, size_t n) {
    for (size_t i = 0; i < n;) {
        unsigned char c = s[i++];
        if (c < 0x80) continue;
        unsigned need = c >= 0xc2 && c <= 0xdf ? 1 :
                        c >= 0xe0 && c <= 0xef ? 2 :
                        c >= 0xf0 && c <= 0xf4 ? 3 : 99;
        if (need == 99 || i + need > n) return false;
        unsigned char first = s[i];
        if ((c == 0xe0 && first < 0xa0) || (c == 0xed && first >= 0xa0) ||
            (c == 0xf0 && first < 0x90) || (c == 0xf4 && first >= 0x90))
            return false;
        for (unsigned j = 0; j < need; ++j)
            if ((s[i++] & 0xc0) != 0x80) return false;
    }
    return true;
}

static bool write_all(int fd, const void *buffer, size_t length) {
    const unsigned char *p = buffer;
    while (length) {
        ssize_t count = write(fd, p, length);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) return false;
        p += (size_t)count;
        length -= (size_t)count;
    }
    return true;
}

static bool write_frame(const char *path, const char *kind,
                        const void *text, size_t length) {
    char temporary[4096];
    if (snprintf(temporary, sizeof(temporary), "%s.tmp.%ld", path,
                 (long)getpid()) >= (int)sizeof(temporary)) return false;
    int fd = open(temporary, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW,
                  0600);
    if (fd < 0) return false;
    bool ok = write_all(fd, FRAME_HEADER, sizeof(FRAME_HEADER) - 1) &&
              write_all(fd, kind, 1) && write_all(fd, "\n", 1) &&
              (!length || write_all(fd, text, length)) && fsync(fd) == 0;
    int saved = errno;
    if (close(fd) != 0) ok = false;
    if (ok && rename(temporary, path) != 0) ok = false;
    if (!ok) unlink(temporary);
    errno = saved;
    return ok;
}

static bool grant_android_read(struct bridge *b) {
    char acl[64];
    if (snprintf(acl, sizeof(acl), "u:%u:r--", (unsigned)b->android_uid) >=
        (int)sizeof(acl)) return false;
    pid_t child = fork();
    if (child < 0) return false;
    if (child == 0) {
        execlp("setfacl", "setfacl", "-m", acl, b->host_file, (char *)NULL);
        _exit(127);
    }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) return false;
    }
    return WIFEXITED(status) && WEXITSTATUS(status) == 0;
}

static bool publish_request(struct bridge *b) {
    char temporary[4096];
    if (snprintf(temporary, sizeof(temporary), "%s.tmp.%ld", b->request_file,
                 (long)getpid()) >= (int)sizeof(temporary)) return false;
    int fd = open(temporary, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW,
                  0600);
    if (fd < 0) return false;
    char value[32];
    int length = snprintf(value, sizeof(value), "%llu\n",
                          (unsigned long long)++b->generation);
    bool ok = length > 0 && (size_t)length < sizeof(value) &&
              write_all(fd, value, (size_t)length) && fsync(fd) == 0;
    int saved = errno;
    if (close(fd) != 0) ok = false;
    if (ok && rename(temporary, b->request_file) != 0) ok = false;
    if (!ok) unlink(temporary);
    errno = saved;
    return ok;
}

static bool read_frame(const char *path, char **text, size_t *length, char *kind) {
    *text = NULL;
    *length = 0;
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return false;
    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size < 11 ||
        st.st_size > (off_t)(MAX_TEXT + 11)) {
        close(fd);
        return false;
    }
    size_t cap = (size_t)st.st_size;
    char *bytes = malloc(cap + 1);
    if (!bytes) { close(fd); return false; }
    size_t got = 0;
    while (got < cap) {
        ssize_t n = read(fd, bytes + got, cap - got);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        got += (size_t)n;
    }
    close(fd);
    bytes[got] = '\0';
    const size_t prefix = sizeof(FRAME_HEADER) - 1;
    if (got < prefix + 2 || memcmp(bytes, FRAME_HEADER, prefix) ||
        bytes[prefix + 1] != '\n' ||
        (bytes[prefix] != 'T' && bytes[prefix] != 'C')) {
        free(bytes);
        return false;
    }
    *kind = bytes[prefix];
    *length = got - prefix - 2;
    if (*kind == 'C' && *length != 0) { free(bytes); return false; }
    if (*length > MAX_TEXT || memchr(bytes + prefix + 2, '\0', *length) ||
        !valid_utf8((unsigned char *)bytes + prefix + 2, *length)) {
        free(bytes);
        return false;
    }
    if (*kind == 'T') {
        *text = malloc(*length + 1);
        if (!*text) { free(bytes); return false; }
        memcpy(*text, bytes + prefix + 2, *length);
        (*text)[*length] = '\0';
    }
    free(bytes);
    return true;
}

static void destroy_source(struct bridge *b) {
    if (b->source) {
        ext_data_control_source_v1_destroy(b->source);
        b->source = NULL;
    }
    free(b->active_text);
    b->active_text = NULL;
    b->active_length = 0;
}

static void source_send(void *data, struct ext_data_control_source_v1 *source,
                        const char *mime, int32_t fd) {
    (void)source;
    struct bridge *b = data;
    bool supported = !strcmp(mime, MIME_UTF8) || !strcmp(mime, MIME_TEXT) ||
                     !strcmp(mime, MIME_UTF8_STRING);
    if (supported && b->active_text)
        (void)write_all(fd, b->active_text, b->active_length);
    close(fd);
}

static void source_cancelled(void *data,
                             struct ext_data_control_source_v1 *source) {
    struct bridge *b = data;
    if (b->source == source) {
        ext_data_control_source_v1_destroy(source);
        b->source = NULL;
        free(b->active_text);
        b->active_text = NULL;
        b->active_length = 0;
    }
}

static const struct ext_data_control_source_v1_listener source_listener = {
    .send = source_send,
    .cancelled = source_cancelled,
};

static void set_current_clip(struct bridge *b, char *text, size_t length,
                             bool is_clear) {
    free(b->last_local_text);
    b->last_local_text = NULL;
    b->last_local_length = 0;
    b->last_local_known = true;
    b->last_local_clear = is_clear;
    if (!is_clear) {
        b->last_local_text = malloc(length + 1);
        if (b->last_local_text) {
            memcpy(b->last_local_text, text, length);
            b->last_local_text[length] = '\0';
            b->last_local_length = length;
        }
    }
}

static bool content_matches(struct bridge *b, const char *text,
                            size_t length, bool is_clear) {
    if (!b->last_local_known || b->last_local_clear != is_clear) return false;
    return is_clear || (b->last_local_text && length == b->last_local_length &&
                         !memcmp(text, b->last_local_text, length));
}

static void publish_android_clip(struct bridge *b, const char *path) {
    struct stat st;
    if (lstat(path, &st) != 0 || !S_ISREG(st.st_mode) || S_ISLNK(st.st_mode) ||
        st.st_nlink != 1 || st.st_uid != b->android_uid ||
        (st.st_mode & 077) != 0) {
        (void)unlink(path);
        return;
    }
    char *text = NULL;
    size_t length = 0;
    char kind = 0;
    if (!read_frame(path, &text, &length, &kind)) {
        (void)unlink(path);
        return;
    }
    if (content_matches(b, text, length, kind == 'C')) {
        free(text);
        (void)unlink(path);
        return;
    }
    if (kind == 'C') {
        ext_data_control_device_v1_set_selection(b->device, NULL);
        (void)wl_display_flush(b->display);
        destroy_source(b);
        set_current_clip(b, NULL, 0, true);
        (void)unlink(path);
        return;
    }
    struct ext_data_control_source_v1 *old_source = b->source;
    char *old_text = b->active_text;
    b->active_text = text;
    b->active_length = length;
    b->source = ext_data_control_manager_v1_create_data_source(b->manager);
    if (!b->source) {
        b->source = old_source;
        b->active_text = old_text;
        free(text);
        (void)unlink(path);
        return;
    }
    ext_data_control_source_v1_add_listener(b->source, &source_listener, b);
    ext_data_control_source_v1_offer(b->source, MIME_UTF8);
    ext_data_control_source_v1_offer(b->source, MIME_TEXT);
    ext_data_control_source_v1_offer(b->source, MIME_UTF8_STRING);
    ext_data_control_device_v1_set_selection(b->device, b->source);
    if (wl_display_flush(b->display) < 0 && errno != EAGAIN) b->failed = true;
    if (old_source) ext_data_control_source_v1_destroy(old_source);
    free(old_text);
    set_current_clip(b, text, length, false);
    (void)unlink(path);
}

static void publish_pending_android_clip(struct bridge *b) {
    DIR *directory = opendir(b->ipc_dir);
    if (!directory) return;
    char selected[4096] = {0};
    struct timespec newest = {0, 0};
    struct dirent *entry;
    while ((entry = readdir(directory)) != NULL) {
        size_t name_length = strlen(entry->d_name);
        if (strncmp(entry->d_name, "android-", 8) || name_length < 14 ||
            strcmp(entry->d_name + name_length - 6, ".frame")) continue;
        char path[4096];
        int length = snprintf(path, sizeof(path), "%s/%s", b->ipc_dir,
                              entry->d_name);
        if (length <= 0 || (size_t)length >= sizeof(path)) continue;
        struct stat st;
        if (lstat(path, &st) != 0 || !S_ISREG(st.st_mode) || S_ISLNK(st.st_mode) ||
            st.st_uid != b->android_uid || st.st_nlink != 1) continue;
        if (st.st_mtim.tv_sec > newest.tv_sec ||
            (st.st_mtim.tv_sec == newest.tv_sec && st.st_mtim.tv_nsec > newest.tv_nsec)) {
            memcpy(selected, path, (size_t)length + 1);
            newest = st.st_mtim;
        }
    }
    closedir(directory);
    if (selected[0]) publish_android_clip(b, selected);
}

static void offer_mime(void *data, struct ext_data_control_offer_v1 *offer,
                       const char *mime) {
    struct bridge *b = data;
    if (b->offer != offer) return;
    char **mimes = realloc(b->offer_mimes,
                           (b->offer_mime_count + 1) * sizeof(*mimes));
    if (!mimes) return;
    b->offer_mimes = mimes;
    b->offer_mimes[b->offer_mime_count] = strdup(mime);
    if (b->offer_mimes[b->offer_mime_count]) b->offer_mime_count++;
}

static const struct ext_data_control_offer_v1_listener offer_listener = {
    .offer = offer_mime,
};

static void data_offer(void *data, struct ext_data_control_device_v1 *device,
                       struct ext_data_control_offer_v1 *offer) {
    (void)device;
    struct bridge *b = data;
    if (b->offer) ext_data_control_offer_v1_destroy(b->offer);
    for (size_t i = 0; i < b->offer_mime_count; ++i) free(b->offer_mimes[i]);
    free(b->offer_mimes);
    b->offer_mimes = NULL;
    b->offer_mime_count = 0;
    b->offer = offer;
    ext_data_control_offer_v1_add_listener(offer, &offer_listener, b);
}

static bool offer_has(struct bridge *b, const char *mime) {
    for (size_t i = 0; i < b->offer_mime_count; ++i)
        if (!strcmp(b->offer_mimes[i], mime)) return true;
    return false;
}

static bool receive_offer(struct bridge *b) {
    const char *mime = offer_has(b, MIME_UTF8) ? MIME_UTF8 :
                       offer_has(b, MIME_TEXT) ? MIME_TEXT :
                       offer_has(b, MIME_UTF8_STRING) ? MIME_UTF8_STRING : NULL;
    if (!mime || !b->offer) {
        if (!write_frame(b->host_file, "C", NULL, 0) ||
            !grant_android_read(b) || !publish_request(b)) return false;
        set_current_clip(b, NULL, 0, true);
        return true;
    }
    int pipefd[2];
    if (pipe2(pipefd, O_CLOEXEC) != 0) return false;
    ext_data_control_offer_v1_receive(b->offer, mime, pipefd[1]);
    close(pipefd[1]);
    if (wl_display_flush(b->display) < 0 && errno != EAGAIN) {
        close(pipefd[0]);
        return false;
    }
    struct pollfd pfd = { .fd = pipefd[0], .events = POLLIN | POLLHUP };
    char *text = malloc(MAX_TEXT + 1);
    if (!text) { close(pipefd[0]); return false; }
    size_t length = 0;
    bool complete = false;
    while (length <= MAX_TEXT) {
        int ready = poll(&pfd, 1, 3000);
        if (ready <= 0) break;
        ssize_t n = read(pipefd[0], text + length, MAX_TEXT + 1 - length);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) break;
        if (n == 0) { complete = true; break; }
        length += (size_t)n;
        if (length > MAX_TEXT) break;
    }
    close(pipefd[0]);
    bool ok = complete && valid_utf8((unsigned char *)text, length);
    if (ok) {
        if (content_matches(b, text, length, length == 0)) {
            free(text);
            return true;
        }
        ok = write_frame(b->host_file, length ? "T" : "C", text, length) &&
             grant_android_read(b) && publish_request(b);
        if (ok) set_current_clip(b, text, length, length == 0);
    }
    free(text);
    return ok;
}

static void selection(void *data, struct ext_data_control_device_v1 *device,
                      struct ext_data_control_offer_v1 *offer) {
    (void)device;
    struct bridge *b = data;
    if (!offer) {
        set_current_clip(b, NULL, 0, true);
        if (!write_frame(b->host_file, "C", NULL, 0) ||
            !grant_android_read(b) || !publish_request(b))
            fprintf(stderr, "clipboard clear transfer failed\n");
        return;
    }
    if (!receive_offer(b)) fprintf(stderr, "clipboard transfer failed\n");
}

static void device_finished(void *data,
                            struct ext_data_control_device_v1 *device) {
    (void)device;
    struct bridge *b = data;
    b->failed = true;
}

static void primary_selection(void *data,
                              struct ext_data_control_device_v1 *device,
                              struct ext_data_control_offer_v1 *offer) {
    (void)data; (void)device; (void)offer;
}

static const struct ext_data_control_device_v1_listener device_listener = {
    .data_offer = data_offer,
    .selection = selection,
    .finished = device_finished,
    .primary_selection = primary_selection,
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

static void registry_global(void *data, struct wl_registry *registry,
                            uint32_t name, const char *interface,
                            uint32_t version) {
    struct bridge *b = data;
    if (!strcmp(interface, "wl_seat") && !b->seat) {
        b->seat = wl_registry_bind(registry, name, &wl_seat_interface,
                                   version < 7 ? version : 7);
        wl_seat_add_listener(b->seat, &seat_listener, b);
    } else if (!strcmp(interface, "ext_data_control_manager_v1") && !b->manager) {
        b->manager = wl_registry_bind(registry, name,
                                      &ext_data_control_manager_v1_interface, 1);
    }
}

static void registry_remove(void *data, struct wl_registry *registry,
                            uint32_t name) {
    (void)data; (void)registry; (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_global,
    .global_remove = registry_remove,
};

static void usage(const char *name) {
    fprintf(stderr, "usage: %s --ipc-dir DIR --android-uid UID\n", name);
}

int main(int argc, char **argv) {
    signal(SIGINT, stop_signal);
    signal(SIGTERM, stop_signal);
    const char *dir = NULL;
    unsigned long android_uid = 0;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--ipc-dir") && i + 1 < argc) dir = argv[++i];
        else if (!strcmp(argv[i], "--android-uid") && i + 1 < argc) {
            char *end = NULL;
            errno = 0;
            android_uid = strtoul(argv[++i], &end, 10);
            if (errno || !end || *end || android_uid < 10000 || android_uid > 65535) {
                usage(argv[0]); return 2;
            }
        }
        else if (!strcmp(argv[i], "--help")) { usage(argv[0]); return 0; }
        else { usage(argv[0]); return 2; }
    }
    if (!dir || dir[0] != '/' || !android_uid) { usage(argv[0]); return 2; }
    struct bridge b = {0};
    b.inotify_fd = -1;
    b.ipc_dir = strdup(dir);
    b.host_file = malloc(strlen(dir) + 64);
    b.request_file = malloc(strlen(dir) + 64);
    if (!b.ipc_dir || !b.host_file || !b.request_file) return 2;
    sprintf(b.host_file, "%s/clipboard_host_to_android", dir);
    snprintf(b.request_file, strlen(dir) + 64, "%s/../clipboard_host_request", dir);
    b.android_uid = (uid_t)android_uid;
    struct stat st;
    if (lstat(dir, &st) != 0 || !S_ISDIR(st.st_mode) || S_ISLNK(st.st_mode) ||
        st.st_uid != 0 || (st.st_mode & 07777) != 01733) {
        fprintf(stderr, "clipboard IPC directory is missing or unsafe\n");
        return 2;
    }
    b.inotify_fd = inotify_init1(IN_CLOEXEC | IN_NONBLOCK);
    if (b.inotify_fd < 0) { perror("inotify_init1"); return 2; }
    b.watch_id = inotify_add_watch(b.inotify_fd, dir, IN_CLOSE_WRITE | IN_MOVED_TO);
    if (b.watch_id < 0) { perror("inotify_add_watch"); return 2; }
    b.display = wl_display_connect(NULL);
    if (!b.display) { perror("wl_display_connect"); return 3; }
    b.registry = wl_display_get_registry(b.display);
    wl_registry_add_listener(b.registry, &registry_listener, &b);
    if (wl_display_roundtrip(b.display) < 0 || !b.seat || !b.manager) {
        fprintf(stderr, "compositor lacks wl_seat or ext_data_control_manager_v1\n");
        return 3;
    }
    b.device = ext_data_control_manager_v1_get_data_device(b.manager, b.seat);
    ext_data_control_device_v1_add_listener(b.device, &device_listener, &b);
    if (wl_display_roundtrip(b.display) < 0) return 3;
    fprintf(stderr, "AaaS clipboard bridge ready\n");
    publish_pending_android_clip(&b);
    while (running && !b.failed) {
        if (wl_display_dispatch_pending(b.display) < 0) break;
        if (wl_display_flush(b.display) < 0 && errno != EAGAIN) break;
        struct pollfd fds[2] = {
            { .fd = wl_display_get_fd(b.display), .events = POLLIN },
            { .fd = b.inotify_fd, .events = POLLIN },
        };
        int result = poll(fds, 2, -1);
        if (result < 0 && errno == EINTR) continue;
        if (result < 0) break;
        if (fds[0].revents & (POLLERR | POLLHUP | POLLNVAL)) break;
        if (fds[0].revents & POLLIN)
            if (wl_display_dispatch(b.display) < 0) break;
        if (fds[1].revents & POLLIN) {
            char events[8192];
            ssize_t count;
            while ((count = read(b.inotify_fd, events, sizeof(events))) > 0) {
                for (char *cursor = events; cursor < events + count;) {
                    struct inotify_event *event = (struct inotify_event *)cursor;
                    if ((event->mask & IN_MOVED_TO) && event->len &&
                        !strncmp(event->name, "android-", 8) &&
                        strstr(event->name, ".frame") == event->name + strlen(event->name) - 6) {
                        char path[4096];
                        int length = snprintf(path, sizeof(path), "%s/%s", dir,
                                              event->name);
                        if (length > 0 && (size_t)length < sizeof(path))
                            publish_android_clip(&b, path);
                    }
                    cursor += sizeof(*event) + event->len;
                }
            }
        }
    }
    if (b.source) {
        ext_data_control_device_v1_set_selection(b.device, NULL);
        (void)wl_display_flush(b.display);
        (void)wl_display_roundtrip(b.display);
    }
    destroy_source(&b);
    if (b.offer) ext_data_control_offer_v1_destroy(b.offer);
    if (b.device) ext_data_control_device_v1_destroy(b.device);
    if (b.manager) ext_data_control_manager_v1_destroy(b.manager);
    if (b.seat) wl_seat_release(b.seat);
    if (b.registry) wl_registry_destroy(b.registry);
    if (b.display) wl_display_disconnect(b.display);
    if (b.inotify_fd >= 0) close(b.inotify_fd);
    free(b.offer_mimes); free(b.active_text); free(b.last_local_text);
    free(b.host_file); free(b.request_file); free(b.ipc_dir);
    return 0;
}
