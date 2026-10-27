#include <assert.h>
#include <stdint.h>
#include <string.h>

static int32_t caller_uid;
int32_t AIBinder_getCallingUid(void) { return caller_uid; }

#include "probe_keystore_sid.c"

int main(void) {
    caller_uid = 1000;
    AIBinder_setRequestingSid(0, true);
    assert(strcmp(AIBinder_getCallingSid(), "u:r:system_server:s0") == 0);
    caller_uid = 0;
    assert(AIBinder_getCallingSid() == 0);
    caller_uid = 10000;
    assert(AIBinder_getCallingSid() == 0);
    return 0;
}
