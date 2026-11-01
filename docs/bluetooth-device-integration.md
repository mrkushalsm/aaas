# Android Bluetooth device integration plan

Status: **future work; rootless runtime currently cannot start the optional stack**

This plan is separate from M1E's two-window desktop contract. No Bluetooth
controller, discovery, pairing, BLE, or GATT capability is claimed.

## Current runtime finding (2026-11-02)

The Android 16 image includes `Bluetooth.apk` through a system_ext symlink into
`com.android.bt`, and the matching Android 16 APEX library exists at
`/apex/com.android.bt/lib64/libbluetooth_jni.so`. The corresponding
`/system_ext/lib64/libbluetooth_jni.so` path in the selected rootfs is a zero
byte placeholder. In normal runtime sessions the Bluetooth service therefore
fails while loading JNI and Android retries it.

A disposable session-only bind of the APEX-matched library made JNI load
successfully (Build ID `b20f0d8ca69e1fa215704ecdfe8a1db5`, SHA-256
`34702b808383de76d623da8df84f14a434280268f8c0a66a22077c59d263f937`). The
stack then aborted because its `bt_main_thread` could not set SCHED_FIFO
priority 1: `sched_setscheduler` returned `EPERM`, and the Android Bluetooth
code treats that failure as fatal. This second failure means copying or
linking the correct library alone is not a complete fix. No system image or
persistent host policy was changed. The local Android source subset does not
contain `packages/modules/Bluetooth`, so an image-matched source correction is
not available here.

The app windows, SurfaceFlinger, and system_server remained alive in the
examined runs. This is recorded as a documented rootless capability blocker,
not as a Bluetooth PASS or a packaging fix. Do not grant extra host capability,
change scheduler policy, suppress the crash, or disable the service as an
unreviewed workaround.

## Future implementation sequence

1. **Pin and audit the Android stack.** Record the Android build fingerprint,
   Bluetooth APK/APEX versions, JNI and HAL build IDs, VINTF declarations,
   SELinux policy, linker namespace configuration, and the exact system_ext
   packaging rule. Build Java, JNI, and HAL components from one matching Android
   revision. Replace the zero byte stub only through the versioned image-overlay
   flow after the build and ABI match are demonstrated.
2. **Choose one controller owner.** Decide whether Android receives a virtual
   HCI controller (for example, a kernel VHCI/USB transport) or a dedicated
   controller interface. Do not let Android and host BlueZ concurrently own
   one physical HCI device. Define whether host BlueZ remains the controller
   owner and which upstream transport, if any, is supported; a BlueZ D-Bus
   facade is not equivalent to Android's HCI/HAL contract.
3. **Resolve rootless scheduling deliberately.** Determine the least-privilege
   supported way for the Bluetooth stack to request its documented real-time
   worker scheduling inside the runtime. Prefer a bounded, session-scoped
   mechanism with explicit ownership and teardown. If this requires a host
   capability or kernel interface unavailable to an unprivileged session,
   treat that as a prerequisite and expose Bluetooth as unavailable. Do not
   change global scheduler or privilege policy for M1E.
4. **Define user and security boundaries.** Map Android runtime permissions,
   pairing consent, discoverability, and per-app Bluetooth permissions to the
   Linux user's explicit device grant. Keep device access scoped to the session;
   avoid a permanent privileged daemon and avoid exposing unrelated host
   adapters or devices.
5. **Add staged coverage.** Start with HAL initialization and controller
   registration; then adapter enable/disable, discovery, pairing, BLE scan,
   GATT connection, disconnect, runtime close/reopen, and permission revocation.
   Test with a deterministic simulated controller first, then supported host
   hardware. Verify that host BlueZ and Android do not contend for the same
   controller and that teardown removes session resources.
6. **Track separately from desktop M1E.** Bluetooth device integration should
   be a future device-integration milestone. It can reuse AaaS's session,
   permission, and lifecycle infrastructure but does not change the native
   Wayland application-window acceptance contract.

## Dependencies and licensing review

Prefer Android's pinned Bluetooth module and HAL interfaces already present in
its APEX/VINTF image. Any Linux controller transport or virtual-HCI helper must
be evaluated for kernel availability, required capabilities, distribution
packaging, and license compatibility before adoption. No new dependency is
selected by this plan.

## Entry criteria

Begin implementation only after matching Bluetooth module sources/build
artifacts are available, the controller ownership model is selected, the
rootless scheduling requirement has a least-privilege design, and a safe
simulated-controller test environment is identified. Until then the accurate
state is **unavailable in the current rootless image**.
