# Android audio HAL experiment

**Status: PARTIAL/OPEN.** The host PCM adapter is verified separately, but the Android framework still cannot create an audio track through this experimental HAL. Playback and microphone acceptance are not passed.

## Image and interface findings

The workspace image is Android 16 x86_64 with `ro.hardware=ranchu`. Its vendor VINTF manifest declares `android.hardware.audio@7.1::IDevicesFactory/default`, and `/vendor/bin/hw/android.hardware.audio.service` registers that HIDL service. The legacy HIDL 7.1 adapter loads the old shared-library HAL using `hw_get_module_by_class`; AOSP's HIDL adapter source confirms it then opens the returned `audio_hw_device_t`.

The vendor audio policy XML is version 7.0 and declares a primary module with a speaker and built-in microphone. The image's existing `audio.primary.default.so` is present, while `audio.primary.ranchu.so` is an empty placeholder in the workspace image. The runtime reports `ro.hardware.audio.primary` unset. AOSP's Ranchu/Golfish history documents that module-specific property as the way to select a hardware-module variant before falling back to `ro.hardware` ([AOSP change](https://android.googlesource.com/device/generic/goldfish/%2B/0657d895cf0abe943ab3c1e833b979b79dad36c7)). Android documents that the framework supports either HIDL or AIDL Audio HALs ([AOSP HIDL/AIDL comparison](https://source.android.com/docs/core/audio/aidl-hidl-comp)).

This experiment builds a legacy x86_64/Bionic HAL for the image's HIDL compatibility adapter. A session-only `--experimental-audio-hal` option binds it at `audio.primary.aaas.so`, sets `ro.hardware.audio.primary=aaas`, and starts the host bridge. This selector follows the AOSP module-selection mechanism; it did not resolve the live failure.

## Transport prototype

The HAL provides PCM S16LE playback and capture callbacks over a versioned Unix stream socket at `/dev/aaas/audio.sock`. The host process checks the mapped Android `audioserver` UID, limits the stream count, formats and message size, and connects through the host's existing `libpulse-simple` service (`pipewire-pulse`). Android still owns track creation, app microphone permission, and mic mute. The host helper starts only for opt-in sessions and terminates with the session.

The bridge was separately exercised with paced synthetic host PCM into a PipeWire null sink; its monitor capture contained a 440 Hz signal (262144 bytes, RMS 3896.3, 433 zero crossings). This verifies only the host Pulse/PipeWire transport. It is not Android-generated PCM evidence.

## Live Android result

Session `m1b84_session_ckxzb6mf` used the opt-in overlay and an ordinary target-SDK 35 AudioTrack probe. The session log confirmed:

- `ro.hardware=ranchu`, `ro.hardware.audio.primary=aaas`.
- The session overlay was visible at `/vendor/lib64/hw/audio.primary.aaas.so` (13,408 bytes).
- The HIDL 7.1 `IDevicesFactory/default` service registered before audioserver.
- AudioPolicyManager still reported it could not load `primary`, `r_submix`, or `bluetooth`; the speaker remained unreachable.
- `AudioTrack` failed during initialization with status `-19`; the probe never generated a host bridge client. The bridge log contains only its ready message.

Earlier sessions also observed the HIDL factory registration and module lookup failures. The evidence does not establish whether the factory call failed before `hw_get_module_by_class`, the module loader rejected the HAL, or the HAL open/initialization returned an error. Therefore the exact root cause remains unresolved; the selector experiment is not recorded as a fix.

The custom HAL compiles with `-Wall -Wextra -Werror` and a reproducible build manifest, but it has not been exercised by AudioFlinger. The implementation is a prototype, not accepted Android audio support.

## Microphone and limitations

The HAL and host adapter include a capture path, but Android `AudioRecord` was not opened. No microphone samples crossed the boundary. Runtime permission grant/revocation, physical microphone behavior, source-disconnect handling, and capture cleanup have not been live accepted.

Canonical M4 remains **PARTIAL/OPEN**. Required next engineering work is to capture the HIDL factory's actual `openDevice` result (including its `DevicesFactoryHAL` error), correct the session-scoped cause, and then verify AudioTrack PCM through PipeWire before proceeding to AudioRecord. Do not infer success from service registration, the module file existing, or host-only loopback.
