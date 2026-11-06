/*
 * Copyright (C) 2026 AaaS contributors
 * SPDX-License-Identifier: MIT
 */
#ifndef AAAS_AUDIO_PROTOCOL_H
#define AAAS_AUDIO_PROTOCOL_H

#include <stdint.h>

#define AAAS_AUDIO_MAGIC "AAASAU01"
#define AAAS_AUDIO_VERSION 1u
#define AAAS_AUDIO_PLAYBACK 1u
#define AAAS_AUDIO_CAPTURE 2u
#define AAAS_AUDIO_FORMAT_S16_LE 1u
#define AAAS_AUDIO_MAX_RATE 96000u
#define AAAS_AUDIO_MAX_CHANNELS 2u
#define AAAS_AUDIO_MAX_BUFFER 262144u

#if defined(__GNUC__)
#define AAAS_PACKED __attribute__((packed))
#else
#define AAAS_PACKED
#endif

struct AAAS_PACKED aaas_audio_hello {
    char magic[8];
    uint16_t version;
    uint16_t direction;
    uint32_t sample_rate;
    uint16_t channels;
    uint16_t format;
};

#endif
