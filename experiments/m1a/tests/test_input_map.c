#include "input_map.h"

#include <stdio.h>
#include <stdlib.h>

static int failures;

static void expect_point(const char *name, double sx, double sy,
                         uint32_t sw, uint32_t sh, uint32_t dw, uint32_t dh,
                         int inside, int32_t ex, int32_t ey) {
    aaas_mapped_point p = aaas_map_surface_to_display(sx, sy, sw, sh, dw, dh);
    if (p.inside != inside || (!inside ? 0 : (p.x != ex || p.y != ey))) {
        fprintf(stderr,
                "FAIL %s: got inside=%d x=%d y=%d expected inside=%d x=%d y=%d\n",
                name, p.inside, p.x, p.y, inside, ex, ey);
        failures++;
    } else {
        printf("PASS %s: inside=%d x=%d y=%d\n", name, p.inside, p.x, p.y);
    }
}

int main(void) {
    /* Identical dimensions. */
    expect_point("identical-origin", 0, 0, 1280, 720, 1280, 720, 1, 0, 0);
    expect_point("identical-center", 640, 360, 1280, 720, 1280, 720, 1, 640, 360);
    expect_point("identical-last-pixel", 1279, 719, 1280, 720, 1280, 720, 1, 1279, 719);
    expect_point("identical-right-edge", 1280, 719, 1280, 720, 1280, 720, 0, 0, 0);
    expect_point("identical-negative", -1, 0, 1280, 720, 1280, 720, 0, 0, 0);

    /* Half-size surface. */
    expect_point("half-origin", 0, 0, 640, 360, 1280, 720, 1, 0, 0);
    expect_point("half-center", 320, 180, 640, 360, 1280, 720, 1, 640, 360);
    expect_point("half-last-pixel", 639.9, 359.9, 640, 360, 1280, 720, 1, 1279, 719);

    /* Default AaaS phone window over an independent 720x1280 Android source. */
    expect_point("phone-window-top-left", 0, 0, 420, 740, 720, 1280, 1, 0, 0);
    expect_point("phone-window-center", 210, 370, 420, 740, 720, 1280, 1, 360, 640);
    expect_point("phone-window-bottom-right", 419.9, 739.9, 420, 740,
                 720, 1280, 1, 719, 1279);

    /* Double-size surface. */
    expect_point("double-center", 1280, 720, 2560, 1440, 1280, 720, 1, 640, 360);
    expect_point("double-last-pixel", 2559.9, 1439.9, 2560, 1440, 1280, 720, 1, 1279, 719);

    /* wp_viewport stretches the full active buffer to the surface destination. */
    expect_point("wide-surface-left-corner", 0, 0, 950, 1100, 720, 1280, 1, 0, 0);
    expect_point("wide-surface-right-corner", 949.9, 0, 950, 1100, 720, 1280, 1, 719, 0);
    expect_point("wide-surface-center", 475, 550, 950, 1100, 720, 1280, 1, 360, 640);
    expect_point("wide-surface-bottom-right", 949.9, 1099.9, 950, 1100, 720, 1280, 1, 719, 1279);
    expect_point("short-surface-top-right", 959.9, 0, 960, 578, 960, 578, 1, 959, 0);
    expect_point("odd-height-bottom-right", 959.9, 556.9, 960, 557, 960, 557, 1, 959, 556);
    expect_point("landscape-bottom-right", 1279.9, 719.9, 1280, 720, 1280, 720, 1, 1279, 719);

    /* Degenerate and future resize generations. */
    expect_point("zero-surface", 0, 0, 0, 0, 1280, 720, 0, 0, 0);
    expect_point("zero-display", 0, 0, 1280, 720, 0, 0, 0, 0, 0);

    if (!aaas_presented_geometry_ready(960, 578, 960, 578)) {
        fprintf(stderr, "FAIL matching frame must enable input\n");
        failures++;
    }
    if (aaas_presented_geometry_ready(960, 565, 960, 557)) {
        fprintf(stderr, "FAIL stale frame must disable input during configure\n");
        failures++;
    }
    if (aaas_presented_geometry_ready(720, 1280, 960, 565)) {
        fprintf(stderr, "FAIL resize-back must remain gated until matching frame\n");
        failures++;
    }

    if (failures) {
        fprintf(stderr, "%d input mapping test(s) failed\n", failures);
        return 1;
    }
    printf("all input mapping tests passed\n");
    return 0;
}
