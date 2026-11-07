# Android audio HAL experiment

**Status: PARTIAL/OPEN.** The opt-in, session-local path now carries real
Android AudioTrack playback into PipeWire and real PipeWire source samples into
Android AudioRecord. It is not yet full M4 audio acceptance: ordinary media-app
playback, permission revocation, playback controls/concurrency, failure-path
coverage, and physical microphone behavior remain unverified.

## Image and interface findings

The workspace image is Android 16 x86_64 with `ro.hardware=ranchu`. Its vendor VINTF manifest declares `android.hardware.audio@7.1::IDevicesFactory/default`, and `/vendor/bin/hw/android.hardware.audio.service` registers that HIDL service. The legacy HIDL 7.1 adapter loads the old shared-library HAL using `hw_get_module_by_class`; AOSP's HIDL adapter source confirms it then opens the returned `audio_hw_device_t`.

The vendor audio policy XML is version 7.0 and declares a primary module with a speaker and built-in microphone. The image's existing `audio.primary.default.so` is present, while `audio.primary.ranchu.so` is an empty placeholder in the workspace image. The runtime reports `ro.hardware.audio.primary` unset. AOSP's Ranchu/Golfish history documents that module-specific property as the way to select a hardware-module variant before falling back to `ro.hardware` ([AOSP change](https://android.googlesource.com/device/generic/goldfish/%2B/0657d895cf0abe943ab3c1e833b979b79dad36c7)). Android documents that the framework supports either HIDL or AIDL Audio HALs ([AOSP HIDL/AIDL comparison](https://source.android.com/docs/core/audio/aidl-hidl-comp)).

This experiment builds a legacy x86_64/Bionic HAL for the image's HIDL compatibility adapter. A session-only `--experimental-audio-hal` option binds it at `audio.primary.aaas.so`, sets `ro.hardware.audio.primary=aaas`, and starts the host bridge. The selector alone did not resolve the failure. The live campaign found that the Ranchu 7.1 factory special-cased `primary` to its emulator device path instead of using the legacy module selector. A session-local bind of the image-matched AOSP legacy HIDL factory routes the primary module through `hw_get_module_by_class`.

## Transport prototype

The HAL provides PCM S16LE playback and capture callbacks over a versioned Unix stream socket at `/dev/aaas/audio.sock`. The host process checks the mapped Android `audioserver` UID, limits the stream count, formats and message size, and connects through the host's existing `libpulse-simple` service (`pipewire-pulse`). Android still owns track creation, app microphone permission, and mic mute. The host helper starts only for opt-in sessions and terminates with the session.

The legacy HIDL adapter also needs ashmem-backed FMQ allocation. The rootless
guest does not expose `/dev/ashmem`; the stock ashmem setter rejects a memfd.
The session-only vendor audio-service preload shim implements the required
ashmem region API over a CLOEXEC, NOEXEC-sealed memfd and implements the
relevant size/protection seals. This enabled the FMQ path without exposing an
ashmem device node or changing the base image. Playback acceptance also used
session-only stock-compatible `audioserver` and `libaudiohal.so` overlays;
their use is diagnostic and not yet a reproducible default runtime
configuration.

The bridge was separately exercised with paced synthetic host PCM into a PipeWire null sink; its monitor capture contained a 440 Hz signal (262144 bytes, RMS 3896.3, 433 zero crossings). This verifies only the host Pulse/PipeWire transport. It is not Android-generated PCM evidence.

## Historical first live result (2026-11-06)

Session `m1b84_session_ckxzb6mf` used the opt-in overlay and an ordinary target-SDK 35 AudioTrack probe. The session log confirmed:

- `ro.hardware=ranchu`, `ro.hardware.audio.primary=aaas`.
- The session overlay was visible at `/vendor/lib64/hw/audio.primary.aaas.so` (13,408 bytes).
- The HIDL 7.1 `IDevicesFactory/default` service registered before audioserver.
- AudioPolicyManager still reported it could not load `primary`, `r_submix`, or `bluetooth`; the speaker remained unreachable.
- `AudioTrack` failed during initialization with status `-19`; the probe never generated a host bridge client. The bridge log contains only its ready message.

Earlier sessions also observed the HIDL factory registration and module lookup failures. The evidence does not establish whether the factory call failed before `hw_get_module_by_class`, the module loader rejected the HAL, or the HAL open/initialization returned an error. Therefore the exact root cause remains unresolved; the selector experiment is not recorded as a fix.

That first run did not load the primary HAL. Its original evidence and failure remain preserved in session `m1b84_session_ckxzb6mf`.

## Live playback and microphone continuation (2026-11-07)

The session-local path was subsequently exercised by the Android framework.
In playback session `m1b84_session_2mbhio2e`, the legacy factory opened the
HAL (`module_api=1`, `hal_api=256`), `init_check` and
`open_output_stream` returned 0 for 48 kHz stereo PCM16, and AudioFlinger
selected output 13 on the primary speaker route. The ordinary diagnostic
`org.aaas.audioprobe` reported `PLAYBACK_OK ... frames=48000`; the HAL logged
`output_write_enter` and connected to the host socket. The PipeWire null-sink
monitor capture SHA-256 was
`eead53103b2d60668afcb4390c571bceee7d3ae1eeb91ef8f59cf8b48a0cdb1c`.
Analysis found 47,760 active samples per channel, active RMS 50.15, and a
dominant frequency of 440.009 Hz. This is end-to-end AudioTrack PCM, not an
idle stream or host-generated playback signal.

In microphone session `m1b84_session_7bmrswv1`, an ordinary target-SDK 35
probe requested `RECORD_AUDIO` through Android's permission UI. A separate
denial run (`m1b84_session_6fxx1kmc`) produced
`RECORD_PERMISSION_DENIED` and no capture socket. After granting permission
through the Android PermissionController UI in
`m1b84_session_tgcfzkl7`, a subsequent complete runtime restart retained the
grant (`RECORD_PERMISSION_ALREADY_GRANTED`) in
`m1b84_session_7bmrswv1`. AudioRecord read 144,000 frames at 48 kHz mono;
the app reported RMS 3535.08, 2,640 zero crossings, dominant 440 Hz, and
SHA-256 `c17e0171a907e9c8db395333ff6f20e05c657062efdd06d129eab65079303d50`.
The host bridge independently observed 145,920 frames, RMS 3535.16, peak
5,000, and 145,676 nonzero samples from the controlled PipeWire virtual
source. The fixture was a 440 Hz mono signal. Its PipeWire source was kept
active with a host reader because the first test attempt allowed the virtual
source to suspend and therefore delivered silence.

## Remaining limitations

The explicit permission-denied case and normal grant/persistence are verified;
runtime-permission revocation and post-revocation AudioRecord denial remain
open. The virtual source demonstrates software-only capture; no physical
microphone was tested. The real-media-app path (including VLC/mpv URI access),
pause/resume, volume/mute, concurrent clients, host sink/source disconnect,
and idle/failure recovery remain open. Host and Android logs are retained only
under the workspace's raw session records; no PCM payload was added to Git.

The corrected route remains opt-in and currently needs session-local compatible
audio framework/factory overlays plus the memfd ashmem shim. The base guest
image is unchanged. See the dated `audio_microphone_continuation_2026_11_07`
acceptance record for exact evidence hashes and regressions. Canonical M4
remains **PARTIAL/OPEN**; the demonstrated vertical slices are not represented
as complete platform acceptance.

## Runner overlay ordering regression (2026-11-07)

The reusable runner initially rebound a selected `audioserver` binary over
`/system/bin/audioserver` after placing the preload wrapper there. That later
bind replaced the wrapper, so the stock server started without the session
preloads and repeatedly died before publishing `media.audio_policy`. The
runner now binds the selected server only at
`/system/bin/audioserver.aaas-original` when diagnostics/preloads are active;
the wrapper remains the executable at `/system/bin/audioserver`. A focused
test asserts the selected server is bound once and the wrapper is retained.

After this fix, session `m1b84_session_5alc1utr` loaded the legacy HAL through
the HIDL service, returned success from `module_open` and `init_check`, opened
48 kHz stereo PCM16 output, and reported `PLAYBACK_OK` for 48,000 AudioTrack
frames. Its session bridge wrote PCM to the explicitly selected PipeWire null
sink. The monitor capture had 45,680 left-channel samples above magnitude 5,
active RMS 51.4, peak 71, and a 439.527 Hz zero-crossing estimate over the
active span. Capture SHA-256 was
`d83cf440fa3c6893762d3fe591dff4ac24c9a1cf5795ecdf653eba319912b10a`; the raw
PCM was deleted after measurement. The runtime reached `RUNNING`, then
`STOPPED`; the host bridge logged playback stream close and exit.

This closes the session-overlay regression and re-verifies the AudioTrack
vertical slice. It does not establish ordinary media-app playback, playback
controls, concurrency, microphone revocation, host-device failure recovery, or
normal non-diagnostic audio startup. The test used the existing opt-in audio
configuration and a test-only `PULSE_SINK=aaas_m4_null` selection. Canonical
M4 remains **PARTIAL/OPEN**.
