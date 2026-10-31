#include "input_map.h"

#include <math.h>

aaas_mapped_point aaas_map_surface_to_display(double surface_x, double surface_y,
                                              uint32_t surface_w, uint32_t surface_h,
                                              uint32_t display_w, uint32_t display_h) {
    aaas_mapped_point out = { .x = 0, .y = 0, .inside = 0 };
    if (!surface_w || !surface_h || !display_w || !display_h) {
        return out;
    }

    if (surface_x < 0.0 || surface_y < 0.0 ||
        surface_x >= (double)surface_w || surface_y >= (double)surface_h) {
        return out;
    }

    /* wp_viewport scales the full source rectangle independently on each
     * axis to the destination size. Preserve that exact transform here. */
    double display_x = surface_x * (double)display_w / (double)surface_w;
    double display_y = surface_y * (double)display_h / (double)surface_h;
    int32_t x = (int32_t)floor(display_x);
    int32_t y = (int32_t)floor(display_y);
    if (x < 0) x = 0;
    if (y < 0) y = 0;
    if ((uint32_t)x >= display_w) x = (int32_t)display_w - 1;
    if ((uint32_t)y >= display_h) y = (int32_t)display_h - 1;

    out.x = x;
    out.y = y;
    out.inside = 1;
    return out;
}

int aaas_presented_geometry_ready(uint32_t surface_w, uint32_t surface_h,
                                  uint32_t frame_w, uint32_t frame_h) {
    return surface_w != 0 && surface_h != 0 &&
           frame_w == surface_w && frame_h == surface_h;
}
