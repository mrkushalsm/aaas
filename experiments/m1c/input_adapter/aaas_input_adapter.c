/*
 * AaaS Android pointer input adapter.
 *
 * This is a deliberately small, persistent Android-side daemon.  It accepts
 * only the versioned AaaS pointer protocol on a private SEQPACKET socket and
 * feeds validated press/release/move events to Android's real input system
 * through the platform `cmd input` entry point.  `execv` is used with a fixed
 * argv; no shell, package names, or arbitrary commands are accepted.
 */

#include "input_v1.h"
#include "input_state.h"

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

static int ascii_digit(char c, int base) {
    int v;
    if (c >= '0' && c <= '9') v = c - '0';
    else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
    else if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
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
    char line[768];
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
    } else {
        ssize_t ignored = write(STDERR_FILENO, line, (size_t)n);
        (void)ignored;
    }
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
        usleep(5000);
    }
}

static int inject_event(const char *motion, int32_t x, int32_t y, uint32_t sequence) {
    char xs[16];
    char ys[16];
    snprintf(xs, sizeof(xs), "%d", x);
    snprintf(ys, sizeof(ys), "%d", y);

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
            (char *)"0",
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
    char extra[192];
    snprintf(extra, sizeof(extra),
             "\"motion\":\"%s\",\"x\":%d,\"y\":%d,\"sequence\":%u,\"rc\":%d",
             motion, x, y, sequence, rc);
    adapter_log(rc == 0 ? "inject" : "inject_failed", extra);
    return rc;
}

static void send_ack(int fd, const aaas_input_msg *hello, uint64_t session_id) {
    aaas_input_msg host = {
        .magic = AAAS_INPUT_MAGIC,
        .version = AAAS_INPUT_VERSION,
        .type = AAAS_INPUT_HELLO,
        .length = AAAS_INPUT_MSG_SIZE,
        .sequence = 0,
        .display_id = 0,
        .display_generation = hello->display_generation,
        .timestamp_ns = monotonic_ns(),
        .session_id = session_id,
        .x = hello->x,
        .y = hello->y,
        .button = 0,
        .state = 1,
        .focus_generation = hello->focus_generation,
        .flags = AAAS_INPUT_FLAG_ACK,
        .reserved = 0,
    };
    aaas_input_msg wire;
    aaas_input_to_wire(&wire, &host);
    ssize_t n = send(fd, &wire, sizeof(wire), MSG_NOSIGNAL);
    if (n != (ssize_t)sizeof(wire)) {
        adapter_log("hello_ack_failed", NULL);
    }
}

static void release_all(int fd, uint32_t *pressed, int32_t x, int32_t y,
                        uint32_t sequence, const char *reason) {
    (void)fd;
    static const uint32_t buttons[] = {
        AAAS_INPUT_BUTTON_LEFT,
        AAAS_INPUT_BUTTON_RIGHT,
        AAAS_INPUT_BUTTON_MIDDLE,
    };
    uint32_t mask = *pressed;
    if (!mask) {
        return;
    }
    for (unsigned i = 0; i < sizeof(buttons) / sizeof(buttons[0]); i++) {
        if (mask & button_mask(buttons[i])) {
            if (inject_event("UP", x, y, sequence) == 0) {
                *pressed &= ~button_mask(buttons[i]);
            }
        }
    }
    char extra[128];
    snprintf(extra, sizeof(extra), "\"reason\":\"%s\",\"remaining\":%u",
             reason, *pressed);
    adapter_log("buttons_released", extra);
}

typedef struct {
    aaas_input_state order;
    uint32_t pressed_buttons;
    int focused;
    int32_t last_x;
    int32_t last_y;
    unsigned invalid_messages;
} adapter_state;

static int handle_message(int fd, adapter_state *st, const aaas_input_msg *wire) {
    aaas_input_msg m;
    aaas_input_from_wire(&m, wire);

    char why[64] = {0};
    if (!aaas_input_state_accept(&st->order, &m, why, sizeof(why))) {
        st->invalid_messages++;
        char extra[128];
        snprintf(extra, sizeof(extra), "\"reason\":\"%s\",\"count\":%u",
                 why, st->invalid_messages);
        adapter_log("invalid_message", extra);
        return st->invalid_messages >= 8 ? 1 : 0;
    }

    if (m.type == AAAS_INPUT_HELLO) {
        send_ack(fd, &m, st->order.session_id);
        st->last_x = 0;
        st->last_y = 0;
        st->focused = 0;
        char extra[128];
        snprintf(extra, sizeof(extra),
                 "\"display_generation\":%u,\"width\":%d,\"height\":%d,\"sequence\":%u",
                 st->order.display_generation, m.x, m.y, st->order.sequence);
        adapter_log("hello", extra);
        return 0;
    }

    if (m.type == AAAS_INPUT_FOCUS) {
        st->last_x = m.x;
        st->last_y = m.y;
        if (m.state == AAAS_INPUT_FOCUS_ENTER) {
            st->focused = 1;
            adapter_log("focus_enter", NULL);
        } else {
            release_all(fd, &st->pressed_buttons, st->last_x, st->last_y,
                        st->order.sequence, "focus_leave");
            st->focused = 0;
            adapter_log("focus_leave", NULL);
        }
        return 0;
    }

    if (m.type == AAAS_INPUT_SHUTDOWN) {
        release_all(fd, &st->pressed_buttons, st->last_x, st->last_y,
                    st->order.sequence, "shutdown");
        adapter_log("shutdown_received", NULL);
        return 1;
    }

    if (!st->focused) {
        adapter_log("unfocused_event_rejected", NULL);
        return 0;
    }

    if (m.type == AAAS_INPUT_MOTION) {
        st->last_x = m.x;
        st->last_y = m.y;
        char extra[128];
        snprintf(extra, sizeof(extra), "\"x\":%d,\"y\":%d,\"pressed\":%u",
                 m.x, m.y, st->pressed_buttons);
        adapter_log("motion", extra);
        if (st->pressed_buttons) {
            inject_event("MOVE", m.x, m.y, st->order.sequence);
        }
        return 0;
    }

    if (m.type == AAAS_INPUT_BUTTON) {
        uint32_t mask = button_mask(m.button);
        if (!mask) {
            adapter_log("unsupported_button", NULL);
            return 0;
        }
        st->last_x = m.x;
        st->last_y = m.y;
        if (m.state == AAAS_INPUT_BUTTON_PRESSED) {
            if (st->pressed_buttons & mask) {
                adapter_log("duplicate_press", NULL);
                return 0;
            }
            inject_event("MOVE", m.x, m.y, st->order.sequence);
            if (inject_event("DOWN", m.x, m.y, st->order.sequence) == 0) {
                st->pressed_buttons |= mask;
            }
        } else {
            if (!(st->pressed_buttons & mask)) {
                adapter_log("release_without_press", NULL);
                return 0;
            }
            if (inject_event("UP", m.x, m.y, st->order.sequence) == 0) {
                st->pressed_buttons &= ~mask;
            }
        }
        return 0;
    }

    return 0;
}

static void usage(const char *prog) {
    fprintf(stderr,
            "Usage: %s [options]\n"
            "  --socket <path>        input SEQPACKET socket (default: " DEFAULT_SOCKET ")\n"
            "  --session-file <path>  session token file (default: " DEFAULT_SESSION_FILE ")\n"
            "  --log <path>           JSON log path (default: " DEFAULT_LOG ")\n"
            "  --display <id>         Android display id (default: 0)\n"
            "  --help                 show this help\n",
            prog);
}

int main(int argc, char **argv) {
    const char *socket_path = DEFAULT_SOCKET;
    const char *session_file = DEFAULT_SESSION_FILE;
    const char *log_path = DEFAULT_LOG;
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
        } else if (strcmp(argv[i], "--help") == 0) {
            usage(argv[0]);
            return 0;
        } else {
            fprintf(stderr, "Unknown option: %s\n", argv[i]);
            usage(argv[0]);
            return 1;
        }
    }
    if (display_id != 0) {
        fprintf(stderr, "This adapter only supports the AaaS display 0\n");
        return 1;
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

    char start_extra[192];
    snprintf(start_extra, sizeof(start_extra),
             "\"pid\":%ld,\"socket\":\"%s\",\"session\":\"%016llx\",\"display\":%d",
             (long)getpid(), socket_path, (unsigned long long)session_id, display_id);
    adapter_log("start", start_extra);

    int fd = connect_input_socket(socket_path);
    if (fd < 0) {
        adapter_log("connect_failed", NULL);
        if (g_log_fd >= 0) close(g_log_fd);
        return 1;
    }
    adapter_log("connected", NULL);

    adapter_state st;
    memset(&st, 0, sizeof(st));
    aaas_input_state_init(&st.order, session_id);

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
            aaas_input_msg wire;
            ssize_t n = recv(fd, &wire, sizeof(wire), MSG_TRUNC);
            if (n <= 0) {
                adapter_log(n == 0 ? "disconnected" : "recv_failed", NULL);
                break;
            }
            if (n != (ssize_t)sizeof(wire)) {
                adapter_log("invalid_message_length", NULL);
                continue;
            }
            if (handle_message(fd, &st, &wire)) {
                break;
            }
        }
        if (p.revents & (POLLHUP | POLLERR)) {
            adapter_log("socket_hangup", NULL);
            break;
        }
    }

    release_all(fd, &st.pressed_buttons, st.last_x, st.last_y,
                st.order.sequence, "adapter_exit");
    adapter_log("stop", NULL);
    close(fd);
    if (g_log_fd >= 0) close(g_log_fd);
    return 0;
}
