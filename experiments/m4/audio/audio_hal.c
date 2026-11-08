/*
 * Copyright (C) 2026 AaaS contributors
 * SPDX-License-Identifier: MIT
 *
 * Session-selected legacy Android audio HAL.  The Android 16 image supplies
 * the HIDL 7.1 legacy adapter; this module provides its audio.primary.aaas
 * backend and forwards PCM over the session-only /dev/aaas/audio.sock socket.
 */
#define _GNU_SOURCE
#include <hardware/audio.h>
#include <hardware/hardware.h>
#include <system/audio.h>
#include "audio_protocol.h"

#include <fcntl.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

extern int __android_log_print(int priority, const char *tag, const char *format, ...);
#define AAAS_LOGI(...) ((void)__android_log_print(4, "AaasAudioHAL", __VA_ARGS__))
#define AAAS_LOGE(...) ((void)__android_log_print(6, "AaasAudioHAL", __VA_ARGS__))

/* Bionic's errno accessor is __errno(); avoid binding to the host glibc ABI. */
extern int *__errno(void);
#undef errno
#define errno (*__errno())
#define EINTR 4
#define ENOMEM 12
#define EIO 5
#define EINVAL 22
#define ENOSYS 38
#define EPIPE 32
#define ENAMETOOLONG 36

#define SOCKET_PATH "/dev/aaas/audio.sock"
#define HAL_STREAM_BUFFER_MS 20u

struct aaas_device { struct audio_hw_device hw; volatile int mic_muted; };
struct aaas_stream_out {
    struct audio_stream_out stream;
    int fd;
    uint32_t rate;
    audio_channel_mask_t channels;
    audio_format_t format;
    audio_devices_t device;
    size_t frames;
    uint64_t written_frames;
    float left_volume;
    float right_volume;
    bool paused;
};
struct aaas_stream_in {
    struct audio_stream_in stream;
    int fd;
    uint32_t rate;
    audio_channel_mask_t channels;
    audio_format_t format;
    audio_devices_t device;
    size_t frames;
    struct aaas_device *device_owner;
    bool transport_failed;
};

static ssize_t write_all(int fd, const void *buffer, size_t bytes) {
    const uint8_t *p = (const uint8_t *)buffer;
    size_t done = 0;
    while (done < bytes) {
        ssize_t n = write(fd, p + done, bytes - done);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -errno;
        done += (size_t)n;
    }
    return (ssize_t)done;
}

static ssize_t read_all(int fd, void *buffer, size_t bytes) {
    uint8_t *p = (uint8_t *)buffer;
    size_t done = 0;
    while (done < bytes) {
        ssize_t n = read(fd, p + done, bytes - done);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return n < 0 ? -errno : -EPIPE;
        done += (size_t)n;
    }
    return (ssize_t)done;
}

static int connect_audio(uint16_t direction, uint32_t rate,
                         audio_channel_mask_t mask) {
    unsigned channels = direction == AAAS_AUDIO_PLAYBACK
        ? audio_channel_count_from_out_mask(mask)
        : audio_channel_count_from_in_mask(mask);
    if (!channels || channels > AAAS_AUDIO_MAX_CHANNELS || !rate ||
        rate > AAAS_AUDIO_MAX_RATE) return -EINVAL;
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return -errno;
    struct timeval timeout = { .tv_sec = 2, .tv_usec = 0 };
    (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    size_t path_len = strlen(SOCKET_PATH);
    if (path_len >= sizeof(address.sun_path)) { close(fd); return -ENAMETOOLONG; }
    memcpy(address.sun_path, SOCKET_PATH, path_len + 1);
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        int error = errno;
        AAAS_LOGE("socket_connect direction=%u failed errno=%d", direction, error);
        close(fd); return -error;
    }
    struct aaas_audio_hello hello;
    memcpy(hello.magic, AAAS_AUDIO_MAGIC, sizeof(hello.magic));
    hello.version = AAAS_AUDIO_VERSION;
    hello.direction = direction;
    hello.sample_rate = rate;
    hello.channels = (uint16_t)channels;
    hello.format = AAAS_AUDIO_FORMAT_S16_LE;
    ssize_t hello_result = write_all(fd, &hello, sizeof(hello));
    if (hello_result < 0) {
        AAAS_LOGE("socket_hello direction=%u failed status=%d", direction,
                  (int)hello_result);
        close(fd); return (int)hello_result;
    }
    AAAS_LOGI("socket_connected direction=%u rate=%u channels=%u", direction,
              rate, channels);
    return fd;
}

static size_t frame_size(uint32_t rate, audio_channel_mask_t mask, bool input) {
    unsigned channels = input ? audio_channel_count_from_in_mask(mask)
                              : audio_channel_count_from_out_mask(mask);
    (void)rate;
    return (size_t)channels * sizeof(int16_t);
}

static uint32_t out_rate(const struct audio_stream *s) {
    return ((const struct aaas_stream_out *)s)->rate;
}
static int out_set_rate(struct audio_stream *s, uint32_t rate) {
    struct aaas_stream_out *o = (struct aaas_stream_out *)s;
    if (rate < 8000 || rate > AAAS_AUDIO_MAX_RATE) return -EINVAL;
    if (o->fd >= 0) return -ENOSYS;
    o->rate = rate; return 0;
}
static size_t out_buffer_size(const struct audio_stream *s) {
    const struct aaas_stream_out *o = (const struct aaas_stream_out *)s;
    return o->frames * frame_size(o->rate, o->channels, false);
}
static audio_channel_mask_t out_channels(const struct audio_stream *s) {
    return ((const struct aaas_stream_out *)s)->channels;
}
static audio_format_t out_format(const struct audio_stream *s) {
    return ((const struct aaas_stream_out *)s)->format;
}
static int out_set_format(struct audio_stream *s, audio_format_t format) {
    struct aaas_stream_out *o = (struct aaas_stream_out *)s;
    if (format != AUDIO_FORMAT_PCM_16_BIT || o->fd >= 0) return -EINVAL;
    o->format = format; return 0;
}
static int out_standby(struct audio_stream *s) {
    struct aaas_stream_out *o = (struct aaas_stream_out *)s;
    if (o->fd >= 0) { shutdown(o->fd, SHUT_RDWR); close(o->fd); o->fd = -1; }
    o->paused = false;
    return 0;
}
static int stream_dump(const struct audio_stream *s, int fd) {
    (void)s; (void)fd; return 0;
}
static audio_devices_t out_device(const struct audio_stream *s) {
    return ((const struct aaas_stream_out *)s)->device;
}
static int out_set_device(struct audio_stream *s, audio_devices_t device) {
    ((struct aaas_stream_out *)s)->device = device; return 0;
}
static int stream_set_parameters(struct audio_stream *s, const char *kv) {
    (void)s; (void)kv; return 0;
}
static char *stream_get_parameters(const struct audio_stream *s, const char *keys) {
    (void)s; (void)keys; return strdup("");
}
static int stream_effect(const struct audio_stream *s, effect_handle_t effect) {
    (void)s; (void)effect; return 0;
}
static uint32_t out_latency(const struct audio_stream_out *s) {
    const struct aaas_stream_out *o = (const struct aaas_stream_out *)s;
    return o->rate ? (uint32_t)((o->frames * 1000u) / o->rate + 30u) : 50u;
}
static int out_set_volume(struct audio_stream_out *s, float left, float right) {
    struct aaas_stream_out *o = (struct aaas_stream_out *)s;
    o->left_volume = left < 0 ? 0 : (left > 1 ? 1 : left);
    o->right_volume = right < 0 ? 0 : (right > 1 ? 1 : right);
    return 0;
}
static ssize_t out_write(struct audio_stream_out *s, const void *buffer, size_t bytes) {
    struct aaas_stream_out *o = (struct aaas_stream_out *)s;
    static volatile int first_write_logged;
    if (!__atomic_exchange_n(&first_write_logged, 1, __ATOMIC_RELAXED))
        AAAS_LOGI("output_write_enter bytes=%zu rate=%u channels=%u", bytes,
                  o->rate, audio_channel_count_from_out_mask(o->channels));
    size_t fs = frame_size(o->rate, o->channels, false);
    if (!buffer || !fs || bytes % fs || bytes > AAAS_AUDIO_MAX_BUFFER) return -EINVAL;
    if (o->paused) {
        struct timespec delay = { .tv_sec = bytes / (fs * o->rate),
            .tv_nsec = (long)((bytes % (fs * o->rate)) * 1000000000ULL / (fs * o->rate)) };
        nanosleep(&delay, NULL); return (ssize_t)bytes;
    }
    if (o->fd < 0) {
        o->fd = connect_audio(AAAS_AUDIO_PLAYBACK, o->rate, o->channels);
        if (o->fd < 0) return o->fd;
    }
    const int16_t *src = (const int16_t *)buffer;
    int16_t *scaled = NULL;
    if (o->left_volume != 1.0f || o->right_volume != 1.0f) {
        size_t samples = bytes / sizeof(int16_t);
        if (samples > AAAS_AUDIO_MAX_BUFFER / sizeof(int16_t)) return -EINVAL;
        scaled = (int16_t *)malloc(bytes);
        if (!scaled) return -ENOMEM;
        for (size_t i = 0; i < samples; ++i) {
            float volume = (audio_channel_count_from_out_mask(o->channels) == 2 && (i & 1))
                ? o->right_volume : o->left_volume;
            int32_t value = (int32_t)((float)src[i] * volume);
            if (value > INT16_MAX) value = INT16_MAX;
            if (value < INT16_MIN) value = INT16_MIN;
            scaled[i] = (int16_t)value;
        }
        src = scaled;
    }
    ssize_t result = write_all(o->fd, src, bytes);
    free(scaled);
    if (result < 0) {
        int error = (int)-result;
        AAAS_LOGE("output_write_failed status=%d frames=%llu", (int)result,
                  (unsigned long long)o->written_frames);
        shutdown(o->fd, SHUT_RDWR); close(o->fd); o->fd = -1;
        return -error;
    }
    o->written_frames += bytes / fs;
    return (ssize_t)bytes;
}
static int out_render_position(const struct audio_stream_out *s, uint32_t *frames) {
    if (!frames) return -EINVAL;
    *frames = (uint32_t)((const struct aaas_stream_out *)s)->written_frames;
    return 0;
}
static int out_next_timestamp(const struct audio_stream_out *s, int64_t *timestamp) {
    (void)s; if (!timestamp) return -EINVAL; *timestamp = 0; return -ENOSYS;
}
static int out_pause(struct audio_stream_out *s) { ((struct aaas_stream_out *)s)->paused = true; return 0; }
static int out_resume(struct audio_stream_out *s) { ((struct aaas_stream_out *)s)->paused = false; return 0; }
static int out_flush(struct audio_stream_out *s) { return out_standby(&s->common); }

static uint32_t in_rate(const struct audio_stream *s) {
    return ((const struct aaas_stream_in *)s)->rate;
}
static int in_set_rate(struct audio_stream *s, uint32_t rate) {
    struct aaas_stream_in *i = (struct aaas_stream_in *)s;
    if (rate < 8000 || rate > AAAS_AUDIO_MAX_RATE || i->fd >= 0) return -EINVAL;
    i->rate = rate; return 0;
}
static size_t in_buffer_size(const struct audio_stream *s) {
    const struct aaas_stream_in *i = (const struct aaas_stream_in *)s;
    return i->frames * frame_size(i->rate, i->channels, true);
}
static audio_channel_mask_t in_channels(const struct audio_stream *s) {
    return ((const struct aaas_stream_in *)s)->channels;
}
static audio_format_t in_format(const struct audio_stream *s) {
    return ((const struct aaas_stream_in *)s)->format;
}
static int in_set_format(struct audio_stream *s, audio_format_t format) {
    struct aaas_stream_in *i = (struct aaas_stream_in *)s;
    if (format != AUDIO_FORMAT_PCM_16_BIT || i->fd >= 0) return -EINVAL;
    i->format = format; return 0;
}
static int in_standby(struct audio_stream *s) {
    struct aaas_stream_in *i = (struct aaas_stream_in *)s;
    if (i->fd >= 0) { shutdown(i->fd, SHUT_RDWR); close(i->fd); i->fd = -1; }
    i->transport_failed = false;
    return 0;
}
static audio_devices_t in_device(const struct audio_stream *s) {
    return ((const struct aaas_stream_in *)s)->device;
}
static int in_set_device(struct audio_stream *s, audio_devices_t device) {
    ((struct aaas_stream_in *)s)->device = device; return 0;
}
static int in_gain(struct audio_stream_in *s, float gain) {
    (void)s; return gain >= 0.0f && gain <= 1.0f ? 0 : -EINVAL;
}
static ssize_t in_silence(struct aaas_stream_in *i, void *buffer, size_t bytes,
                          size_t frame_bytes) {
    memset(buffer, 0, bytes);
    uint64_t frames = bytes / frame_bytes;
    struct timespec delay = { .tv_sec = (time_t)(frames / i->rate),
        .tv_nsec = (long)((frames % i->rate) * 1000000000ULL / i->rate) };
    while (nanosleep(&delay, &delay) < 0 && errno == EINTR) {}
    return (ssize_t)bytes;
}
static ssize_t in_read(struct audio_stream_in *s, void *buffer, size_t bytes) {
    struct aaas_stream_in *i = (struct aaas_stream_in *)s;
    static volatile int first_read_logged;
    if (!__atomic_exchange_n(&first_read_logged, 1, __ATOMIC_RELAXED))
        AAAS_LOGI("input_read_enter bytes=%zu rate=%u channels=%u", bytes,
                  i->rate, audio_channel_count_from_in_mask(i->channels));
    size_t fs = frame_size(i->rate, i->channels, true);
    if (!buffer || !fs || bytes % fs || bytes > AAAS_AUDIO_MAX_BUFFER) return -EINVAL;
    if (__atomic_load_n(&i->device_owner->mic_muted, __ATOMIC_RELAXED)) {
        return in_silence(i, buffer, bytes, fs);
    }
    if (i->transport_failed) return in_silence(i, buffer, bytes, fs);
    if (i->fd < 0) {
        i->fd = connect_audio(AAAS_AUDIO_CAPTURE, i->rate, i->channels);
        if (i->fd < 0) {
            i->transport_failed = true;
            AAAS_LOGE("input transport unavailable; returning paced silence until standby");
            return in_silence(i, buffer, bytes, fs);
        }
    }
    ssize_t n = read_all(i->fd, buffer, bytes);
    if (n < 0) {
        int error = (int)-n;
        shutdown(i->fd, SHUT_RDWR); close(i->fd); i->fd = -1;
        i->transport_failed = true;
        AAAS_LOGE("input transport failed error=%d; returning paced silence until standby",
                  error);
        return in_silence(i, buffer, bytes, fs);
    }
    return n;
}
static uint32_t in_frames_lost(struct audio_stream_in *s) { (void)s; return 0; }

static int adev_init_check(const struct audio_hw_device *dev) {
    (void)dev;
    AAAS_LOGI("init_check status=0");
    return 0;
}
static int adev_set_mode(struct audio_hw_device *dev, audio_mode_t mode) { (void)dev; (void)mode; return 0; }
static int adev_set_voice_volume(struct audio_hw_device *dev, float volume) {
    (void)dev;
    return volume >= 0.0f && volume <= 1.0f ? 0 : -EINVAL;
}
static int adev_set_parameters(struct audio_hw_device *dev, const char *kv_pairs) {
    (void)dev; (void)kv_pairs; return 0;
}
static char *adev_get_parameters(const struct audio_hw_device *dev, const char *keys) {
    (void)dev; (void)keys; return strdup("");
}
static int adev_set_mic_mute(struct audio_hw_device *dev, bool mute) {
    struct aaas_device *d = (struct aaas_device *)dev;
    __atomic_store_n(&d->mic_muted, mute ? 1 : 0, __ATOMIC_RELAXED); return 0;
}
static int adev_get_mic_mute(const struct audio_hw_device *dev, bool *mute) {
    if (!mute) return -EINVAL;
    *mute = __atomic_load_n(&((const struct aaas_device *)dev)->mic_muted, __ATOMIC_RELAXED) != 0;
    return 0;
}
static size_t adev_get_input_buffer_size(const struct audio_hw_device *dev,
                                         const struct audio_config *config) {
    (void)dev;
    if (!config || config->format != AUDIO_FORMAT_PCM_16_BIT ||
        !config->sample_rate || config->sample_rate > AAAS_AUDIO_MAX_RATE) return 0;
    unsigned channels = audio_channel_count_from_in_mask(config->channel_mask);
    if (!channels || channels > AAAS_AUDIO_MAX_CHANNELS) return 0;
    return config->sample_rate / 50u * channels * sizeof(int16_t);
}
static int adev_open_output(struct audio_hw_device *dev, audio_io_handle_t handle,
    audio_devices_t devices, audio_output_flags_t flags, struct audio_config *config,
    struct audio_stream_out **stream_out, const char *address) {
    (void)dev; (void)handle; (void)flags; (void)address;
    if (!config || !stream_out) {
        AAAS_LOGE("open_output_stream invalid arguments");
        return -EINVAL;
    }
    if (config->format == AUDIO_FORMAT_DEFAULT) config->format = AUDIO_FORMAT_PCM_16_BIT;
    if (config->sample_rate == 0) config->sample_rate = 48000;
    if (config->format != AUDIO_FORMAT_PCM_16_BIT || config->sample_rate > AAAS_AUDIO_MAX_RATE) {
        AAAS_LOGE("open_output_stream unsupported format=%#x rate=%u", config->format,
                  config->sample_rate);
        return -EINVAL;
    }
    unsigned channels = audio_channel_count_from_out_mask(config->channel_mask);
    if (!channels) { config->channel_mask = AUDIO_CHANNEL_OUT_STEREO; channels = 2; }
    if (channels > AAAS_AUDIO_MAX_CHANNELS) {
        AAAS_LOGE("open_output_stream unsupported channels=%u", channels);
        return -EINVAL;
    }
    struct aaas_stream_out *o = (struct aaas_stream_out *)calloc(1, sizeof(*o));
    if (!o) return -ENOMEM;
    o->fd = -1; o->rate = config->sample_rate; o->channels = config->channel_mask;
    o->format = config->format; o->device = devices ? devices : AUDIO_DEVICE_OUT_SPEAKER;
    o->frames = o->rate / 50u; o->left_volume = o->right_volume = 1.0f;
    o->stream.common.get_sample_rate = out_rate; o->stream.common.set_sample_rate = out_set_rate;
    o->stream.common.get_buffer_size = out_buffer_size; o->stream.common.get_channels = out_channels;
    o->stream.common.get_format = out_format; o->stream.common.set_format = out_set_format;
    o->stream.common.standby = out_standby; o->stream.common.dump = stream_dump;
    o->stream.common.get_device = out_device; o->stream.common.set_device = out_set_device;
    o->stream.common.set_parameters = stream_set_parameters;
    o->stream.common.get_parameters = stream_get_parameters;
    o->stream.common.add_audio_effect = stream_effect; o->stream.common.remove_audio_effect = stream_effect;
    o->stream.get_latency = out_latency; o->stream.set_volume = out_set_volume; o->stream.write = out_write;
    o->stream.get_render_position = out_render_position; o->stream.get_next_write_timestamp = out_next_timestamp;
    o->stream.pause = out_pause; o->stream.resume = out_resume; o->stream.flush = out_flush;
    *stream_out = &o->stream;
    AAAS_LOGI("open_output_stream status=0 rate=%u channels=%u format=%#x", o->rate,
              channels, (unsigned)o->format);
    return 0;
}
static void adev_close_output(struct audio_hw_device *dev, struct audio_stream_out *s) {
    (void)dev; if (!s) return; out_standby(&s->common); free(s);
}
static int adev_open_input(struct audio_hw_device *dev, audio_io_handle_t handle,
    audio_devices_t devices, struct audio_config *config, struct audio_stream_in **stream_in,
    audio_input_flags_t flags, const char *address, audio_source_t source) {
    (void)handle; (void)flags; (void)address; (void)source;
    if (!config || !stream_in) return -EINVAL;
    if (config->format == AUDIO_FORMAT_DEFAULT) config->format = AUDIO_FORMAT_PCM_16_BIT;
    if (config->sample_rate == 0) config->sample_rate = 48000;
    if (config->format != AUDIO_FORMAT_PCM_16_BIT || config->sample_rate > AAAS_AUDIO_MAX_RATE) return -EINVAL;
    unsigned channels = audio_channel_count_from_in_mask(config->channel_mask);
    if (!channels) { config->channel_mask = AUDIO_CHANNEL_IN_MONO; channels = 1; }
    if (channels > AAAS_AUDIO_MAX_CHANNELS) return -EINVAL;
    struct aaas_stream_in *i = (struct aaas_stream_in *)calloc(1, sizeof(*i));
    if (!i) return -ENOMEM;
    i->fd = -1; i->rate = config->sample_rate; i->channels = config->channel_mask;
    i->format = config->format; i->device = devices ? devices : AUDIO_DEVICE_IN_BUILTIN_MIC;
    i->frames = i->rate / 50u; i->device_owner = (struct aaas_device *)dev;
    i->stream.common.get_sample_rate = in_rate; i->stream.common.set_sample_rate = in_set_rate;
    i->stream.common.get_buffer_size = in_buffer_size; i->stream.common.get_channels = in_channels;
    i->stream.common.get_format = in_format; i->stream.common.set_format = in_set_format;
    i->stream.common.standby = in_standby; i->stream.common.dump = stream_dump;
    i->stream.common.get_device = in_device; i->stream.common.set_device = in_set_device;
    i->stream.common.set_parameters = stream_set_parameters; i->stream.common.get_parameters = stream_get_parameters;
    i->stream.common.add_audio_effect = stream_effect; i->stream.common.remove_audio_effect = stream_effect;
    i->stream.set_gain = in_gain; i->stream.read = in_read; i->stream.get_input_frames_lost = in_frames_lost;
    *stream_in = &i->stream;
    AAAS_LOGI("open_input_stream status=0 rate=%u channels=%u format=%#x device=%#x",
              i->rate, channels, (unsigned)i->format, (unsigned)i->device);
    return 0;
}
static void adev_close_input(struct audio_hw_device *dev, struct audio_stream_in *s) {
    (void)dev; if (!s) return; in_standby(&s->common); free(s);
}
static int adev_close(hw_device_t *device) { free(device); return 0; }
static int adev_open(const hw_module_t *module, const char *name, hw_device_t **out) {
    AAAS_LOGI("module_open name=%s id=%s module_api=%u hal_api=%u", name ? name : "(null)",
              module && module->id ? module->id : "(null)",
              module ? module->module_api_version : 0,
              module ? module->hal_api_version : 0);
    if (!module || !name || !out || strcmp(name, AUDIO_HARDWARE_INTERFACE) != 0) {
        AAAS_LOGE("module_open invalid arguments or interface name");
        return -EINVAL;
    }
    struct aaas_device *d = (struct aaas_device *)calloc(1, sizeof(*d));
    if (!d) return -ENOMEM;
    d->hw.common.tag = HARDWARE_DEVICE_TAG;
    d->hw.common.version = AUDIO_DEVICE_API_VERSION_2_0;
    d->hw.common.module = (struct hw_module_t *)module;
    d->hw.common.close = adev_close;
    d->hw.init_check = adev_init_check;
    d->hw.set_voice_volume = adev_set_voice_volume;
    d->hw.set_mode = adev_set_mode;
    d->hw.set_mic_mute = adev_set_mic_mute;
    d->hw.get_mic_mute = adev_get_mic_mute;
    d->hw.set_parameters = adev_set_parameters;
    d->hw.get_parameters = adev_get_parameters;
    d->hw.get_input_buffer_size = adev_get_input_buffer_size;
    d->hw.open_output_stream = adev_open_output;
    d->hw.close_output_stream = adev_close_output;
    d->hw.open_input_stream = adev_open_input;
    d->hw.close_input_stream = adev_close_input;
    *out = &d->hw.common;
    AAAS_LOGI("module_open status=0 device_api=%u", d->hw.common.version);
    return 0;
}

__attribute__((constructor)) static void aaas_hal_loaded(void) {
    AAAS_LOGI("library_loaded");
}
static struct hw_module_methods_t module_methods = { .open = adev_open };
struct audio_module HAL_MODULE_INFO_SYM = {
    .common = { .tag = HARDWARE_MODULE_TAG,
        .module_api_version = AUDIO_MODULE_API_VERSION_0_1,
        .hal_api_version = HARDWARE_HAL_API_VERSION,
        .id = AUDIO_HARDWARE_MODULE_ID,
        .name = "AaaS session PipeWire audio HAL",
        .author = "AaaS",
        .methods = &module_methods }
};
