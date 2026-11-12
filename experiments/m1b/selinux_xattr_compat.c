/* Narrow Android SELinux-xattr and kernel-config compatibility preload. */

extern int *__errno(void) __attribute__((weak));
extern char *getenv(const char *name) __attribute__((weak));
static int same_string(const char *left, const char *right);

#ifndef AAAS_PROC_CONFIG_GZ_PATH
#define AAAS_PROC_CONFIG_GZ_PATH "/proc/config.gz"
#endif
#ifndef AAAS_KERNEL_CONFIG_GZ_ENV
#define AAAS_KERNEL_CONFIG_GZ_ENV "AAAS_KERNEL_CONFIG_GZ"
#endif

static long raw_openat(int dirfd, const char *path, int flags, unsigned int mode) {
    register long r10 __asm__("r10") = (long)mode;
    long result;
    __asm__ volatile (
        "syscall"
        : "=a" (result)
        : "a" (257), "D" ((long)dirfd), "S" (path), "d" ((long)flags), "r" (r10)
        : "rcx", "r11", "memory"
    );
    return result;
}

static int finish_open(long result) {
    if (result < 0) {
        if (__errno) *__errno() = (int)(-result);
        return -1;
    }
    return (int)result;
}

static long open_kernel_config_fallback(int dirfd, const char *path, int flags,
                                        unsigned int mode, long original_result) {
    if (original_result != -2 || dirfd != -100 ||
            (flags & 3) != 0 || (flags & 0100) != 0 ||
            (flags & 020000000) == 020000000 ||
            !same_string(path, AAAS_PROC_CONFIG_GZ_PATH) || !getenv) {
        return original_result;
    }
    const char *fallback = getenv(AAAS_KERNEL_CONFIG_GZ_ENV);
    if (!fallback || !*fallback) return original_result;
    return raw_openat(-100, fallback, flags, mode);
}

static unsigned int open_mode_argument(int flags, __builtin_va_list args) {
    /* O_CREAT and O_TMPFILE are the only open flags that consume a mode. */
    if ((flags & 0100) || ((flags & 020000000) == 020000000))
        return __builtin_va_arg(args, unsigned int);
    return 0;
}

static long openat_with_config_fallback(int dirfd, const char *path, int flags,
                                        unsigned int mode) {
    long result = raw_openat(dirfd, path, flags, mode);
    return open_kernel_config_fallback(dirfd, path, flags, mode, result);
}

int openat(int dirfd, const char *path, int flags, ...) {
    __builtin_va_list args;
    __builtin_va_start(args, flags);
    unsigned int mode = open_mode_argument(flags, args);
    __builtin_va_end(args);
    return finish_open(openat_with_config_fallback(dirfd, path, flags, mode));
}

int openat64(int dirfd, const char *path, int flags, ...) {
    __builtin_va_list args;
    __builtin_va_start(args, flags);
    unsigned int mode = open_mode_argument(flags, args);
    __builtin_va_end(args);
    return finish_open(openat_with_config_fallback(dirfd, path, flags, mode));
}

int open(const char *path, int flags, ...) {
    __builtin_va_list args;
    __builtin_va_start(args, flags);
    unsigned int mode = open_mode_argument(flags, args);
    __builtin_va_end(args);
    return finish_open(openat_with_config_fallback(-100, path, flags, mode));
}

int open64(const char *path, int flags, ...) {
    __builtin_va_list args;
    __builtin_va_start(args, flags);
    unsigned int mode = open_mode_argument(flags, args);
    __builtin_va_end(args);
    return finish_open(openat_with_config_fallback(-100, path, flags, mode));
}

int __openat_2(int dirfd, const char *path, int flags) {
    return finish_open(openat_with_config_fallback(dirfd, path, flags, 0));
}

int __openat64_2(int dirfd, const char *path, int flags) {
    return finish_open(openat_with_config_fallback(dirfd, path, flags, 0));
}

int __open_2(const char *path, int flags) {
    return finish_open(openat_with_config_fallback(-100, path, flags, 0));
}

int __open64_2(const char *path, int flags) {
    return finish_open(openat_with_config_fallback(-100, path, flags, 0));
}

static int same_string(const char *left, const char *right) {
    if (!left || !right) return 0;
    while (*left && *left == *right) {
        left++;
        right++;
    }
    return *left == '\0' && *right == '\0';
}

static int starts_with(const char *value, const char *prefix) {
    if (!value || !prefix) return 0;
    while (*prefix) {
        if (*value++ != *prefix++) return 0;
    }
    return 1;
}

static int is_android_context(const void *value, unsigned long size) {
    const char *context = (const char *)value;
    if (!context || size < 2 || size > 256 || context[size - 1] != '\0') return 0;
    for (unsigned long i = 0; i + 1 < size; i++) {
        if (context[i] == '\0') return 0;
    }
    return starts_with(context, "u:object_r:") || starts_with(context, "u:r:");
}

static int ignore_invalid_android_label(long result, const char *name,
                                        const void *value, unsigned long size,
                                        int flags) {
    return result == -22 && flags == 0 && same_string(name, "security.selinux") &&
           is_android_context(value, size);
}

int fsetxattr(int fd, const char *name, const void *value,
              unsigned long size, int flags) {
    register long r10 __asm__("r10") = (long)size;
    register long r8 __asm__("r8") = (long)flags;
    long result;
    __asm__ volatile (
        "syscall"
        : "=a" (result)
        : "a" (190), "D" (fd), "S" (name), "d" (value), "r" (r10), "r" (r8)
        : "rcx", "r11", "memory"
    );

    /* Fedora's SELinux policy rejects Android's property types with EINVAL.
     * This diagnostic profile has no Android SELinux enforcement, so only
     * that expected label failure is treated as a no-op. */
    if (ignore_invalid_android_label(result, name, value, size, flags)) return 0;
    if (result < 0) {
        if (__errno) *__errno() = (int)(-result);
        return -1;
    }
    return (int)result;
}
