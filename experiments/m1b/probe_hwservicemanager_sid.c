/* Diagnostic only: test HIDL manager's caller-SID dependency on non-SELinux hosts.
 * Scoped to hwservicemanager through its init service environment.
 * Do not deploy as a production authorization policy.
 */
#include <stdbool.h>

bool aaas_probe_hidl_set_requesting_sid(const void *service, bool requesting)
    __asm__("_ZN7android8hardware16setRequestingSidERKNS_2spINS_4hidl4base4V1_05IBaseEEEb");

bool aaas_probe_hidl_set_requesting_sid(const void *service, bool requesting) {
    (void)service;
    (void)requesting;
    return true;
}
