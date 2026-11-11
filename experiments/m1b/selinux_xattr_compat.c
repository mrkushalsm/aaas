/* Narrow xattr compatibility for the diagnostic Android 16 runtime. */

extern int *__errno(void) __attribute__((weak));

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
