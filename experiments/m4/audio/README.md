# Android audio HAL experiment

**Status: PARTIAL/OPEN.** The reproducible `--audio` session option builds and
selects session-local HAL/framework overlays, starts a UID-checked host bridge,
and routes ordinary Android Music playback through PipeWire. AudioTrack
controls, mono mixing, concurrent media/probe output, virtual and physical
microphone capture, and clean shutdown have live evidence. Normal permission
grant, active-capture revocation, fresh denial, regrant, and resumed capture are
verified. Playback disconnect and recovery after private PipeWire restart are
verified; capture transport now fails promptly and a fresh capture stream works
after recovery. Canonical M4 is PASS/CLOSED for the documented supported runtime;
see the final acceptance entry below.

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

The statements in this dated section describe the initial 2026-11-07
acceptance state and are superseded by the follow-ups below. Later sessions
verified ordinary Music playback, pause/resume, volume/mute, mono mixing,
concurrent clients, a physical microphone, source/sink loss behavior, normal
Android permission revocation and regrant, and private PipeWire service restart.
The synchronous-read limitation below was corrected by the 2026-11-08 capture
failure repair documented at the end of this file. Host and Android raw logs
remain in the workspace, and no PCM payload was added to Git.

The route remains opt-in and uses session-local compatible audio
framework/factory overlays plus the memfd ashmem shim. The base guest image is
unchanged. At this historical point the final combined M2/M3/M4 acceptance
matrix remained open; the dated closure campaign below supersedes that status.

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

## Runtime audio continuation (2026-11-08)

The 2026-11-07 limitations above are historical. On the ext4 workspace
(`/run/media/mrkus/Aaas`, UUID
`094120c3-e1f8-4a61-a95a-c347ecb711d1`), the workspace guard returned
`HEALTHY_FOR_CONTROLLED_TESTING`. The prior USB/JBD2 incident remains in the
health record; the controlled sessions produced no later matching kernel
storage errors. SMART was not queried during these sessions.

The runner now prepares the audio artifacts for `--audio` sessions and can
launch Android Music on the shared WAV through MediaStore with a temporary
read-URI grant. Session `m1b84_session_ctqr5ko5` delivered 480,000 AudioTrack
frames from Music. Session `m1b84_session_8fvci8o7` verified media-stream
volume and mute/resume on the PipeWire monitor (440 Hz, active RMS 1250.61;
the muted interval was silent). The original fixture is
`shared-storage/android-media/0/Music/AaaS-M4-Original-Tone.wav`.

Session `m1b84_session_kg1lq74m` verified 48 kHz stereo pause/resume/mute and a
44.1 kHz mono 660 Hz AudioTrack mixed to the 48 kHz stereo host route. PipeWire
measurement found 440 Hz RMS 47.50 and 660 Hz RMS 23.86 during the mono segment.
Sessions `m1b84_session_t84_4q94` and `m1b84_session_mdhj80m6` launched Music and
`org.aaas.audioprobe` on separate virtual displays. A bounded monitor showed
simultaneous 440 Hz and 660 Hz peaks (RMS 41.79 in the measured overlap); its
temporary recording was deleted. In `m1b84_session_mdhj80m6`, slot 2 reached
`CLOSED` while Music's AudioTrack continued to its 480,000-frame stop about 2.7
seconds later. Both sessions reached `STOPPED`.

Virtual-source capture remains verified in `m1b84_session_ap58hujd`: 48 kHz
mono, 144,000 frames, Android RMS 3509.68 and 440 Hz; the host observed RMS
3510.13. A short authorized built-in microphone capture in
`m1b84_session_p66hqwr0` produced Android RMS 192.44 (dominant estimate 380 Hz)
and host RMS 192.35; the PipeWire source returned to `SUSPENDED`. No raw
microphone audio was retained. Earlier Android permission-denial and normal UI
grant evidence remains valid, but active revocation and a new post-revocation
denial have not been tested.

The live output-sink-removal experiment (`m1b84_session_c9vd_vex`) left Android
responsive, completed the bounded probe and mono segment, closed the host
stream, and stopped cleanly. PipeWire may move an existing stream when a sink
disappears, so this establishes orderly teardown, not silence or a specific
fallback route. Unit tests cover partial-frame rejection, PipeWire write
failure cleanup, and capture peer disconnect. The full Python suite passed 389
tests; focused audio/runner/overlay tests passed 100.

Evidence hashes and remaining acceptance gates are in
`results/m4/acceptance.json`. M4 remains **PARTIAL/OPEN**: microphone permission
revocation, deterministic sink/source disappearance semantics, the final
combined M2/M3/M4 regression, and the complete cleanup/failure matrix remain
open.

### Failure follow-up (2026-11-08)

Removing the selected virtual capture source during AudioRecord caused
AudioFlinger to report `framesRead=-61`; the bounded app probe returned silence
and the session stopped without hanging (`m1b84_session_0y_a97b6`). Killing
the host bridge during Android startup caused the runner to fail the session
closed (`m1b84_session_f655x46_`). A fresh session then passed stereo and mono
AudioTrack probes and shut down cleanly (`m1b84_session_9b2hx39k`). Automatic
same-session bridge restart and PipeWire-daemon failure behavior are not
claimed. The bridge now limits concurrent handler threads to four, with a
synthetic test for excess unauthenticated socket peers. Full suite: 390 tests
passed. Canonical M4 remains **PARTIAL/OPEN** pending microphone permission
revocation and the final integration matrix.

Revocation-test setup session `m1b84_session_uahany_6` reached `RUNNING` and
stopped normally, but the existing Android UI capture path could not capture
virtual display 2 and its UIAutomator dump was killed. No permission change or
revocation result is claimed; see the acceptance JSON for session evidence.

### Permission and PipeWire outage follow-up (2026-11-08)

The display-aware AaaS UI tap path successfully drove Android Settings on a
virtual display. In `m1b84_session_kq01kbhy`, the capture probe's microphone
permission was changed to “Don’t allow”; Android logged
`RECORD_PERMISSION_DENIED` on later ordinary permission requests. A Settings
tap later showed “Allow only while using” selected, but a subsequent app
request still returned denied. Do not treat this as a successful regrant. The
probe captures for three seconds, so active-recording revocation was not
established. The runtime stopped normally and no raw audio was kept.

A disposable private PipeWire/WirePlumber/pipewire-pulse instance was used to
exercise the production bridge without stopping the desktop audio server.
Terminating the private pipewire-pulse process closed an in-flight playback
client, and fresh playback worked after restarting that service. Capture's
synchronous Pulse read blocked while the service was absent and resumed after
restart; a fresh capture then received PCM. This establishes restart-dependent
transport recovery, not prompt capture failure. M4 remains **PARTIAL/OPEN**
until microphone regrant, active-capture revocation, and the coherent combined
M2/M3/M4 acceptance campaign pass.

### Permission revocation and regrant verification (2026-11-08)

The follow-up session `m1b84_session__6e4oa_6` used Android Settings through the
supported display-aware AaaS tap path. PermissionController logged the normal
request denial, Settings grant, active-session revocation, post-revocation
normal-dialog denial, and a later Settings regrant. During active revocation,
the audio bridge closed the capture stream after 67,200 frames; Android did not
continue the requested 30-second recording. After regrant the ordinary
nonprivileged probe received 1,440,000 controlled 48 kHz mono frames from a
440 Hz PipeWire virtual source: RMS 3461.40, 25,311 zero crossings, dominant
frequency 440 Hz. No raw PCM capture was retained. Session evidence hashes and
the exact event sequence are recorded in `results/m4/acceptance.json`.

The private PipeWire daemon outage experiment is also documented there. Playback
disconnected and recovered on a fresh stream after service restart. Capture
resumed after private service restart but its synchronous Pulse read waited
during the outage; this is not an immediate failure guarantee. The combined
M2/M3/M4 acceptance campaign remains open, so canonical M4 remains
**PARTIAL/OPEN**.


### Final acceptance follow-up (2026-11-08)

A normal Android Settings grant/revocation/regrant sequence was tested against
an active `AudioRecord` session. Revocation closed the active host stream; a new
recording request was denied; after regrant, a fresh controlled 440 Hz virtual
source capture passed. Audio-enabled M2 and M3 cross-runs also passed, as did
Android notification post forwarding in an audio-enabled session. The isolated
PipeWire outage test remains restart-dependent: playback disconnects and resumes
on a fresh stream after restart; synchronous capture waits for restart. The
full combined M4 acceptance matrix remains open. Session IDs, limitations, and
evidence hashes are recorded in `results/m4/acceptance.json`.

## PipeWire capture outage repair and closure (2026-11-08)

### Root cause and transport behavior

The capture bridge used `pa_simple_read()`. That synchronous Pulse-compatible call can remain blocked while the server is unavailable, so placing a timeout around it would return control while leaking a blocked worker. The capture side now owns an asynchronous libpulse mainloop and uses stream/context state checks, a read callback, bounded in-memory PCM, and a cancellable event loop. Connect is bounded to 3 seconds, each read fragment to 1 second, and cancellation is polled every 5 ms. Loss causes the bridge to close the Android-facing stream and release its worker. No stale PCM is replayed.

The HAL latches failure for the current capture stream and returns paced silence until standby/close; a later stream may connect again. The probe rejects a silent tail as `CAPTURE_FAILED`. An existing AudioRecord does not seamlessly reconnect. Recovery means create a fresh stream after the service is restored. Android permission revocation remains authoritative and prevents host capture from being reopened without a new authorized AudioRecord stream.

### Outage tests

`dbus-run-session -- python3 scripts/test_aaas_audio_pipewire.py` ran two private PipeWire/WirePlumber/pipewire-pulse outage and restart cycles. It verified controlled 440 Hz capture before and after outages. In-flight capture observed EOF 1.9–2.0 ms after service loss; while unavailable, a fresh capture attempt failed in 2.3–2.6 ms. SIGTERM joined the bridge worker and removed the socket in about 114 ms. The desktop audio service was not touched.

`AAAS_AUDIO_CAPTURE_APK=/tmp/AaasAudioCaptureProbe.apk python3 scripts/test_aaas_audio_android_outage.py` used the normal `--audio` AaaS runner and an isolated private PipeWire service. `m1b84_session_v6jzxitt` reported `CAPTURE_FAILED` with a silent tail after outage and the host stream closed in about 3.3 ms. After restarting the private service, `m1b84_session_a51g_5o4` created a fresh stream and captured 1,440,000 frames at 48 kHz mono, RMS 5656.45, 440 Hz dominant frequency, SHA-256 `ff728cc60861f9af534ae413b917c9bb87cfa00214ceb270526231e19934e67f`. Both sessions reached STOPPED. Android logs are retained in the workspace; the raw capture was not committed.

The bridge is bounded to four concurrent direct transport clients. A fifth is rejected, and a released slot accepts a subsequent client. This is intentional resource protection, not support for an arbitrary number of direct clients. Android playback tracks are mixed by AudioFlinger; concurrent Android client acceptance is separately recorded.

### Regression and build evidence

- `python3 -m unittest tests.test_aaas_audio -q`: 14 tests passed, including four-client limit, fifth-client rejection, slot release, disconnect cleanup, bridge shutdown, and probe silence classification.
- `python3 -m unittest discover -s tests -q`: 400 tests passed, zero failures/errors/skips.
- Private PipeWire outage test and live Android outage/recovery test passed.
- Android x86_64 HAL, memfd ashmem shim, and HIDL factory interposer rebuilt with `-Wall -Wextra -Werror`; hashes: HAL `d01a64d9d150b2bc2961f6b819f523e83678e594e7904b32b8fa35f78cb1fe4e`, shim `1b7e8759a139a00ff530d7eb35568470c7772e999a05f4419a33f52868e1c3f0`, factory `9d6aedb4d3e9dfc886a0fffff2936ce972b1d62e4099191b26dc917d6b418c19`.
- `python3 -m compileall -q scripts tests experiments/m4/audio experiments/m4/clipboard`, JSON validation, and `git diff --check` passed.

This closes the prior capture-outage blocker for M4's bounded failure and clean-recovery contract. It does not claim gapless playback/capture or automatic continuation of an active AudioRecord through a PipeWire daemon restart.

### Human listening follow-up (2026-11-10)

The user could not hear the earlier listening replay. The active Android
`STREAM_MUSIC` level was 5, while the host's default built-in Speaker sink was
already at 100% / 0 dB. The fixture tone is deliberately bounded at a PCM peak
of 3000/32767. A preceding monitor capture at the low Android level measured
peak 71 and RMS 27.11. These observations point to Android stream volume plus
the quiet diagnostic fixture, rather than a host sink setting or HAL sample
conversion fault.

The probe builder now accepts `--package-name` for isolated probe installs and
`--playback-music-volume N` (0–15). In that mode the app saves the existing
Android Music index, sets the requested index only during its short stereo and
mono playback sequence, then restores the saved index. No host sink or HAL gain
was changed. The isolated package `org.aaas.audiolisteningprobe` was built with
the existing development keystore (APK SHA-256
`dff6cb7b05e03300e844ea48b29aa398939b05c378605e054ce98930604ae2d4`), installed
through the active AaaS service, and launched on Android display 6/7. Android
logged:

```
TEST_MUSIC_VOLUME_SET value=15 previous=5
PLAYBACK_PAUSE_OK frames=48000
PLAYBACK_RESUME_OK
PLAYBACK_OK rate=48000 channels=2 frames=192000 pause_resume=ok mute=ok
MONO_PLAYBACK_OK rate=44100 channels=1 frames=44100
TEST_MUSIC_VOLUME_RESTORED value=5
```

An independent 48 kHz stereo capture from the default Speaker sink monitor
recorded 1,977,600 bytes over 10.3 seconds, with peak 3000 and RMS 660.84 over
the full capture. The two seconds containing the active test had RMS 1641.21
and 1343.34 because playback deliberately includes pause and mute intervals.
The user confirmed the replay was audible and clear. The test restored the
previous Android media volume (5), then the probe window was closed; the
persistent runtime remained active. This verifies human audibility for the
bounded test sequence. It does not change the saved volume preference in the
existing userdata; users can raise Android's media volume for ordinary app
playback.
