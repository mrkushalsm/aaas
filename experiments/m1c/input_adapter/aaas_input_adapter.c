/*
 * AaaS Android pointer input adapter.
 *
 * Persistent Android-side daemon.  It accepts only the versioned AaaS pointer
 * protocol on a private SEQPACKET socket and feeds validated press/release/
 * move/hover/scroll events to Android's real input system.  The default
 * backend is a persistent native Binder client.  The legacy per-event
 * `cmd input` path is retained as an explicit diagnostic fallback.
 */

#include "input_v1.h"
#include "input_state.h"
#include "inject_binder.h"

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define DEFAULT_SOCKET "/dev/aaas/input.sock"
#define DEFAULT_SESSION_FILE "/dev/aaas/input_session"
#define DEFAULT_LOG "/aaas_input_adapter.log"
#define CMD_PATH "/system/bin/cmd"
#define INJECT_TIMEOUT_MS 3000

/*
 * The adapter is built against the host's C headers but linked with Bionic's
 * libc (the same compatibility pattern used by the AaaS Composer service).
 * Bionic exposes __errno rather than glibc's __errno_location.
 */
int *__errno(void);
int *__errno_location(void) {
    return __errno();
}

static volatile sig_atomic_t g_stop;
static int g_log_fd = -1;
/* Each private presenter socket is bound to one trusted Android display. */
static int32_t g_android_display_id;

typedef enum {
    INPUT_BACKEND_AUTO = 0,
    INPUT_BACKEND_BINDER,
    INPUT_BACKEND_CMD,
} input_backend;

static input_backend g_backend = INPUT_BACKEND_AUTO;

static int ascii_digit(char c, int base) {
    int v;
    if (c >= '0' && c <= '9') v = c - '0';
    else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
    else if (c >= 'A' && c <= 'F') v = c - 'a' + 10;
    else return -1;
    return v < base ? v : -1;
}

static uint64_t parse_u64(const char *s, int *ok) {
    if (!s) {
        *ok = 0;
        return 0;
    }
    while (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r') s++;
    int base = 10;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        base = 16;
        s += 2;
    }
    uint64_t value = 0;
    int digits = 0;
    while (*s) {
        int d = ascii_digit(*s, base);
        if (d < 0) break;
        value = value * (uint64_t)base + (uint64_t)d;
        digits++;
        s++;
    }
    *ok = digits > 0;
    return value;
}

static int parse_int(const char *s, int *ok) {
    int negative = 0;
    if (!s) {
        *ok = 0;
        return 0;
    }
    while (*s == ' ' || *s == '\t') s++;
    if (*s == '-') {
        negative = 1;
        s++;
    } else if (*s == '+') {
        s++;
    }
    uint64_t value = parse_u64(s, ok);
    if (!*ok || value > 0x7fffffffU) {
        *ok = 0;
        return 0;
    }
    return negative ? -(int)value : (int)value;
}

/*
 * Bionic does not ship crt1.o in this rootfs and clang is invoked with
 * -nostdlib (the same ABI pattern as the Composer service), so provide the
 * minimal PIE entry point and let Bionic initialize argc/argv/envp.
 */
extern void __libc_init(void *raw_args, void *onexit,
                        int (*main_fn)(int, char **, char **), void *structors);

__attribute__((naked, noreturn)) void _start(void) {
    __asm__ volatile (
        "xor %ebp, %ebp\n"
        "mov %rsp, %rdi\n"
        "and $-16, %rsp\n"
        "sub $48, %rsp\n"
        "movq $0, (%rsp)\n"
        "movq $0, 8(%rsp)\n"
        "movq $0, 16(%rsp)\n"
        "movq $0, 24(%rsp)\n"
        "movq $0, 32(%rsp)\n"
        "movq $0, 40(%rsp)\n"
        "xor %esi, %esi\n"
        "lea main(%rip), %rdx\n"
        "mov %rsp, %rcx\n"
        "call __libc_init\n"
        "hlt\n"
    );
}


static uint64_t monotonic_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ULL + (uint64_t)t.tv_nsec;
}

static void adapter_log(const char *event, const char *extra_json) {
    char line[1024];
    int n;
    if (extra_json && extra_json[0]) {
        n = snprintf(line, sizeof(line),
                     "{\"t_ns\":%llu,\"role\":\"input_adapter\",\"event\":\"%s\",%s}\n",
                     (unsigned long long)monotonic_ns(), event, extra_json);
    } else {
        n = snprintf(line, sizeof(line),
                     "{\"t_ns\":%llu,\"role\":\"input_adapter\",\"event\":\"%s\"}\n",
                     (unsigned long long)monotonic_ns(), event);
    }
    if (n < 0) {
        return;
    }
    if ((size_t)n >= sizeof(line)) {
        n = (int)sizeof(line) - 1;
    }
    if (g_log_fd >= 0) {
        ssize_t ignored = write(g_log_fd, line, (size_t)n);
        (void)ignored;
    }
    ssize_t ignored2 = write(STDERR_FILENO, line, (size_t)n);
    (void)ignored2;
}

static void adapter_logf(const char *event, const char *fmt, ...) {
    char extra[768];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(extra, sizeof(extra), fmt, ap);
    va_end(ap);
    adapter_log(event, extra);
}

static void handle_signal(int sig) {
    (void)sig;
    g_stop = 1;
}

static uint32_t button_mask(uint32_t button) {
    switch (button) {
    case AAAS_INPUT_BUTTON_LEFT: return 1u << 0;
    case AAAS_INPUT_BUTTON_RIGHT: return 1u << 1;
    case AAAS_INPUT_BUTTON_MIDDLE: return 1u << 2;
    default: return 0;
    }
}

static uint64_t read_session_id(const char *path) {
    for (int attempt = 0; attempt < 50 && !g_stop; attempt++) {
        int fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd >= 0) {
            char buf[64];
            ssize_t n = read(fd, buf, sizeof(buf) - 1);
            close(fd);
            if (n > 0) {
                buf[n] = '\0';
                int ok = 0;
                uint64_t value = parse_u64(buf, &ok);
                if (ok && value != 0) {
                    return value;
                }
            }
        }
        usleep(100000);
    }
    return 0;
}

static int connect_input_socket(const char *path) {
    for (int attempt = 0; attempt < 100 && !g_stop; attempt++) {
        int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
        if (fd < 0) {
            adapter_log("socket_failed", NULL);
            return -1;
        }
        struct sockaddr_un addr;
        memset(&addr, 0, sizeof(addr));
        addr.sun_family = AF_UNIX;
        strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);
        if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) == 0) {
            return fd;
        }
        close(fd);
        if (attempt == 0 || attempt % 10 == 9) {
            char extra[128];
            snprintf(extra, sizeof(extra), "\"attempt\":%d,\"errno\":%d", attempt + 1, errno);
            adapter_log("connect_retry", extra);
        }
        usleep(100000);
    }
    return -1;
}

static int wait_for_child(pid_t pid) {
    uint64_t deadline = monotonic_ns() + (uint64_t)INJECT_TIMEOUT_MS * 1000000ULL;
    for (;;) {
        int status = 0;
        pid_t r = waitpid(pid, &status, WNOHANG);
        if (r == pid) {
            if (WIFEXITED(status)) {
                return WEXITSTATUS(status);
            }
            return -1;
        }
        if (r < 0 && errno != EINTR) {
            return -1;
        }
        if (monotonic_ns() >= deadline) {
            kill(pid, SIGKILL);
            while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
            }
            return -1;
        }
        /* Keep synchronous framework-built scrolls from adding another
         * 5 ms scheduling quantum to each Android input event. */
        usleep(1000);
    }
}

static const char *action_name(int action) {
    switch (action) {
    case AAAS_ACTION_DOWN: return "DOWN";
    case AAAS_ACTION_UP: return "UP";
    case AAAS_ACTION_MOVE: return "MOVE";
    case AAAS_ACTION_BUTTON_PRESS: return "BUTTON_PRESS";
    case AAAS_ACTION_BUTTON_RELEASE: return "BUTTON_RELEASE";
    case AAAS_ACTION_SCROLL: return "SCROLL";
    case AAAS_ACTION_HOVER_MOVE: return "HOVER_MOVE";
    case AAAS_ACTION_HOVER_ENTER: return "HOVER_ENTER";
    case AAAS_ACTION_HOVER_EXIT: return "HOVER_EXIT";
    default: return "UNKNOWN";
    }
}

static const char *source_name(uint32_t source) {
    switch (source) {
    case AAAS_SOURCE_TOUCHSCREEN: return "TOUCHSCREEN";
    case AAAS_SOURCE_MOUSE: return "MOUSE";
    case AAAS_SOURCE_TOUCHPAD: return "TOUCHPAD";
    default: return "UNKNOWN";
    }
}

static int inject_cmd_motion(const char *motion, int32_t x, int32_t y,
                             uint32_t sequence, int64_t request_ns) {
    char xs[16], display[16];
    char ys[16];
    snprintf(xs, sizeof(xs), "%d", x);
    snprintf(ys, sizeof(ys), "%d", y);
    snprintf(display, sizeof(display), "%d", g_android_display_id);

    uint64_t start_ns = monotonic_ns();
    pid_t pid = fork();
    if (pid < 0) {
        adapter_log("fork_failed", NULL);
        return -1;
    }
    if (pid == 0) {
        char *argv[] = {
            (char *)"cmd",
            (char *)"input",
            (char *)"-d",
            display,
            (char *)"motionevent",
            (char *)motion,
            xs,
            ys,
            NULL,
        };
        execv(CMD_PATH, argv);
        _exit(127);
    }

    int rc = wait_for_child(pid);
    uint64_t done_ns = monotonic_ns();
    adapter_logf(rc == 0 ? "inject_done" : "inject_failed",
                 "\"backend\":\"cmd\",\"action\":\"%s\",\"x\":%d,\"y\":%d,"
                 "\"sequence\":%u,\"rc\":%d,\"request_ns\":%llu,"
                 "\"start_ns\":%llu,\"done_ns\":%llu,\"elapsed_ns\":%llu",
                 motion, x, y, sequence, rc,
                 (unsigned long long)request_ns,
                 (unsigned long long)start_ns,
                 (unsigned long long)done_ns,
                 (unsigned long long)(done_ns - start_ns));
    return rc;
}

static int inject_cmd_scroll(int32_t x, int32_t y, uint32_t source,
                             float vscroll, float hscroll,
                             uint32_t sequence, int64_t request_ns) {
    /* Android's generic View scroll handlers gate AXIS_VSCROLL/HSCROLL on
     * SOURCE_CLASS_POINTER.  SOURCE_TOUCHPAD is position-class and Settings'
     * ScrollViews ignore its ACTION_SCROLL even though injection succeeds.
     * Normalize both Wayland wheel and touchpad deltas to Android mouse scroll. */
    const char *input_source = "mouse";
    const char *origin_source = source == AAAS_SOURCE_TOUCHPAD ? "touchpad" : "mouse";
    char xs[16], ys[16], vs[48], hs[48];
    char display[16];
    snprintf(xs, sizeof(xs), "%d", x);
    snprintf(ys, sizeof(ys), "%d", y);
    snprintf(vs, sizeof(vs), "VSCROLL,%.6g", (double)vscroll);
    snprintf(hs, sizeof(hs), "HSCROLL,%.6g", (double)hscroll);
    snprintf(display, sizeof(display), "%d", g_android_display_id);

    uint64_t start_ns = monotonic_ns();
    pid_t pid = fork();
    if (pid < 0) {
        adapter_log("fork_failed", "\"action\":\"SCROLL\"");
        return -1;
    }
    if (pid == 0) {
        char *argv[16];
        int n = 0;
        argv[n++] = (char *)"cmd";
        argv[n++] = (char *)"input";
        /* Android 16 parses optional source before optional display ID:
         * input [source] [-d DISPLAY_ID] command. */
        argv[n++] = (char *)input_source;
        argv[n++] = (char *)"-d";
        argv[n++] = display;
        argv[n++] = (char *)"scroll";
        argv[n++] = xs;
        argv[n++] = ys;
        if (vscroll != 0.0f) {
            argv[n++] = (char *)"--axis";
            argv[n++] = vs;
        }
        if (hscroll != 0.0f) {
            argv[n++] = (char *)"--axis";
            argv[n++] = hs;
        }
        argv[n] = NULL;
        execv(CMD_PATH, argv);
        _exit(127);
    }

    int rc = wait_for_child(pid);
    uint64_t done_ns = monotonic_ns();
    adapter_logf(rc == 0 ? "inject_done" : "inject_failed",
                 "\"backend\":\"cmd\",\"action\":\"SCROLL\","
                 "\"source\":\"%s\",\"android_source\":\"%s\",\"x\":%d,\"y\":%d,"
                 "\"vscroll\":%.6g,\"hscroll\":%.6g,\"sequence\":%u,"
                 "\"rc\":%d,\"request_ns\":%llu,\"start_ns\":%llu,"
                 "\"done_ns\":%llu,\"elapsed_ns\":%llu",
                 origin_source, input_source, x, y, (double)vscroll, (double)hscroll,
                 sequence, rc, (unsigned long long)request_ns,
                 (unsigned long long)start_ns, (unsigned long long)done_ns,
                 (unsigned long long)(done_ns - start_ns));
    return rc;
}

static int inject_event(int action, int32_t x, int32_t y,
                        uint32_t source, uint32_t tool_type,
                        uint32_t button_state, uint32_t action_button,
                        float pressure, float vscroll, float hscroll,
                        uint32_t sequence, int64_t request_ns) {
    uint64_t start_ns = monotonic_ns();
    /* Android's MotionEvent.obtain path is the validated scroll serializer. */
    if (action == AAAS_ACTION_SCROLL) {
        return inject_cmd_scroll(x, y, source, vscroll, hscroll,
                                 sequence, request_ns);
    }
    if (g_backend == INPUT_BACKEND_AUTO &&
        (action == AAAS_ACTION_DOWN || action == AAAS_ACTION_BUTTON_PRESS ||
         action == AAAS_ACTION_HOVER_ENTER || action == AAAS_ACTION_HOVER_MOVE ||
         action == AAAS_ACTION_SCROLL)) {
        int rc = aaas_binder_inject(action, x, y, source, tool_type,
                                    button_state, action_button, pressure,
                                    vscroll, hscroll, (int64_t)start_ns, sequence,
                                    g_android_display_id);
        if (rc != 0) {
            adapter_logf("inject_failed", "\"backend\":\"binder_probe\",\"action\":\"%s\","
                         "\"sequence\":%u,\"rc\":%d",
                         action_name(action), sequence, rc);
            return rc;
        }
        g_backend = INPUT_BACKEND_BINDER;
        adapter_logf("backend_selected", "\"backend\":\"binder\",\"probe_rc\":0");
        adapter_logf("inject_done", "\"backend\":\"binder\",\"action\":\"%s\","
                     "\"sequence\":%u,\"elapsed_ns\":%llu",
                     action_name(action), sequence,
                     (unsigned long long)(monotonic_ns() - start_ns));
        return 0;
    }
    if (g_backend == INPUT_BACKEND_CMD) {
        switch (action) {
        case AAAS_ACTION_DOWN:
            return inject_cmd_motion("DOWN", x, y, sequence, request_ns);
        case AAAS_ACTION_MOVE:
            return inject_cmd_motion("MOVE", x, y, sequence, request_ns);
        case AAAS_ACTION_UP:
            return inject_cmd_motion("UP", x, y, sequence, request_ns);
        case AAAS_ACTION_BUTTON_PRESS:
        case AAAS_ACTION_BUTTON_RELEASE:
            adapter_log("cmd_backend_extra_mouse_button_unsupported", NULL);
            return -1;
        case AAAS_ACTION_HOVER_MOVE:
        case AAAS_ACTION_HOVER_ENTER:
        case AAAS_ACTION_HOVER_EXIT:
            /* Hover is intentionally not synthesized on the diagnostic path. */
            return 0;
        default:
            return -1;
        }
    }

    int rc = aaas_binder_inject(action, x, y, source, tool_type, button_state,
                               action_button, pressure, vscroll, hscroll,
                               (int64_t)start_ns, sequence, g_android_display_id);
    if (rc != 0 && (action == AAAS_ACTION_UP || action == AAAS_ACTION_BUTTON_RELEASE)) {
        /* Service failure is uncertain: keep state tracked and retry during cleanup. */
        adapter_log("up_injection_failed_state_retained", NULL);
    }
    uint64_t done_ns = monotonic_ns();
    adapter_logf(rc == 0 ? "inject_done" : "inject_failed",
                 "\"backend\":\"binder\",\"action\":\"%s\",\"x\":%d,\"y\":%d,"
                 "\"source\":\"%s\",\"tool\":%u,\"button_state\":%u,"
                 "\"action_button\":%u,\"pressure\":%.3f,\"vscroll\":%.3f,"
                 "\"hscroll\":%.3f,\"sequence\":%u,\"rc\":%d,"
                 "\"request_ns\":%llu,\"start_ns\":%llu,\"done_ns\":%llu,"
                 "\"elapsed_ns\":%llu",
                 action_name(action), x, y, source_name(source), tool_type,
                 button_state, action_button, pressure, vscroll, hscroll,
                 sequence, rc,
                 (unsigned long long)request_ns,
                 (unsigned long long)start_ns,
                 (unsigned long long)done_ns,
                 (unsigned long long)(done_ns - start_ns));
    return rc;
}

static void send_ack(int fd, const aaas_input_msg *hello, uint64_t session_id) {
    aaas_input_msg host = {
        .magic = AAAS_INPUT_MAGIC,
        .version = AAAS_INPUT_VERSION,
        .type = AAAS_INPUT_HELLO,
        .length = AAAS_INPUT_MSG_SIZE,
        .sequence = 0,
        .display_id = hello->display_id,
        .display_generation = hello->display_generation,
        .timestamp_ns = monotonic_ns(),
        .session_id = session_id,
        .x = hello->x,
        .y = hello->y,
        .button = 0,
        .state = 1,
        .focus_generation = hello->focus_generation,
        .flags = AAAS_INPUT_FLAG_ACK | AAAS_INPUT_FLAG_KEYBOARD_V2,
        .reserved = 0,
    };
    aaas_input_msg wire;
    aaas_input_to_wire(&wire, &host);
    ssize_t n = send(fd, &wire, sizeof(wire), MSG_NOSIGNAL);
    if (n != (ssize_t)sizeof(wire)) {
        adapter_log("hello_ack_failed", NULL);
    }
}

typedef struct {
    aaas_input_state order;
    uint32_t android_display_id;
    uint32_t pressed_buttons;
    int focused;
    int32_t last_x;
    int32_t last_y;
    unsigned invalid_messages;
    input_backend selected_backend;
    int keyboard_focused;
    const char *focus_request_path;
    const char *focus_ack_path;
    uint64_t focus_instance_nonce;
    uint8_t pressed_keys[768];
    uint32_t pressed_keycodes[768];
    int64_t key_down_ns[768];
} adapter_state;

static int parse_decimal_field(const char **cursor, char delimiter,
                               uint64_t maximum, uint64_t *value) {
    const char *p = *cursor;
    if (*p < '0' || *p > '9') return -1;
    uint64_t parsed = 0;
    do {
        unsigned digit = (unsigned)(*p - '0');
        if (parsed > (maximum - digit) / 10U) return -1;
        parsed = parsed * 10U + digit;
        ++p;
    } while (*p >= '0' && *p <= '9');
    if (*p != delimiter) return -1;
    *cursor = p + 1;
    *value = parsed;
    return 0;
}

static int request_android_display_focus(adapter_state *st, uint32_t generation) {
    if (!st->focus_request_path || !st->focus_ack_path) return 0;
    char request[128];
    int request_len = snprintf(request, sizeof(request), "%llu %u %u\n",
            (unsigned long long)st->focus_instance_nonce, generation,
            st->android_display_id);
    if (request_len <= 0 || request_len >= (int)sizeof(request)) return -1;
    int fd = open(st->focus_request_path, O_WRONLY | O_TRUNC | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t written = write(fd, request, (size_t)request_len);
    close(fd);
    if (written != request_len) return -1;

    /* The broker acknowledges only after InputDispatcher reports the target Activity window.
     * Allow that bounded Android focus transition to finish before rejecting host focus. */
    uint64_t deadline = monotonic_ns() + 3000000000ULL;
    while (monotonic_ns() < deadline && !g_stop) {
        char response[128] = {0};
        fd = open(st->focus_ack_path, O_RDONLY | O_CLOEXEC);
        if (fd >= 0) {
            ssize_t count = read(fd, response, sizeof(response) - 1);
            close(fd);
            uint64_t nonce = 0, response_generation = 0, task_id = 0;
            const char *cursor = response;
            int ready = count > 8 && strncmp(cursor, "focused ", 8) == 0;
            int rejected = count > 9 && strncmp(cursor, "unfocused ", 10) == 0;
            int parsed = ready || rejected;
            if (parsed) {
                cursor += ready ? 8 : 10;
                parsed = parse_decimal_field(&cursor, ' ', UINT64_MAX, &nonce) == 0 &&
                        parse_decimal_field(&cursor, ' ', UINT32_MAX,
                                            &response_generation) == 0 &&
                        parse_decimal_field(&cursor, '\n', INT32_MAX, &task_id) == 0;
            }
            if (parsed && nonce == st->focus_instance_nonce &&
                    response_generation == generation) {
                if (ready) {
                    adapter_logf("android_display_focus_ready",
                            "\"display\":%u,\"generation\":%u,\"task_id\":%d",
                            st->android_display_id, generation, (int)task_id);
                    return 0;
                }
                adapter_logf("android_display_focus_rejected",
                        "\"display\":%u,\"generation\":%u",
                        st->android_display_id, generation);
                return -1;
            }
        }
        usleep(10000);
    }
    adapter_logf("android_display_focus_timeout",
            "\"display\":%u,\"generation\":%u",
            st->android_display_id, generation);
    return -1;
}

static int handle_keyboard_message(adapter_state *st, const aaas_input_keyboard_msg *wire) {
    aaas_input_keyboard_msg m;
    aaas_input_keyboard_from_wire(&m,wire);
    char why[64]={0};
    if(aaas_input_keyboard_validate(&m,st->order.session_id,
                                    st->android_display_id,why,sizeof(why))!=0 ||
       m.display_generation<st->order.display_generation || m.sequence==0 ||
       m.sequence<=st->order.sequence || m.focus_generation<st->order.focus_generation) {
        adapter_logf("keyboard_packet_rejected", "\"reason\":\"%s\"", why[0]?why:"stale ordering");
        return 0;
    }
    adapter_logf("keyboard_packet_validated", "\"sequence\":%u,\"type\":%u,\"state\":%u",
                 m.sequence,m.type,m.state);
    st->order.sequence=m.sequence;
    st->order.display_generation=m.display_generation;
    st->order.focus_generation=m.focus_generation;
    int64_t now=(int64_t)monotonic_ns();
    if(m.type==AAAS_INPUT_KEYBOARD_FOCUS) {
        if(m.state==AAAS_INPUT_FOCUS_LEAVE) {
            uint32_t released=0;
            for(uint32_t k=0;k<768;k++) if(st->pressed_keys[k]) {
                int rc=aaas_binder_inject_key(1,(int32_t)st->pressed_keycodes[k],
                    (int32_t)k,0,0,now,st->key_down_ns[k],g_android_display_id);
                if(rc==0) { st->pressed_keys[k]=0; released++; }
            }
            adapter_logf("keyboard_focus_leave","\"released\":%u",released);
            st->keyboard_focused=0;
        } else {
            if (request_android_display_focus(st, m.focus_generation) != 0) {
                st->keyboard_focused=0;
                adapter_log("keyboard_focus_android_rejected",NULL);
                return 0;
            }
            st->keyboard_focused=1;
            adapter_log("keyboard_focus_enter",NULL);
        }
        return 0;
    }
    if(!st->keyboard_focused) { adapter_log("unfocused_key_rejected",NULL); return 0; }
    uint32_t k=m.evdev_key;
    if(m.state==AAAS_INPUT_KEY_PRESSED) {
        if(!st->pressed_keys[k]) { st->pressed_keys[k]=1; st->pressed_keycodes[k]=m.android_keycode; st->key_down_ns[k]=(int64_t)m.timestamp_ns; }
    } else if(!st->pressed_keys[k]) {
        adapter_log("key_release_without_press",NULL); return 0;
    }
    int rc=aaas_binder_inject_key(m.state==AAAS_INPUT_KEY_PRESSED?0:1,
        (int32_t)m.android_keycode,(int32_t)k,
        (int32_t)m.meta_state,(int32_t)m.repeat_count,(int64_t)m.timestamp_ns,
        st->pressed_keys[k]?st->key_down_ns[k]:(int64_t)m.timestamp_ns,
        g_android_display_id);
    if(rc==0 && m.state==AAAS_INPUT_KEY_RELEASED) st->pressed_keys[k]=0;
    adapter_logf(rc==0?"key_injected":"key_injection_failed",
        "\"sequence\":%u,\"state\":%u,\"rc\":%d,\"elapsed_ns\":%llu",
        m.sequence,m.state,rc,(unsigned long long)(monotonic_ns()-(uint64_t)now));
    return 0;
}

static int handle_message(int fd, adapter_state *st,
                          const aaas_input_msg *wire);

static int accept_message(adapter_state *st, const aaas_input_msg *wire,
                          aaas_input_msg *m, int64_t *request_ns,
                          int64_t *recv_ns) {
    aaas_input_from_wire(m, wire);
    *request_ns = (int64_t)m->timestamp_ns;
    *recv_ns = (int64_t)monotonic_ns();

    char why[64] = {0};
    if (aaas_input_validate(m, st->order.session_id, st->android_display_id,
                            why, sizeof(why)) != 0) {
        st->invalid_messages++;
        adapter_logf("invalid_message", "\"reason\":\"%s\",\"count\":%u",
                     why, st->invalid_messages);
        return st->invalid_messages >= 8 ? -1 : 0;
    }
    if (!aaas_input_state_accept(&st->order, m, why, sizeof(why))) {
        st->invalid_messages++;
        adapter_logf("invalid_message", "\"reason\":\"%s\",\"count\":%u",
                     why, st->invalid_messages);
        return st->invalid_messages >= 8 ? -1 : 0;
    }
    return 1;
}

/* High-resolution touchpads and high-rate wheel devices can produce scroll
 * packets faster than the Android `cmd input` process can start. Sum only
 * adjacent packets with the same source and focus/display generation; never
 * batch across another input event. This preserves ordering and total delta. */
static int handle_scroll_burst(int fd, adapter_state *st,
                               const aaas_input_msg *first_wire) {
    aaas_input_msg m;
    aaas_input_from_wire(&m, first_wire);
    if (m.type != AAAS_INPUT_SCROLL ||
        m.button > AAAS_INPUT_AXIS_SOURCE_WHEEL_TILT) {
        return handle_message(fd, st, first_wire);
    }
    int64_t request_ns = 0, recv_ns = 0;
    int accepted = accept_message(st, first_wire, &m, &request_ns, &recv_ns);
    if (accepted <= 0) return accepted < 0;

    int64_t total_v = (int32_t)m.state;
    int64_t total_h = (int32_t)m.reserved;
    uint32_t count = 1;
    uint32_t first_sequence = m.sequence;
    uint32_t last_sequence = m.sequence;
    int32_t x = m.x, y = m.y;
    uint64_t generation = m.display_generation;
    uint32_t focus_generation = m.focus_generation;
    const uint32_t source = m.button;
    const int64_t first_request_ns = request_ns;

    while (count < 128) {
        aaas_input_msg peek_wire, peek;
        ssize_t n = recv(fd, &peek_wire, sizeof(peek_wire),
                         MSG_PEEK | MSG_DONTWAIT | MSG_TRUNC);
        if (n != (ssize_t)sizeof(peek_wire)) break;
        aaas_input_from_wire(&peek, &peek_wire);
        if (peek.type != AAAS_INPUT_SCROLL || peek.button != source ||
            peek.display_generation != generation ||
            peek.focus_generation != focus_generation) {
            break;
        }

        aaas_input_msg next_wire;
        n = recv(fd, &next_wire, sizeof(next_wire), MSG_DONTWAIT | MSG_TRUNC);
        if (n != (ssize_t)sizeof(next_wire)) break;
        int64_t next_request_ns = 0, next_recv_ns = 0;
        accepted = accept_message(st, &next_wire, &m,
                                  &next_request_ns, &next_recv_ns);
        if (accepted < 0) return 1;
        if (!accepted) continue;
        total_v += (int32_t)m.state;
        total_h += (int32_t)m.reserved;
        if (total_v > INT32_MAX || total_v < INT32_MIN ||
            total_h > INT32_MAX || total_h < INT32_MIN) {
            adapter_log("scroll_batch_overflow", NULL);
            return 0;
        }
        x = m.x;
        y = m.y;
        last_sequence = m.sequence;
        count++;
    }

    st->last_x = x;
    st->last_y = y;
    if (!st->focused) {
        adapter_log("unfocused_scroll_rejected", NULL);
        return 0;
    }
    float v = (float)total_v / 120.0f;
    float h = (float)total_h / 120.0f;
    const char *source_name = "wheel";
    switch (source) {
    case AAAS_INPUT_AXIS_SOURCE_FINGER: source_name = "finger"; break;
    case AAAS_INPUT_AXIS_SOURCE_CONTINUOUS: source_name = "continuous"; break;
    case AAAS_INPUT_AXIS_SOURCE_WHEEL_TILT: source_name = "wheel_tilt"; break;
    }
    bool touchpad = source == AAAS_INPUT_AXIS_SOURCE_FINGER ||
                    source == AAAS_INPUT_AXIS_SOURCE_CONTINUOUS;
    if (count > 1) {
        adapter_logf("scroll_batch", "\"source\":\"%s\",\"count\":%u,"
                     "\"vscroll\":%.6g,\"hscroll\":%.6g,\"first_sequence\":%u,"
                     "\"last_sequence\":%u,\"oldest_request_ns\":%llu",
                     source_name, count, (double)v, (double)h,
                     first_sequence, last_sequence,
                     (unsigned long long)first_request_ns);
    }
    return inject_cmd_scroll(x, y, touchpad ? AAAS_SOURCE_TOUCHPAD : AAAS_SOURCE_MOUSE,
                             v, h,
                             last_sequence, first_request_ns) != 0;
}

static int inject_request(adapter_state *st, int action, int32_t x, int32_t y,
                          uint32_t source, uint32_t tool_type,
                          uint32_t button_state, uint32_t action_button,
                          float pressure, float vscroll, float hscroll,
                          uint32_t sequence, int64_t request_ns) {
    (void)st;
    return inject_event(action, x, y, source, tool_type, button_state,
                        action_button, pressure, vscroll, hscroll,
                        sequence, request_ns);
}

static void release_all(adapter_state *st, int32_t x, int32_t y,
                        uint32_t sequence, const char *reason) {
    static const uint32_t buttons[] = {
        AAAS_INPUT_BUTTON_LEFT,
        AAAS_INPUT_BUTTON_RIGHT,
        AAAS_INPUT_BUTTON_MIDDLE,
    };
    uint32_t mask = st->pressed_buttons;
    if (!mask) {
        return;
    }
    for (unsigned i = 0; i < sizeof(buttons) / sizeof(buttons[0]); i++) {
        uint32_t bit = button_mask(buttons[i]);
        if (!(mask & bit)) {
            continue;
        }
        uint32_t remaining = st->pressed_buttons & ~bit;
        const uint32_t android_remaining =
                (remaining & (1u << 0) ? AAAS_BUTTON_PRIMARY : 0) |
                (remaining & (1u << 1) ? AAAS_BUTTON_SECONDARY : 0) |
                (remaining & (1u << 2) ? AAAS_BUTTON_TERTIARY : 0);
        uint32_t android_button = bit == (1u << 0) ? AAAS_BUTTON_PRIMARY
                : bit == (1u << 1) ? AAAS_BUTTON_SECONDARY : AAAS_BUTTON_TERTIARY;
        int action = remaining == 0 ? AAAS_ACTION_UP : AAAS_ACTION_BUTTON_RELEASE;
        int rc = inject_request(st, action, x, y, AAAS_SOURCE_MOUSE, AAAS_TOOL_MOUSE,
                                android_remaining, android_button, 0.0f, 0.0f, 0.0f,
                                sequence, (int64_t)monotonic_ns());
        if (rc != 0) {
            adapter_log("release_reconciliation_failed", NULL);
            break;
        }
        st->pressed_buttons = remaining;
    }
    adapter_logf("buttons_released", "\"reason\":\"%s\",\"remaining\":%u",
                 reason, st->pressed_buttons);
}

static int handle_message(int fd, adapter_state *st, const aaas_input_msg *wire) {
    aaas_input_msg m;
    int64_t request_ns = 0, recv_ns = 0;
    int accepted = accept_message(st, wire, &m, &request_ns, &recv_ns);
    if (accepted <= 0) return accepted < 0;

    switch (m.type) {
    case AAAS_INPUT_HELLO: {
        send_ack(fd, &m, st->order.session_id);
        st->last_x = 0;
        st->last_y = 0;
        st->focused = 0;
        adapter_logf("hello",
                     "\"display_generation\":%u,\"width\":%d,\"height\":%d,"
                     "\"sequence\":%u,\"request_ns\":%llu,\"recv_ns\":%llu",
                     st->order.display_generation, m.x, m.y,
                     st->order.sequence,
                     (unsigned long long)request_ns,
                     (unsigned long long)recv_ns);
        return 0;
    }
    case AAAS_INPUT_FOCUS: {
        st->last_x = m.x;
        st->last_y = m.y;
        if (m.state == AAAS_INPUT_FOCUS_ENTER) {
            st->focused = 1;
            /* Host focus is tracked locally. Android's injected host pointer
             * has no stable device identity and can retain stale hover state. */
            adapter_logf("focus_enter", "\"sequence\":%u,\"request_ns\":%llu,\"recv_ns\":%llu",
                         st->order.sequence,
                         (unsigned long long)request_ns,
                         (unsigned long long)recv_ns);
        } else {
            release_all(st, st->last_x, st->last_y, st->order.sequence,
                        "focus_leave");
            st->focused = 0;
            adapter_logf("focus_leave", "\"sequence\":%u,\"request_ns\":%llu,\"recv_ns\":%llu",
                         st->order.sequence,
                         (unsigned long long)request_ns,
                         (unsigned long long)recv_ns);
        }
        return 0;
    }
    case AAAS_INPUT_SHUTDOWN: {
        uint64_t now=monotonic_ns();
        for(uint32_t k=0;k<768;k++) if(st->pressed_keys[k]) {
            if(aaas_binder_inject_key(1,(int32_t)st->pressed_keycodes[k],(int32_t)k,
               0,0,(int64_t)now,st->key_down_ns[k],g_android_display_id)==0)
                st->pressed_keys[k]=0;
        }
        st->keyboard_focused=0;
        release_all(st, st->last_x, st->last_y, st->order.sequence,
                    "shutdown");
        adapter_logf("shutdown_received", "\"sequence\":%u,\"request_ns\":%llu,\"recv_ns\":%llu",
                     st->order.sequence,
                     (unsigned long long)request_ns,
                     (unsigned long long)recv_ns);
        return 1;
    }
    case AAAS_INPUT_MOTION: {
        st->last_x = m.x;
        st->last_y = m.y;
        if (!st->focused) {
            return 0;
        }
        if (st->pressed_buttons) {
            inject_request(st, AAAS_ACTION_MOVE, m.x, m.y, AAAS_SOURCE_MOUSE,
                           AAAS_TOOL_MOUSE, st->pressed_buttons, 0,
                           1.0f, 0.0f, 0.0f, st->order.sequence, request_ns);
        }
        return 0;
    }
    case AAAS_INPUT_HOVER: {
        st->last_x = m.x;
        st->last_y = m.y;
        /* Keep hover motion in the host Wayland surface. Android receives
         * pointer movement only during a held-button drag. */
        return 0;
    }
    case AAAS_INPUT_SCROLL: {
        if (!st->focused) {
            adapter_log("unfocused_scroll_rejected", NULL);
            return 0;
        }
        st->last_x = m.x;
        st->last_y = m.y;
        uint32_t source = AAAS_SOURCE_MOUSE;
        uint32_t tool_type = AAAS_TOOL_MOUSE;
        switch (m.button) {
        case AAAS_INPUT_AXIS_SOURCE_FINGER:
        case AAAS_INPUT_AXIS_SOURCE_CONTINUOUS:
            source = AAAS_SOURCE_TOUCHPAD;
            tool_type = AAAS_TOOL_FINGER;
            break;
        case AAAS_INPUT_AXIS_SOURCE_WHEEL:
        case AAAS_INPUT_AXIS_SOURCE_WHEEL_TILT:
            break;
        default:
            adapter_log("scroll_bad_axis_source", NULL);
            return 0;
        }
        float v = (float)(int32_t)m.state / 120.0f;
        float h = (float)(int32_t)m.reserved / 120.0f;
        inject_request(st, AAAS_ACTION_SCROLL, m.x, m.y, source, tool_type,
                       0, 0, 0.0f, v, h, st->order.sequence, request_ns);
        return 0;
    }
    case AAAS_INPUT_AXIS_STOP: {
        st->last_x = m.x;
        st->last_y = m.y;
        adapter_logf("axis_stop", "\"mask\":%u,\"sequence\":%u,\"request_ns\":%llu,\"recv_ns\":%llu",
                     m.button, st->order.sequence,
                     (unsigned long long)request_ns,
                     (unsigned long long)recv_ns);
        return 0;
    }
    case AAAS_INPUT_BUTTON: {
        uint32_t bit = button_mask(m.button);
        if (!bit) {
            adapter_log("unsupported_button", NULL);
            return 0;
        }
        st->last_x = m.x;
        st->last_y = m.y;
        if (m.state == AAAS_INPUT_BUTTON_PRESSED) {
            if (st->pressed_buttons & bit) {
                adapter_log("duplicate_press", NULL);
                return 0;
            }
            uint32_t new_mask = st->pressed_buttons | bit;
            const uint32_t android_mask =
                    (new_mask & (1u << 0) ? AAAS_BUTTON_PRIMARY : 0) |
                    (new_mask & (1u << 1) ? AAAS_BUTTON_SECONDARY : 0) |
                    (new_mask & (1u << 2) ? AAAS_BUTTON_TERTIARY : 0);
            uint32_t android_button = bit == (1u << 0) ? AAAS_BUTTON_PRIMARY
                    : bit == (1u << 1) ? AAAS_BUTTON_SECONDARY : AAAS_BUTTON_TERTIARY;
            int action = android_button == AAAS_BUTTON_PRIMARY && st->pressed_buttons == 0
                    ? AAAS_ACTION_DOWN : AAAS_ACTION_BUTTON_PRESS;
            if (inject_request(st, action, m.x, m.y, AAAS_SOURCE_MOUSE,
                               AAAS_TOOL_MOUSE, android_mask, android_button, 1.0f, 0.0f, 0.0f,
                               st->order.sequence, request_ns) == 0) {
                st->pressed_buttons = new_mask;
            }
        } else {
            if (!(st->pressed_buttons & bit)) {
                adapter_log("release_without_press", NULL);
                return 0;
            }
            uint32_t remaining = st->pressed_buttons & ~bit;
            const uint32_t android_remaining =
                    (remaining & (1u << 0) ? AAAS_BUTTON_PRIMARY : 0) |
                    (remaining & (1u << 1) ? AAAS_BUTTON_SECONDARY : 0) |
                    (remaining & (1u << 2) ? AAAS_BUTTON_TERTIARY : 0);
            uint32_t android_button = bit == (1u << 0) ? AAAS_BUTTON_PRIMARY
                    : bit == (1u << 1) ? AAAS_BUTTON_SECONDARY : AAAS_BUTTON_TERTIARY;
            int action = remaining == 0 ? AAAS_ACTION_UP : AAAS_ACTION_BUTTON_RELEASE;
            if (inject_request(st, action, m.x, m.y, AAAS_SOURCE_MOUSE,
                               AAAS_TOOL_MOUSE, android_remaining, android_button, 0.0f, 0.0f, 0.0f,
                               st->order.sequence, request_ns) == 0) {
                st->pressed_buttons = remaining;
            }
        }
        return 0;
    }
    default:
        return 0;
    }
}

static void usage(const char *prog) {
    fprintf(stderr,
            "Usage: %s [options]\n"
            "  --socket <path>        input SEQPACKET socket (default: " DEFAULT_SOCKET ")\n"
            "  --session-file <path>  session token file (default: " DEFAULT_SESSION_FILE ")\n"
            "  --log <path>           JSON log path (default: " DEFAULT_LOG ")\n"
            "  --display <id>         Android target display id (default: 0)\n"
            "  --focus-request <path>  trusted Android task-focus request file\n"
            "  --focus-ack <path>      trusted Android task-focus acknowledgement file\n"
            "  --backend <auto|binder|cmd> input backend (default: auto)\n"
            "  --help                 show this help\n",
            prog);
}

int main(int argc, char **argv) {
    const char *socket_path = DEFAULT_SOCKET;
    const char *session_file = DEFAULT_SESSION_FILE;
    const char *log_path = DEFAULT_LOG;
    const char *backend_arg = NULL;
    const char *focus_request_path = NULL;
    const char *focus_ack_path = NULL;
    int display_id = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--socket") == 0 && i + 1 < argc) {
            socket_path = argv[++i];
        } else if (strcmp(argv[i], "--session-file") == 0 && i + 1 < argc) {
            session_file = argv[++i];
        } else if (strcmp(argv[i], "--log") == 0 && i + 1 < argc) {
            log_path = argv[++i];
        } else if (strcmp(argv[i], "--display") == 0 && i + 1 < argc) {
            int ok = 0;
            display_id = parse_int(argv[++i], &ok);
            if (!ok) {
                fprintf(stderr, "Invalid display id: %s\n", argv[i]);
                return 1;
            }
        } else if (strcmp(argv[i], "--focus-request") == 0 && i + 1 < argc) {
            focus_request_path = argv[++i];
        } else if (strcmp(argv[i], "--focus-ack") == 0 && i + 1 < argc) {
            focus_ack_path = argv[++i];
        } else if (strcmp(argv[i], "--backend") == 0 && i + 1 < argc) {
            backend_arg = argv[++i];
        } else if (strcmp(argv[i], "--help") == 0) {
            usage(argv[0]);
            return 0;
        } else {
            fprintf(stderr, "Unknown option: %s\n", argv[i]);
            usage(argv[0]);
            return 1;
        }
    }
    if (display_id < 0) {
        fprintf(stderr, "Android display id must be non-negative\n");
        return 1;
    }
    g_android_display_id = display_id;

    if (!backend_arg) {
        backend_arg = getenv("AAAS_INPUT_BACKEND");
    }
    if (backend_arg) {
        if (strcmp(backend_arg, "binder") == 0) {
            g_backend = INPUT_BACKEND_BINDER;
        } else if (strcmp(backend_arg, "cmd") == 0) {
            g_backend = INPUT_BACKEND_CMD;
        } else if (strcmp(backend_arg, "auto") == 0) {
            g_backend = INPUT_BACKEND_AUTO;
        } else {
            fprintf(stderr, "Invalid backend: %s\n", backend_arg);
            return 1;
        }
    }

    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGHUP, handle_signal);
    signal(SIGPIPE, SIG_IGN);

    g_log_fd = open(log_path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0666);
    if (g_log_fd < 0) {
        fprintf(stderr, "open log %s failed: %s\n", log_path, strerror(errno));
    }

    uint64_t session_id = read_session_id(session_file);
    if (!session_id) {
        adapter_log("session_unavailable", NULL);
        if (g_log_fd >= 0) close(g_log_fd);
        return 1;
    }

    adapter_logf("start",
                 "\"pid\":%ld,\"socket\":\"%s\",\"session\":\"%016llx\","
                 "\"display\":%d,\"backend\":\"%s\"",
                 (long)getpid(), socket_path,
                 (unsigned long long)session_id, display_id,
                 g_backend == INPUT_BACKEND_BINDER ? "binder"
                     : g_backend == INPUT_BACKEND_CMD ? "cmd" : "auto");

    int fd = connect_input_socket(socket_path);
    if (fd < 0) {
        adapter_log("connect_failed", NULL);
        if (g_log_fd >= 0) close(g_log_fd);
        return 1;
    }
    adapter_log("connected", NULL);

    adapter_state st;
    memset(&st, 0, sizeof(st));
    aaas_input_state_init(&st.order, session_id, (uint32_t)display_id);
    st.android_display_id = (uint32_t)display_id;
    st.selected_backend = g_backend;
    st.focus_request_path = focus_request_path;
    st.focus_ack_path = focus_ack_path;
    st.focus_instance_nonce = monotonic_ns() ^ ((uint64_t)(uint32_t)getpid() << 32);

    while (!g_stop) {
        struct pollfd p = { .fd = fd, .events = POLLIN, .revents = 0 };
        int r = poll(&p, 1, 200);
        if (r < 0) {
            if (errno == EINTR) continue;
            adapter_log("poll_failed", NULL);
            break;
        }
        if (r == 0) {
            continue;
        }
        if (p.revents & POLLIN) {
            union { aaas_input_msg pointer; aaas_input_keyboard_msg keyboard; } packet;
            ssize_t n = recv(fd, &packet, sizeof(packet), MSG_TRUNC);
            if (n <= 0) {
                adapter_log(n == 0 ? "disconnected" : "recv_failed", NULL);
                break;
            }
            int should_stop=0;
            if(n==(ssize_t)sizeof(aaas_input_msg)) {
                aaas_input_msg message;
                aaas_input_from_wire(&message,&packet.pointer);
                should_stop = message.type == AAAS_INPUT_SCROLL
                    ? handle_scroll_burst(fd, &st, &packet.pointer)
                    : handle_message(fd, &st, &packet.pointer);
            } else if(n==(ssize_t)sizeof(aaas_input_keyboard_msg)) {
                should_stop=handle_keyboard_message(&st,&packet.keyboard);
            } else {
                adapter_log("invalid_message_length",NULL);
                continue;
            }
            if (should_stop) {
                break;
            }
        }
        if (p.revents & (POLLHUP | POLLERR)) {
            adapter_log("socket_hangup", NULL);
            break;
        }
    }

    for(uint32_t k=0;k<768;k++) if(st.pressed_keys[k])
        (void)aaas_binder_inject_key(1,(int32_t)st.pressed_keycodes[k],(int32_t)k,
             0,0,(int64_t)monotonic_ns(),st.key_down_ns[k],g_android_display_id);
    release_all(&st, st.last_x, st.last_y, st.order.sequence, "adapter_exit");
    aaas_binder_shutdown();
    adapter_log("stop", NULL);
    close(fd);
    if (g_log_fd >= 0) close(g_log_fd);
    return 0;
}
