# Post-M1E Bluetooth Runtime Health

Status: **PASS / CLOSED — Bluetooth unavailable cleanly in rootless AaaS**

Date: 2026-11-02

This is a post-M1E runtime-health workstream. It does not reopen or alter
M1E's PASS/CLOSED decision. It establishes healthy behavior when the runtime
has no Bluetooth controller. It does not provide radio, pairing, discovery,
BLE, or GATT functionality.

## Finding and cause

The selected Android 16 image described a generic goldfish handheld as having
Bluetooth, while the AaaS rootless session had no controller transport or
permitted real-time scheduling for the Android Bluetooth process. The
Bluetooth framework therefore auto-enabled Bluetooth from persisted state and
bound `com.android.bluetooth/.btservice.AdapterService`. The baseline log
`m1b84_session_qcyqpliw` records six Bluetooth process starts, six deaths, and
six framework restart attempts in about 33 seconds.

There are two distinct defects in the inherited image/runtime combination:

1. `/system_ext/lib64/libbluetooth_jni.so` is a zero-byte placeholder. The
   matching Android 16 Bluetooth APEX JNI library is present, but redirecting
   the load to it does not make the stack usable in this rootless session.
2. With the matching JNI loaded, the Bluetooth worker requests
   `SCHED_FIFO` priority 1. The host kernel returns `EPERM`; the Bluetooth
   implementation treats that unsupported request as fatal.

The actual health defect is that the guest advertised optional hardware that
the session did not provide, causing Android to start a stack that cannot run
in the supported configuration. Android 16's `SystemServer` checks
`PackageManager.FEATURE_BLUETOOTH` and skips Bluetooth service startup when
the feature is absent ([Android 16 QPR2 SystemServer](https://android.googlesource.com/platform/frameworks/base/%2B/android16-qpr2-release/services/java/com/android/server/SystemServer.java)).
The Bluetooth APEX also depends on a chipset-provider HAL; the APEX's presence
alone is not evidence of a controller ([AOSP Bluetooth module](https://source.android.com/docs/core/ota/modular-system/bluetooth)).

The local Android source subset does not include the Bluetooth module source.
The supported rootless behavior is therefore to declare Bluetooth absent,
following Android's existing device-feature contract, rather than patch the
unavailable stack or grant scheduling privileges.

## Implementation

`scripts/aaas_bluetooth.py` derives a session-local, read-only runtime overlay
from the selected rootfs. It removes only the `android.hardware.bluetooth` and
`android.hardware.bluetooth_le` feature declarations, removes the Bluetooth
HCI HAL's init/VINTF registration, and removes the goldfish Bluetooth VHCI
forwarder block. The existing audio HAL and unrelated vendor init services are
left intact.

`scripts/run_aaas.py` creates the policy under the private session directory
and binds its files into that session before Android second-stage init. The
policy manifest records the base and overlay SHA-256 for every replaced file.
The bind helper verifies those hashes before generating the runner. Files are
read-only to Android and mode `0644`, matching Android configuration readers.
The session directory and receipt remain private to the owning user.

The base Android rootfs is never modified. There is no enabled mode until a
controller, matching Android 16 Bluetooth stack/HAL, and a least-privilege
scheduling design are all available. The production SwiftShader overlay is
unchanged. No host capability, scheduler setting, privileged helper, host
BlueZ ownership, or unrelated Android service was changed.

## Provenance

- Android release: 16.
- System fingerprint: `Android/sdk_phone64_x86_64/emu64x:16/BE2A.250530.026.D1/13818094:userdebug/test-keys`.
- System build ID: `BE2A.250530.026.D1`.
- `system/build.prop` SHA-256: `75c85036b61b6b43bbddb7a53eac31f701d8d349fa791af4ec32b521fc39c9f3`.
- Empty `/system_ext/lib64/libbluetooth_jni.so`: 0 bytes, SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- Android 16 APEX JNI: 15,226,152 bytes, SHA-256
  `34702b808383de76d623da8df84f14a434280268f8c0a66a22077c59d263f937`, Build ID
  `b20f0d8ca69e1fa215704ecdfe8a1db5`.
- Preserved base feature/init/VINTF file hashes and per-session overlay hashes
  are recorded in each session's `bluetooth-policy.json`.
- Production SwiftShader SHA-256 remains
  `1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`.

## Live validation

Four valid two-application sessions were run after the policy was installed:

| Session | Mode | RUNNING duration | Bluetooth framework branch | BT process starts/restarts | Presenter ownership | Terminal |
|---|---|---:|---|---:|---|---|
| `m1b84_session_e0pj9wne` | Default LMKD | 127.7 s | No Bluetooth hardware | 0 / 0 | Slot 1: 138/138; slot 2: 125/125; both outstanding 0 | STOPPED |
| `m1b84_session_jhmav59c` | Default LMKD repeat | 76.9 s | No Bluetooth hardware | 0 / 0 | Slot 1: 135/135; slot 2: 122/122; both outstanding 0 | STOPPED |
| `m1b84_session_5ycur_xe` | Source LMKD + cgroup | 79.6 s | No Bluetooth hardware | 0 / 0 | Slot 1: 132/132; slot 2: 118/118; both outstanding 0 | STOPPED |
| `m1b84_session__kr7uvaf` | Source LMKD + cgroup repeat | 74.9 s | No Bluetooth hardware | 0 / 0 | Slot 1: 131/131; slot 2: 118/118; both outstanding 0 | STOPPED |

In every valid session:

- Both Settings and Contacts were reported `RUNNING` in separate app slots,
  and Android published their distinct tasks on virtual displays 2 and 3.
- Both presenters produced and presented frames.
- Logcat contained exactly one `SystemServer: No Bluetooth Service
  (Bluetooth Hardware Not Present)` startup decision.
- There were zero `com.android.bluetooth` process starts/deaths, zero
  `MESSAGE_RESTART_BLUETOOTH_SERVICE` messages, zero Bluetooth service bind
  requests, and zero Bluetooth HCI HAL or VHCI forwarder starts.
- There were no fatal exceptions, fatal signals, or system_server ANRs in the
  accepted log window.
- Each normal shutdown balanced all presenter imports, submissions, and
  releases with zero outstanding buffers. The Android virtual display was
  released before shared-runtime shutdown.
- Both enhanced sessions removed their delegated cgroup hierarchies.

The log contains harmless Bluetooth-related `BluetoothAdapter: Bluetooth
service is null` messages from framework consumers such as audio routing, and
the audio stack may report that Bluetooth audio is unavailable. These are
expected when no Bluetooth framework service exists; they are not Bluetooth
process crashes and did not affect Settings, Contacts, or application
rendering. No pairing or radio operation was attempted.

One earlier implementation trial, `m1b84_session_je3fv_mq`, failed because
policy files were mode `0600`, preventing Android's `hwservicemanager` from
reading the bind-mounted VINTF file. The files were corrected to `0644`; that
trial is excluded from acceptance. Its log and session policy remain preserved.

The default and enhanced sessions used the same validated runtime policy. The
second run in each mode was a separate launch/shutdown cycle, not an in-session
retry. A baseline comparison is preserved in the older sessions: the six
restart attempts in `m1b84_session_qcyqpliw` contrast with zero in each of the
four accepted sessions.

## Verification

- Python suite: 226 passed.
- `make -C experiments/m1a test`: passed.
- `make -C experiments/m1a -B build/wayland-host-presenter test`: passed.
- `make -C experiments/m1c/input_adapter -B all`: passed.
- Composer tests passed from a disposable source copy so the inherited
  `experiments/m1b/composer_aaas/build/` directory was not touched.
- `make -C experiments/m1e/display_broker -B all`: passed.
- Android workspace guard: passed; the workspace remained below its 80 GiB
  working ceiling with more than the 20 GiB reserve.
- The three Bluetooth policy unit tests cover derivation, feature
  removal, unrelated-feature preservation, init/VINTF filtering, idempotent
  output, hashes, read permissions, and rejection of malformed source input.
- No changes were made to M1E status or acceptance records.

## Future Bluetooth device integration

This work does not add Bluetooth hardware support. Re-enable the capability
only after all of the following are provided and verified together:

1. A matched Android 16 Bluetooth APEX/APK/JNI package and removal of the
   zero-byte system_ext placeholder through a versioned overlay.
2. A real or deterministic simulated HCI controller transport and matching
   AIDL Bluetooth HAL with correct VINTF and SELinux policy.
3. A least-privilege, bounded scheduling design for Bluetooth real-time
   workers; do not grant broad host capabilities or change global scheduler
   policy.
4. One explicit controller owner. Host BlueZ and Android must not control the
   same physical adapter concurrently.
5. Session-scoped host-device permissions, pairing/user consent, teardown,
   and tests for adapter enable/disable, discovery, BLE/GATT, controller loss,
   and app permissions.
6. Hardware-independent automated tests followed by supported controller
   integration tests.

Until those prerequisites exist, the truthful supported state is
**Bluetooth unavailable**. This workstream is **PASS / CLOSED** for runtime
health in that configuration; Bluetooth device integration remains future
work.
