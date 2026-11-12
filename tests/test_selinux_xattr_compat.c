#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int *__errno(void) { return &errno; }
int __openat_2(int dirfd, const char *path, int flags);

#define AAAS_PROC_CONFIG_GZ_PATH "proc/config.gz"
#include "../experiments/m1b/selinux_xattr_compat.c"

static void write_file(const char *path, const char *contents) {
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    assert(fd >= 0);
    size_t length = strlen(contents);
    assert(write(fd, contents, length) == (ssize_t)length);
    assert(close(fd) == 0);
}

static void assert_file_contents(int fd, const char *expected) {
    char actual[64] = {0};
    ssize_t count = read(fd, actual, sizeof(actual) - 1);
    assert(count == (ssize_t)strlen(expected));
    assert(memcmp(actual, expected, (size_t)count) == 0);
    assert(close(fd) == 0);
}

int main(void) {
    static const char android_property_context[] = "u:object_r:system_prop:s0";
    static const char android_domain_context[] = "u:r:init:s0";
    static const char malformed_context[] = "not-an-android-context";

    assert(ignore_invalid_android_label(
        -22, "security.selinux", android_property_context,
        sizeof(android_property_context), 0));
    assert(ignore_invalid_android_label(
        -22, "security.selinux", android_domain_context,
        sizeof(android_domain_context), 0));

    assert(!ignore_invalid_android_label(
        -1, "security.selinux", android_property_context,
        sizeof(android_property_context), 0));
    assert(!ignore_invalid_android_label(
        -22, "user.comment", android_property_context,
        sizeof(android_property_context), 0));
    assert(!ignore_invalid_android_label(
        -22, "security.selinux", malformed_context,
        sizeof(malformed_context), 0));
    assert(!ignore_invalid_android_label(
        -22, "security.selinux", android_property_context,
        sizeof(android_property_context), 1));
    assert(!ignore_invalid_android_label(
        -22, "security.selinux", "u:object_r:unterminated", 8, 0));

    char directory[] = "/tmp/aaas-kernel-config-XXXXXX";
    assert(mkdtemp(directory) != NULL);
    int original_cwd = open(".", O_RDONLY | O_DIRECTORY);
    assert(original_cwd >= 0);
    assert(chdir(directory) == 0);
    assert(mkdir("proc", 0700) == 0);
    write_file("kernel.config.gz", "fallback-config");
    assert(setenv("AAAS_KERNEL_CONFIG_GZ", "kernel.config.gz", 1) == 0);
    assert(open_kernel_config_fallback(-100, AAAS_PROC_CONFIG_GZ_PATH,
                                       O_RDONLY, 0, -13) == -13);
    assert(open_kernel_config_fallback(3, AAAS_PROC_CONFIG_GZ_PATH,
                                       O_RDONLY, 0, -2) == -2);
    int fd = open(AAAS_PROC_CONFIG_GZ_PATH, O_RDONLY);
    assert(fd >= 0);
    assert_file_contents(fd, "fallback-config");
    fd = __openat_2(-100, AAAS_PROC_CONFIG_GZ_PATH, O_RDONLY);
    assert(fd >= 0);
    assert_file_contents(fd, "fallback-config");

    write_file(AAAS_PROC_CONFIG_GZ_PATH, "proc-config");
    fd = open(AAAS_PROC_CONFIG_GZ_PATH, O_RDONLY);
    assert(fd >= 0);
    assert_file_contents(fd, "proc-config");

    assert(unlink(AAAS_PROC_CONFIG_GZ_PATH) == 0);
    assert(setenv("AAAS_KERNEL_CONFIG_GZ", "", 1) == 0);
    errno = 0;
    assert(open(AAAS_PROC_CONFIG_GZ_PATH, O_RDONLY) == -1);
    assert(errno == ENOENT);
    assert(unlink("kernel.config.gz") == 0);
    assert(rmdir("proc") == 0);
    assert(fchdir(original_cwd) == 0);
    assert(close(original_cwd) == 0);
    assert(rmdir(directory) == 0);
    return 0;
}
