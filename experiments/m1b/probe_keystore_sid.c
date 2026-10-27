/* Diagnostic only: isolate Binder caller-SID dependency in Keystore2.
 * The host kernel has no SELinux LSM, so Binder cannot attach a caller SID.
 * Accept only the kernel-reported Android system UID. No cryptographic
 * operation is intercepted. This is not a production authorization backend.
 */
#include <stdbool.h>
#include <stdint.h>

extern int32_t AIBinder_getCallingUid(void);

void AIBinder_setRequestingSid(void *binder, bool requesting_sid) {
    (void)binder;
    (void)requesting_sid;
}

const char *AIBinder_getCallingSid(void) {
#ifdef AAAS_PROBE_NO_SID
    return (const char *)0;
#else
    return AIBinder_getCallingUid() == 1000 ? "u:r:system_server:s0" : (const char *)0;
#endif
}
