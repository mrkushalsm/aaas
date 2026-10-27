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
};

enum {
    AAAS_INPUT_FOCUS_LEAVE = 0,
    AAAS_INPUT_FOCUS_ENTER = 1,
};

enum {
    AAAS_INPUT_BUTTON_RELEASED = 0,
    AAAS_INPUT_BUTTON_PRESSED = 1,
};

enum {
    AAAS_INPUT_FLAG_ACK = 1u << 0,
};

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
    uint32_t reserved;          /* must be zero */
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

#ifdef __cplusplus
}
#endif

#endif /* AAAS_INPUT_V1_H */
