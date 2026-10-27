# M1B.8 continuation: UWB resource scan and next boot failure

On 2026-10-27, the existing uncommitted Gemini framework boot work was preserved. The Android 16 runtime reached RangingService and crashed because its resource APK lookup returned null. The unpatched baseline log is in the external workspace under prefix m1b8_codex_baseline_.

## UWB diagnosis and tested correction

The signed com.android.uwb.resources APK is present. PackageManager scans it through /system_ext/priv-app/ServiceUwbResources/ServiceUwbResources.apk, which points into the extracted APEX. The original UwbContext.isAppInUwbApex() accepts only an ApplicationInfo.sourceDir beginning /apex/com.android.uwb. That excludes the installed APK and causes the null package name passed to createPackageContext().

scripts/patch_uwb_resource_scan.py modifies only this predicate. It retains the original APEX path check and also accepts the exact resources package under the system_ext scan directory. It verifies the original JAR SHA-256 before patching, leaves that JAR untouched, and replaces only classes.dex in an overlay copy. Apktool 2.9.3 was used for this diagnostic build; the tool JAR and both Android JARs are preserved in the external workspace. The rebuilt overlay SHA-256 is recorded in results/m1b8/uwb_reproduction.json.

Build:

    python3 scripts/patch_uwb_resource_scan.py \
      --original /run/media/mrkus/Homework/aaas-workspace/tmp/m1b8_service-ranging.original.jar \
      --apktool /run/media/mrkus/Homework/aaas-workspace/tmp/m1b8_apktool_2.9.3.jar \
      --output /run/media/mrkus/Homework/aaas-workspace/tmp/m1b8_service-ranging.rebuilt2.jar

Live diagnostic launch:

    AAAS_LOG_PREFIX=m1b8_uwb_rebuilt2_ AAAS_BOOTANIM=0 AAAS_BOOT_WAIT=20 \
    AAAS_RANGING_JAR_OVERLAY=/run/media/mrkus/Homework/aaas-workspace/tmp/m1b8_service-ranging.rebuilt2.jar \
    python3 scripts/test_zygote_startup.py

The log contains "Found Uwb Resources APK at: com.android.uwb.resources" and "RangingService: Registering Ranging service" on repeated system_server starts. An earlier rebuild failed ART verification due to incorrect smali register use; that failed artifact and log remain under m1b8_uwb_rebuilt1_. The corrected build passed this live check.

## Current boot boundary

Framework boot remains incomplete. At boot phase 550, system_server aborts in the Android tethering APEX libnetworkstats.so while reading network statistics. The tombstone identifies build ID e1b05e69b0136229f3972fd3bc807aed, BpfMapRO<unsigned int, unsigned int>::abortOnMismatch(bool)+676, called by parseBpfNetworkStatsDetail(). Disassembly shows a negative BPF map FD branches to abort() at library offset 0x20080. The isolated rootless runtime has no usable pinned network-statistics BPF maps; its BPF loader fails. This is a separate framework readiness blocker.

The next source change needs to handle absent BPF statistics at the
NetworkStats and BatteryStats boundary without aborting system_server.
Any compatibility behavior must report statistics unavailable or explicitly
empty; it must not claim real traffic accounting. Then verify boot
completion and the Settings activity before adding input.

An isolated binary diagnostic (external workspace prefix m1b8_bpf_diag2_)
let both BpfMapRO template specializations return with their negative map FDs.
It was **not** installed in the rootfs or accepted as a production patch.
This exposed the next causal boundary: native network statistics returns
Bad file descriptor; NetworkStatsFactory throws IOException; the BatteryStats
Wi-Fi collector wraps it as an uncaught IllegalStateException in
system_server. ActivityManager printed "System now ready" during this
diagnostic, but system_server restarted and sys.boot_completed did not
stabilize. The exact tombstones and logcat are retained in the external
workspace.

## Verification boundary

The Python suite passed 73 tests, M1A transport and synchronization tests passed, and the external-workspace mount and budget check passed. No interactive Android activity, Wayland input delivery, or new sustained graphics run was demonstrated in this continuation. The M1B.8 milestone is **partial**.
