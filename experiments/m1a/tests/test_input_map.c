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

    /* Double-size surface. */
    expect_point("double-center", 1280, 720, 2560, 1440, 1280, 720, 1, 640, 360);
    expect_point("double-last-pixel", 2559.9, 1439.9, 2560, 1440, 1280, 720, 1, 1279, 719);

    /* Nonuniform surface: preserve aspect ratio and letterbox the sides. */
    expect_point("letterbox-left-bar", 50, 300, 1280, 600, 1280, 720, 0, 0, 0);
    expect_point("letterbox-right-bar", 1200, 300, 1280, 600, 1280, 720, 0, 0, 0);
    expect_point("letterbox-content-center", 640, 300, 1280, 600, 1280, 720, 1, 640, 360);
    expect_point("letterbox-content-left", 106.7, 300, 1280, 600, 1280, 720, 1, 0, 360);

    /* Nonuniform surface: top/bottom letterboxing. */
    expect_point("vertical-bar-top", 400, 20, 800, 600, 1280, 720, 0, 0, 0);
    expect_point("vertical-bar-bottom", 400, 580, 800, 600, 1280, 720, 0, 0, 0);
    expect_point("vertical-content-center", 400, 300, 800, 600, 1280, 720, 1, 640, 360);

    /* Degenerate and future resize generations. */
    expect_point("zero-surface", 0, 0, 0, 0, 1280, 720, 0, 0, 0);
    expect_point("zero-display", 0, 0, 1280, 720, 0, 0, 0, 0, 0);

    if (failures) {
        fprintf(stderr, "%d input mapping test(s) failed\n", failures);
        return 1;
    }
    printf("all input mapping tests passed\n");
    return 0;
}
