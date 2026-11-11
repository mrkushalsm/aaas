#include <assert.h>
#include <errno.h>
#include <stdlib.h>

int *__errno(void) { return &errno; }

#include "../experiments/m1b/selinux_xattr_compat.c"

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
    return 0;
}
