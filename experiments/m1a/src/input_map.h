#ifndef AAAS_INPUT_MAP_H
#define AAAS_INPUT_MAP_H

#include <stdint.h>

typedef struct {
    int32_t x;
    int32_t y;
    int inside;
} aaas_mapped_point;

/*
 * Map a Wayland surface-local coordinate to Android display pixels.
 *
 * The Android display is fitted into the host surface while preserving its
 * aspect ratio.  Any unused surface area is treated as letterboxing and is
 * outside the mapped region.  Coordinates are floored and clamped to the
 * display bounds; an exact right/bottom edge is outside.
 */
aaas_mapped_point aaas_map_surface_to_display(double surface_x, double surface_y,
                                              uint32_t surface_w, uint32_t surface_h,
                                              uint32_t display_w, uint32_t display_h);

#endif /* AAAS_INPUT_MAP_H */
