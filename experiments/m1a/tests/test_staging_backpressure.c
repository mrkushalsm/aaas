#include "staging_backpressure.h"

#include <assert.h>
#include <stdio.h>

int main(void) {
    assert(aaas_staging_can_complete_source_copy(0));
    assert(aaas_staging_can_complete_source_copy(1));
    assert(!aaas_staging_can_complete_source_copy(2));
    assert(!aaas_staging_can_complete_source_copy(32));

    assert(aaas_staging_can_import(0));
    assert(aaas_staging_can_import(1));
    assert(aaas_staging_can_import(2));
    assert(aaas_staging_can_import(3));
    assert(!aaas_staging_can_import(4));
    assert(!aaas_staging_can_import(32));
    puts("staging backpressure limits passed");
    return 0;
}
