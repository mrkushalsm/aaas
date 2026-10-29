#ifndef AAAS_INPUT_V1_H
#define AAAS_INPUT_V1_H

/*
 * AaaS pointer input transport, protocol version 1.
 *
 * The host presenter writes fixed-size messages to a private AF_UNIX
 * SOCK_SEQPACKET socket.  All integer fields are encoded little-endian on the
 * wire.  The transport is separate from the Composer3 frame/release channel so
 * pointer traffic can never consume frame-release messages.
 */

#include <stddef.h>
#include <stdint.h>

#define AAAS_INPUT_MAGIC 0x49414141u /* 'AAAI' */
#define AAAS_INPUT_VERSION 1u
#define AAAS_INPUT_KEYBOARD_VERSION 2u
#define AAAS_INPUT_MAX_DISPLAY 16u
#define AAAS_INPUT_MAX_DIM 8192u

#define AAAS_INPUT_BUTTON_LEFT 0x110u
#define AAAS_INPUT_BUTTON_RIGHT 0x111u
#define AAAS_INPUT_BUTTON_MIDDLE 0x112u

enum {
    AAAS_INPUT_HELLO = 1,
    AAAS_INPUT_FOCUS = 2,
    AAAS_INPUT_MOTION = 3,
    AAAS_INPUT_BUTTON = 4,
    AAAS_INPUT_SHUTDOWN = 5,
    AAAS_INPUT_HOVER = 6,
    AAAS_INPUT_SCROLL = 7,
    AAAS_INPUT_AXIS_STOP = 8,
};

enum {
    AAAS_INPUT_FOCUS_LEAVE = 0,
    AAAS_INPUT_FOCUS_ENTER = 1,
};

/* Wayland wl_pointer.axis_source values. */
enum {
    AAAS_INPUT_AXIS_SOURCE_WHEEL = 0,
    AAAS_INPUT_AXIS_SOURCE_FINGER = 1,
    AAAS_INPUT_AXIS_SOURCE_CONTINUOUS = 2,
    AAAS_INPUT_AXIS_SOURCE_WHEEL_TILT = 3,
};

/* Logical bitmask used by AXIS_STOP. */
enum {
    AAAS_INPUT_AXIS_VERTICAL = 1u << 0,
    AAAS_INPUT_AXIS_HORIZONTAL = 1u << 1,
};

enum {
    AAAS_INPUT_BUTTON_RELEASED = 0,
    AAAS_INPUT_BUTTON_PRESSED = 1,
};

enum {
    AAAS_INPUT_FLAG_ACK = 1u << 0,
    /* Present when a scroll carries latched axis_value120 data. */
    AAAS_INPUT_FLAG_AXIS_VALUE120 = 1u << 1,
    /* Present when a scroll carries latched axis_discrete data. */
    AAAS_INPUT_FLAG_AXIS_DISCRETE = 1u << 2,
    /* Present when a scroll was synthesized from smooth axis motion. */
    AAAS_INPUT_FLAG_AXIS_SMOOTH = 1u << 3,
    /* Negotiated by a v1 HELLO ACK before v2 keyboard packets are sent. */
    AAAS_INPUT_FLAG_KEYBOARD_V2 = 1u << 4,
};

enum {
    AAAS_INPUT_KEYBOARD_FOCUS = 1,
    AAAS_INPUT_KEY = 2,
};

enum { AAAS_INPUT_KEY_RELEASED = 0, AAAS_INPUT_KEY_PRESSED = 1 };

/* Version 2 keyboard packet. Pointer packets remain the unchanged 68-byte v1. */
typedef struct {
    uint32_t magic;
    uint16_t version;
    uint16_t type;
    uint32_t length;
    uint32_t sequence;
    uint32_t display_id;
    uint32_t display_generation;
    uint64_t timestamp_ns;
    uint64_t session_id;
    uint32_t focus_generation;
    uint32_t evdev_key;
    uint32_t android_keycode;
    uint32_t state;
    uint32_t meta_state;
    uint32_t repeat_count;
    uint32_t keysym;
    uint32_t unicode_scalar;
} __attribute__((packed)) aaas_input_keyboard_msg;

#define AAAS_INPUT_KEYBOARD_MSG_SIZE ((uint32_t)sizeof(aaas_input_keyboard_msg))

typedef struct {
    uint32_t magic;             /* AAAS_INPUT_MAGIC */
    uint16_t version;           /* AAAS_INPUT_VERSION */
    uint16_t type;              /* AAAS_INPUT_* */
    uint32_t length;            /* sizeof(aaas_input_msg) */
    uint32_t sequence;          /* monotonically increasing per session */
    uint32_t display_id;        /* Android display id (0 for the AaaS display) */
    uint32_t display_generation;/* Presenter configure/display generation */
    uint64_t timestamp_ns;      /* CLOCK_MONOTONIC on the sender */
    uint64_t session_id;        /* per-session random token */
    int32_t x;                  /* display pixel x */
    int32_t y;                  /* display pixel y */
    uint32_t button;            /* Linux BTN_* code for BUTTON messages */
    uint32_t state;             /* focus/button state */
    uint32_t focus_generation;  /* incremented on enter/leave */
    uint32_t flags;             /* AAAS_INPUT_FLAG_* */
    uint32_t reserved;          /* must be zero except SCROLL uses horizontal value120 */
} __attribute__((packed)) aaas_input_msg;

#define AAAS_INPUT_MSG_SIZE ((uint32_t)sizeof(aaas_input_msg))

#ifdef __cplusplus
extern "C" {
#endif

/* Host-order message -> little-endian wire representation. */
void aaas_input_to_wire(aaas_input_msg *wire, const aaas_input_msg *host);

/* Little-endian wire representation -> host-order message. */
void aaas_input_from_wire(aaas_input_msg *host, const aaas_input_msg *wire);

/*
 * Validate a host-order message.  Returns 0 when valid, -1 otherwise and fills
 * why with a short reason.  The caller must have checked the packet length.
 */
int aaas_input_validate(const aaas_input_msg *msg, uint64_t session_id,
                        uint32_t display_id, char *why, size_t why_len);

void aaas_input_keyboard_to_wire(aaas_input_keyboard_msg *wire,
                                const aaas_input_keyboard_msg *host);
void aaas_input_keyboard_from_wire(aaas_input_keyboard_msg *host,
                                   const aaas_input_keyboard_msg *wire);
int aaas_input_keyboard_validate(const aaas_input_keyboard_msg *msg,
                                uint64_t session_id, uint32_t display_id,
                                char *why, size_t why_len);

#ifdef __cplusplus
}
#endif

#endif /* AAAS_INPUT_V1_H */
