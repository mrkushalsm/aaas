#include "input_v1.h"

#include <endian.h>
#include <stdio.h>
#include <string.h>

_Static_assert(sizeof(aaas_input_msg) == 68, "unexpected aaas_input_msg size");
_Static_assert(sizeof(aaas_input_keyboard_msg) == 72, "unexpected keyboard packet size");
static int fail(char *why, size_t why_len, const char *reason);

void aaas_input_keyboard_to_wire(aaas_input_keyboard_msg *w,
                                const aaas_input_keyboard_msg *h) {
    w->magic=htole32(h->magic); w->version=htole16(h->version); w->type=htole16(h->type);
    w->length=htole32(h->length); w->sequence=htole32(h->sequence);
    w->display_id=htole32(h->display_id); w->display_generation=htole32(h->display_generation);
    w->timestamp_ns=htole64(h->timestamp_ns); w->session_id=htole64(h->session_id);
    w->focus_generation=htole32(h->focus_generation); w->evdev_key=htole32(h->evdev_key);
    w->android_keycode=htole32(h->android_keycode); w->state=htole32(h->state);
    w->meta_state=htole32(h->meta_state); w->repeat_count=htole32(h->repeat_count);
    w->keysym=htole32(h->keysym); w->unicode_scalar=htole32(h->unicode_scalar);
}

void aaas_input_keyboard_from_wire(aaas_input_keyboard_msg *h,
                                   const aaas_input_keyboard_msg *w) {
    h->magic=le32toh(w->magic); h->version=le16toh(w->version); h->type=le16toh(w->type);
    h->length=le32toh(w->length); h->sequence=le32toh(w->sequence);
    h->display_id=le32toh(w->display_id); h->display_generation=le32toh(w->display_generation);
    h->timestamp_ns=le64toh(w->timestamp_ns); h->session_id=le64toh(w->session_id);
    h->focus_generation=le32toh(w->focus_generation); h->evdev_key=le32toh(w->evdev_key);
    h->android_keycode=le32toh(w->android_keycode); h->state=le32toh(w->state);
    h->meta_state=le32toh(w->meta_state); h->repeat_count=le32toh(w->repeat_count);
    h->keysym=le32toh(w->keysym); h->unicode_scalar=le32toh(w->unicode_scalar);
}

int aaas_input_keyboard_validate(const aaas_input_keyboard_msg *m,
                                uint64_t session_id, uint32_t display_id,
                                char *why, size_t why_len) {
    if(m->magic!=AAAS_INPUT_MAGIC) return fail(why,why_len,"bad magic");
    if(m->version!=AAAS_INPUT_KEYBOARD_VERSION) return fail(why,why_len,"bad keyboard version");
    if(m->length!=AAAS_INPUT_KEYBOARD_MSG_SIZE) return fail(why,why_len,"bad keyboard length");
    if(m->session_id!=session_id) return fail(why,why_len,"stale session");
    if(m->display_id!=display_id || m->display_id>=AAAS_INPUT_MAX_DISPLAY)
        return fail(why,why_len,"wrong display");
    if(!m->display_generation) return fail(why,why_len,"missing display generation");
    if(!m->timestamp_ns) return fail(why,why_len,"missing timestamp");
    if(m->type!=AAAS_INPUT_KEYBOARD_FOCUS && m->type!=AAAS_INPUT_KEY)
        return fail(why,why_len,"bad keyboard type");
    if(m->type==AAAS_INPUT_KEYBOARD_FOCUS) {
        if(m->state!=AAAS_INPUT_FOCUS_LEAVE && m->state!=AAAS_INPUT_FOCUS_ENTER)
            return fail(why,why_len,"bad keyboard focus state");
        if(m->evdev_key || m->android_keycode || m->repeat_count || m->keysym || m->unicode_scalar)
            return fail(why,why_len,"focus packet contains key data");
    } else {
        if(m->evdev_key>=768 || !m->android_keycode || m->android_keycode>300)
            return fail(why,why_len,"bad key identity");
        if(m->state!=AAAS_INPUT_KEY_PRESSED && m->state!=AAAS_INPUT_KEY_RELEASED)
            return fail(why,why_len,"bad key state");
        if(m->repeat_count>100 || (m->state==AAAS_INPUT_KEY_RELEASED && m->repeat_count))
            return fail(why,why_len,"bad repeat count");
        if(m->unicode_scalar>0x10ffff || (m->unicode_scalar>=0xd800 && m->unicode_scalar<=0xdfff))
            return fail(why,why_len,"bad unicode scalar");
    }
    return 0;
}

void aaas_input_to_wire(aaas_input_msg *wire, const aaas_input_msg *host) {
    wire->magic = htole32(host->magic);
    wire->version = htole16(host->version);
    wire->type = htole16(host->type);
    wire->length = htole32(host->length);
    wire->sequence = htole32(host->sequence);
    wire->display_id = htole32(host->display_id);
    wire->display_generation = htole32(host->display_generation);
    wire->timestamp_ns = htole64(host->timestamp_ns);
    wire->session_id = htole64(host->session_id);
    wire->x = (int32_t)htole32((uint32_t)host->x);
    wire->y = (int32_t)htole32((uint32_t)host->y);
    wire->button = htole32(host->button);
    wire->state = htole32(host->state);
    wire->focus_generation = htole32(host->focus_generation);
    wire->flags = htole32(host->flags);
    wire->reserved = htole32(host->reserved);
}

void aaas_input_from_wire(aaas_input_msg *host, const aaas_input_msg *wire) {
    host->magic = le32toh(wire->magic);
    host->version = le16toh(wire->version);
    host->type = le16toh(wire->type);
    host->length = le32toh(wire->length);
    host->sequence = le32toh(wire->sequence);
    host->display_id = le32toh(wire->display_id);
    host->display_generation = le32toh(wire->display_generation);
    host->timestamp_ns = le64toh(wire->timestamp_ns);
    host->session_id = le64toh(wire->session_id);
    host->x = (int32_t)le32toh((uint32_t)wire->x);
    host->y = (int32_t)le32toh((uint32_t)wire->y);
    host->button = le32toh(wire->button);
    host->state = le32toh(wire->state);
    host->focus_generation = le32toh(wire->focus_generation);
    host->flags = le32toh(wire->flags);
    host->reserved = le32toh(wire->reserved);
}

static int fail(char *why, size_t why_len, const char *reason) {
    if (why && why_len) {
        snprintf(why, why_len, "%s", reason);
    }
    return -1;
}

int aaas_input_validate(const aaas_input_msg *m, uint64_t session_id,
                        uint32_t display_id, char *why, size_t why_len) {
    if (m->magic != AAAS_INPUT_MAGIC) return fail(why, why_len, "bad magic");
    if (m->version != AAAS_INPUT_VERSION) return fail(why, why_len, "bad version");
    if (m->length != AAAS_INPUT_MSG_SIZE) return fail(why, why_len, "bad length");
    if (m->type < AAAS_INPUT_HELLO || m->type > AAAS_INPUT_AXIS_STOP) {
        return fail(why, why_len, "bad type");
    }
    if (m->session_id != session_id) return fail(why, why_len, "stale session");
    if (m->display_id != display_id) return fail(why, why_len, "wrong display");
    if (m->display_id >= AAAS_INPUT_MAX_DISPLAY) {
        return fail(why, why_len, "display out of range");
    }
    uint32_t allowed_flags;
    if (m->type == AAAS_INPUT_SCROLL) {
        allowed_flags = AAAS_INPUT_FLAG_AXIS_VALUE120 | AAAS_INPUT_FLAG_AXIS_DISCRETE |
                        AAAS_INPUT_FLAG_AXIS_SMOOTH;
    } else {
        allowed_flags = AAAS_INPUT_FLAG_ACK | AAAS_INPUT_FLAG_KEYBOARD_V2;
    }
    if (m->flags & ~allowed_flags) return fail(why, why_len, "bad flags");
    if ((m->flags & AAAS_INPUT_FLAG_ACK) && m->type != AAAS_INPUT_HELLO) {
        return fail(why, why_len, "ack on non-hello");
    }
    if ((m->flags & AAAS_INPUT_FLAG_KEYBOARD_V2) &&
        (m->type != AAAS_INPUT_HELLO || !(m->flags & AAAS_INPUT_FLAG_ACK))) {
        return fail(why, why_len, "keyboard capability without ack");
    }
    if (m->reserved != 0 && m->type != AAAS_INPUT_SCROLL) {
        return fail(why, why_len, "reserved not zero");
    }

    if (m->type == AAAS_INPUT_HELLO) {
        if (m->x <= 0 || m->y <= 0 ||
            (uint32_t)m->x > AAAS_INPUT_MAX_DIM ||
            (uint32_t)m->y > AAAS_INPUT_MAX_DIM) {
            return fail(why, why_len, "bad hello dimensions");
        }
        if (m->display_generation == 0) {
            return fail(why, why_len, "missing display generation");
        }
        return 0;
    }

    if (m->type == AAAS_INPUT_SHUTDOWN) {
        if (m->display_generation == 0) {
            return fail(why, why_len, "missing display generation");
        }
        return 0;
    }

    if (m->x < 0 || m->y < 0 ||
        (uint32_t)m->x >= AAAS_INPUT_MAX_DIM ||
        (uint32_t)m->y >= AAAS_INPUT_MAX_DIM) {
        return fail(why, why_len, "coordinate out of range");
    }
    if (m->display_generation == 0) {
        return fail(why, why_len, "missing display generation");
    }

    if (m->type == AAAS_INPUT_FOCUS) {
        if (m->state != AAAS_INPUT_FOCUS_LEAVE &&
            m->state != AAAS_INPUT_FOCUS_ENTER) {
            return fail(why, why_len, "bad focus state");
        }
    } else if (m->type == AAAS_INPUT_BUTTON) {
        if (m->state != AAAS_INPUT_BUTTON_RELEASED &&
            m->state != AAAS_INPUT_BUTTON_PRESSED) {
            return fail(why, why_len, "bad button state");
        }
        if (m->button != AAAS_INPUT_BUTTON_LEFT &&
            m->button != AAAS_INPUT_BUTTON_RIGHT &&
            m->button != AAAS_INPUT_BUTTON_MIDDLE) {
            return fail(why, why_len, "unsupported button");
        }
    } else if (m->type == AAAS_INPUT_HOVER) {
        if (m->state != 0 || m->button != 0) {
            return fail(why, why_len, "bad hover payload");
        }
    } else if (m->type == AAAS_INPUT_SCROLL) {
        if (m->button > AAAS_INPUT_AXIS_SOURCE_WHEEL_TILT) {
            return fail(why, why_len, "bad axis source");
        }
        if (m->state == 0 && m->reserved == 0) {
            return fail(why, why_len, "empty scroll");
        }
    } else if (m->type == AAAS_INPUT_AXIS_STOP) {
        if (m->button == 0 || (m->button & ~(AAAS_INPUT_AXIS_VERTICAL |
                                             AAAS_INPUT_AXIS_HORIZONTAL))) {
            return fail(why, why_len, "bad axis stop");
        }
        if (m->state != 0 || m->flags != 0 || m->reserved != 0) {
            return fail(why, why_len, "bad axis stop payload");
        }
    }
    return 0;
}
