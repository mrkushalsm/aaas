/*
 * Test-only property and socket shim for the isolated LMKD selection probe.
 *
 * The shim is preloaded into a disposable LMKD process. It enables the
 * low-RAM kill path so that a bounded cgroup PSI event reaches victim
 * selection while the host still has plenty of free memory, and it lets the
 * probe create LMKD's control socket at a path instead of inheriting an fd
 * from Android init. It is never loaded by the production runtime.
 *
 * Minimal libc declarations keep this shim buildable with the same exact
 * Bionic include set as LMKD without pulling host glibc headers.
 */

#include <stdint.h>

typedef unsigned int socklen_t;

struct sockaddr {
    unsigned short sa_family;
    char sa_data[14];
};

struct sockaddr_un {
    unsigned short sun_family;
    char sun_path[108];
};

extern int socket(int domain, int type, int protocol);
extern int bind(int fd, const struct sockaddr* address, socklen_t length);
extern int setsockopt(int fd, int level, int option, const void* value,
                      socklen_t length);
extern int close(int fd);
extern int unlink(const char* path);
extern char* getenv(const char* name);
extern unsigned long strlen(const char* text);
extern int strcmp(const char* left, const char* right);
extern char* strcpy(char* destination, const char* source);
extern void* memset(void* destination, int value, unsigned long length);
extern int vsnprintf(char* buffer, unsigned long size, const char* format,
                     __builtin_va_list arguments);
extern long write(int fd, const void* buffer, unsigned long count);

#define AF_UNIX 1
#define SOCK_SEQPACKET 5
#define SOL_SOCKET 1
#define SO_PASSCRED 16

static int is_key(const char* key, const char* expected) {
    return key != NULL && strcmp(key, expected) == 0;
}

int8_t property_get_bool(const char* key, int8_t default_value) {
    if (is_key(key, "ro.config.low_ram")) return 1;
    if (is_key(key, "ro.config.per_app_memcg")) return 0;
    if (is_key(key, "persist.device_config.lmkd_native.debug")) return 1;
    return default_value;
}

int32_t property_get_int32(const char* key, int32_t default_value) {
    /* Test-only thresholds: real LMKD selection runs unchanged, but the
     * bounded cgroup stall is far shorter than a real device-wide stall. */
    if (is_key(key, "ro.lmk.psi_complete_stall_ms")) return 20;
    return default_value;
}

int64_t property_get_int64(const char* key, int64_t default_value) {
    (void)key;
    return default_value;
}

int __android_log_print(int priority, const char* tag, const char* format, ...) {
    char buffer[1024];
    int length;
    __builtin_va_list arguments;
    __builtin_va_start(arguments, format);
    length = vsnprintf(buffer, sizeof(buffer), format, arguments);
    __builtin_va_end(arguments);
    if (length < 0) return -1;
    write(2, "lmkd-shim: ", 11);
    write(2, buffer, (unsigned long)length < sizeof(buffer)
                         ? (unsigned long)length : sizeof(buffer) - 1);
    write(2, "\n", 1);
    (void)priority;
    (void)tag;
    return length;
}

int __android_log_write(int priority, const char* tag, const char* text) {
    (void)priority;
    (void)tag;
    write(2, "lmkd-shim: ", 11);
    write(2, text, strlen(text));
    write(2, "\n", 1);
    return (int)strlen(text);
}

int android_get_control_socket(const char* name) {
    (void)name;
    const char* path = getenv("AAAS_TEST_LMKD_SOCKET");
    if (path == NULL) return -1;
    int fd = socket(AF_UNIX, SOCK_SEQPACKET, 0);
    if (fd < 0) return -1;
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    if (strlen(path) >= sizeof(address.sun_path)) {
        close(fd);
        return -1;
    }
    strcpy(address.sun_path, path);
    unlink(path);
    if (bind(fd, (const struct sockaddr*)&address, sizeof(address)) < 0) {
        close(fd);
        return -1;
    }
    int enabled = 1;
    setsockopt(fd, SOL_SOCKET, SO_PASSCRED, &enabled, sizeof(enabled));
    return fd;
}
