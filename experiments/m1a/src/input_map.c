#include "input_map.h"

#include <math.h>

aaas_mapped_point aaas_map_surface_to_display(double surface_x, double surface_y,
                                              uint32_t surface_w, uint32_t surface_h,
                                              uint32_t display_w, uint32_t display_h) {
    aaas_mapped_point out = { .x = 0, .y = 0, .inside = 0 };
    if (!surface_w || !surface_h || !display_w || !display_h) {
        return out;
    }

    double scale_x = (double)surface_w / (double)display_w;
    double scale_y = (double)surface_h / (double)display_h;
    double scale = fmin(scale_x, scale_y);
    if (!(scale > 0.0)) {
        return out;
    }

    double content_w = (double)display_w * scale;
    double content_h = (double)display_h * scale;
    double origin_x = ((double)surface_w - content_w) / 2.0;
    double origin_y = ((double)surface_h - content_h) / 2.0;

    if (surface_x < origin_x || surface_y < origin_y ||
        surface_x >= origin_x + content_w ||
        surface_y >= origin_y + content_h) {
        return out;
    }

    double display_x = (surface_x - origin_x) / scale;
    double display_y = (surface_y - origin_y) / scale;
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
