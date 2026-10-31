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
 * The presenter uses wp_viewport_set_destination() for the complete buffer,
 * so the active buffer is stretched to the configured Wayland surface. Map
 * each axis independently to match that presentation. Coordinates are floored
 * and clamped to display bounds; an exact right/bottom edge is outside.
 */
aaas_mapped_point aaas_map_surface_to_display(double surface_x, double surface_y,
                                              uint32_t surface_w, uint32_t surface_h,
                                              uint32_t display_w, uint32_t display_h);

/* Input is valid only when the currently displayed Android frame matches the
 * configured surface. During Android resize the old buffer remains visible
 * through the viewport; its pixel coordinates are not valid coordinates in
 * the newly resized Android display, so callers must reject input until the
 * first matching-generation buffer is active.
 */
int aaas_presented_geometry_ready(uint32_t surface_w, uint32_t surface_h,
                                  uint32_t frame_w, uint32_t frame_h);

#endif /* AAAS_INPUT_MAP_H */
