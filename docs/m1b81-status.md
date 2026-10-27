# M1B.8.1 status — 2026-10-27

**Overall: PARTIAL.** Keystore2's first failure is reproduced at the Binder
kernel boundary. Scoped diagnostic overlays let the framework set
`sys.boot_completed=1`, register hundreds of services, launch Settings, and
send Android startup-screen frames to Wayland. Accepted caller authorization,
source-built BPF repairs, a verified Settings first draw, and stable graphics
remain outstanding.

## Recovery and preservation

- Branch `master`, initial HEAD `2528409`; no configured remote. The inherited
  modifications to `scripts/test_zygote_startup.py` and
  `experiments/m1b/shim_selinux.c`, plus three untracked M1B.8 files, were
  copied before editing to external `tmp/m1b81_preedit/`. Their inventory and
  original component hashes are in `results/m1b81/experiment_inventory.json`.
- External workspace was confirmed on `/dev/sda2`, NTFS3, UUID
  `A2ACEDF2ACEDC0C1`, with the established capacity reserve intact. The
  original Android image and earlier logs were not changed.
- The inherited UWB, native NetworkStats, and Java statistics overlays were
  used as diagnostics. The latter two are still binary/DEX experiments, not
  accepted source-based compatibility fixes.

## Keystore2 / KeyMint failure

Baseline prefix `m1b81_keystore_baseline1_` reproduces the fatal
`LockSettingsService.initializeSyntheticPassword` call chain. Keystore2 and
KeyMint start and register; Keystore2 detects the version 4 KeyMint device and
completes shared-secret startup. The first failing Java call is
`IKeystoreService.getSecurityLevel(TRUSTED_ENVIRONMENT)`. Binder returns
`-95 EOPNOTSUPP` before Keystore2 dispatches it. A Keystore2-only ioctl trace
(`m1b81_keystore_trace1_`) shows ordinary `BINDER_WRITE_READ` ioctls returning
success, consistent with the error being delivered as a Binder read command.

The image's Keystore2 imports `AIBinder_setRequestingSid` and
`AIBinder_getCallingSid`; upstream Keystore2 constructs its Binder service
with `set_requesting_sid: true`. The host LSM list is
`capability,landlock,lockdown,yama,bpf`, with no SELinux LSM. The existing
development shim already strips the analogous caller-context flag from
ServiceManager's context-manager registration, but does not alter Keystore2's
ordinary Binder node.

`experiments/m1b/probe_binder_sid.c` independently sends identical one-way
transactions to fresh private binderfs instances. With
`FLAT_BINDER_FLAG_TXN_SECURITY_CTX` clear, the client receives
`BR_TRANSACTION_COMPLETE`; with it set, the client receives
`BR_FAILED_REPLY`. The probe uses no Android credentials or key material.
Together with the live `-95`, this supports a missing kernel security-context
conversion as the first Keystore2 failure. It does not prove that other
Keystore2 operations are healthy.

Diagnostic prefix `m1b81_keystore_sidprobe2_` prevents **only Keystore2** from
requesting the Binder SID. `getSecurityLevel` then dispatches, but
`importKey` fails explicitly at Keystore2 `utils.rs:106` because permission
checking has no caller SID. This confirms that simply removing the request is
not a usable fix.

Diagnostic prefix `m1b81_keystore_uidprobe1_` additionally permits only the
kernel-reported UID 1000 to be represented as the `system_server` SID;
other UIDs receive no SID. Keystore2 then reaches KeyMint `importKey`.
KeyMint reports `ROLLBACK_RESISTANCE_UNAVAILABLE` for the first request and
Android logs its documented fallback to a non-rollback-resistant key. A
successful retry and completed encryption/decryption were **not** verified.
This process-scoped compatibility probe is not a production authorization
mechanism: the host has no SELinux enforcement, and the context is synthetic.
It must remain opt-in and restricted to trusted diagnostic code.

The first probe run, `m1b81_keystore_sidprobe1_`, failed earlier because
Android's linker disallowed `/aaas_diag` in the default namespace. That log is
retained. The second probe uses `/data/local/tmp`, an allowed private path.

### Reproduction

The host Binder probe is built with:

```sh
cc -Wall -Wextra -Werror -O2 -o /run/media/mrkus/Homework/aaas-workspace/tmp/m1b81_probe_binder_sid experiments/m1b/probe_binder_sid.c
```

`python3 scripts/probe_binder_sid.py` mounts binderfs in a disposable
`unshare -Ur -m` namespace, creates a private device, and tests both flag
values with bounded subprocesses. The observed Binder replies are in
`results/m1b81/keystore_binder_diagnosis.json`.

The live runner accepts `AAAS_LOG_PREFIX`, `AAAS_KEYSTORE_TRACE=1`, and the
opt-in `AAAS_KEYSTORE_SID_PROBE=<compiled .so>`, along with the inherited UWB
and statistics overlay variables. Its changes remain in the preserved
uncommitted runner. All raw logs and tombstones use unique `m1b81_` prefixes
in the external `tmp` directory.

The scoped probe can be built freestanding with
`cc -shared -fPIC -nostdlib -Wl,-soname,libkeystore_sid_probe.so -o <output> experiments/m1b/probe_keystore_sid.c`.
Defining `AAAS_PROBE_NO_SID` reproduces the earlier no-SID variant. The
UID-gate unit test is `experiments/m1b/test_keystore_sid_probe.c`.

## Next fatal boundary

The UID-scoped Keystore2 probe allows ActivityManager ready phase and Settings
FallbackHome process creation, but `sys.boot_completed` never reaches `1`.
Both mediaserver and system_server first abort at
`libcodec2_client.so: Codec2Client::CacheServiceNames` with
`Check failed: serviceManager Hardware service manager is not running`.
Tombstones `m1b81_keystore_uidprobe1_tombstones/tombstone_00` and `_01`
contain the matching native stacks. The `hwservicemanager` process is alive
and answers other `getTransport` requests in the same run, so its mere process
state does not explain the failed `android.hidl.manager@1.2` lookup. The next
narrow experiment is to trace that HIDL lookup, hwbinder replies, and the
specific loaded client libraries in mediaserver and system_server.

A further **diagnostic-only** run, `m1b81_hwsm_sidprobe1_`, interposed
`android::hardware::setRequestingSid` only in hwservicemanager. The Codec2
assertion disappeared, supporting the same missing caller-context mechanism
for HIDL manager interface retrieval. This is not an authorization fix: the
HIDL manager's access policy has not been reconstructed or tested. The run
then reached a third native BPF-map constructor failure in
`BpfMapRO<unsigned int, StatsValue>::abortOnMismatch`, inside
`bpfGetUidStats()`. Tombstone `_00` records the precise stack. The inherited
NetworkStats diagnostic overlay covered two earlier template instantiations
but not this one. The immediate next task is a source-based unavailable-map
path that preserves `EBADF`/unavailable semantics across all three call sites.

The Android 16 Connectivity source was then cloned at
`627eb3c63e7c7cb3cb9f8ea319e4bb1676079c3a` to the external workspace.
`patches/m1b81/connectivity-networkstats-unavailable-map.patch` changes
`BpfNetworkStats.cpp` to initialize each pinned map through the existing
`Result`-returning `init()` API instead of the aborting pathname constructor.
It returns the original open error (such as `ENOENT` or `EACCES`), while valid
map type/flag mismatches still abort. The JNI factory now restores `errno`
from that negative result before returning its documented error sentinel.
The patch passes `git diff --check` but has **not** been built or loaded; it
does not by itself resolve the Java BatteryStats caller failures. The external
Git checkout retains the unmodified source in its HEAD, and the repository
patch is the reviewable change. No claim of NetworkStats repair follows from
the source patch alone.

## Remaining work

### Later diagnostic boot boundary

The checksum-guarded `scripts/patch_networkstats_uid_diagnostic.py` extends
the retained diagnostic overlay to the third BPF map template. In
`m1b81_network_uidprobe1_`, Android reached ActivityManager's "System now
ready" and phase 1000, then failed because
`/data/system_de/0/powerstats` was absent. The runner now creates that exact
directory with UID 1000 and mode 0700. In `m1b81_powerstats_dir1_`, the
PowerStats failure disappeared. The next fatal is `libmeminfo.so` build ID
`257fd9b6821b01b2d6a22e3015afda57`:
`ReadProcessGpuUsageKb` calls an aborting `BpfMapRO` pathname constructor
for a missing GPU statistics map. Tombstone
`m1b81_powerstats_dir1_tombstones/tombstone_01` records PC `0x14096` in
`abortOnMismatch` and PC `0x12a78` in `ReadProcessGpuUsageKb`.

Android 16 `platform/system/memory/libmeminfo` source revision
`d392610501ce556d7aa10d047e02f197256cd6a4` was retained in the
external workspace. `patches/m1b81/libmeminfo-unavailable-gpu-map.patch`
uses `BpfMapRO::init()` in both GPU map readers, returning their existing
`false` status with the real map-open error. It does not report zero GPU
usage or bypass valid-map metadata checks. Reverse-apply and whitespace
checks pass. The patch is **not built or deployed**, and its source revision
has not been matched to the loaded binary.

### Boot completion and Android frame capture with diagnostic overlays

`scripts/patch_meminfo_gpu_diagnostic.py` checks the original `libmeminfo.so`
SHA-256 `f0793a8cd9c637d4b4e1e3c4aec30d1821a1768a6b6d882b045b4bc2f22f4e3c`
and changes only the invalid-FD branch in its map metadata checker to take
the existing normal return. Valid FDs still take the metadata checks. Output
SHA-256 is `1b392b6b652a0e8d299e99003ab964d15d4cc40a4dbcd82e33add52ce6e6a8f8`.
The runner mounts it only when `AAAS_MEMINFO_LIB_OVERLAY` is set. This is a
reversible diagnostic, not an accepted implementation.

With that overlay plus the earlier Keystore, HIDL, UWB, native NetworkStats,
and Java statistics diagnostics, `m1b81_meminfo_probe1_` reached
`sys.boot_completed=1` after about six seconds. Binder listed 289 services.
`cmd activity start-activity -W -n com.android.settings/.Settings` returned
`Status: ok`; WindowManager reported a focused Settings window. These
results are diagnostic boot evidence and do not make the Keystore SID handling
or statistics overlays acceptable source fixes.

`m1b81_settings_presenter1_` ran the existing Wayland presenter alongside
Android: 59 submissions, 57 presentations, 2 discards, 58 releases, zero
rejections. `m1b81_settings_capture2_` enabled the presenter's existing
DMA-BUF frame dump: 22 submitted and presented frames, 21 releases, zero
rejections. The 22 Android buffer captures had eight distinct RGB hashes.
`results/m1b81/settings_capture2.json` records each frame hash and changed
pixel count. The last frame in `artifacts/m1b81_phone_starting.png` visibly
shows the genuine Android "Phone is starting..." progress screen. **No
captured frame shows the Settings interface.** SurfaceFlinger reported boot
finished near the last submitted frame, and later Settings launch/focus did
not produce another host submission. Its Binder dump timed out. The next
graphics investigation is why SurfaceFlinger stops submitting after the
startup screen despite the Settings window being focused.

An additional `m1b81_sftrace1_` run traced SurfaceFlinger and recorded 65
Composer3 submissions, with three layers and changing client-target pixel
ranges after the Settings launch. This shows the earlier frame-22 stop is
timing dependent. Those later buffers were not captured, so their content is
still unverified. A repeat `m1b81_settings_late1_` stalled before usable
frames; its logs remain in the workspace. During that run, the runner's
`unshare -f` parent exited while the namespace child kept stdout/stderr
open, allowing `communicate()` to outlive the 140-second deadline. The
diagnostic runner now starts a process group and kills that group at its
timeout. A local parent/child timeout probe confirmed the cleanup mechanism;
the modified runner has not yet had a repeat live timeout test.

`m1b81_settings_retry1_` captured frame 35, still showing "Phone is
starting..." despite Settings focus. The WindowManager dump named
`Splash Screen com.android.settings` as the top fullscreen opaque window.
In `m1b81_settings_stack3_`, a SIGQUIT trace from Settings PID 1107 showed
its main thread waiting in `DrawFrameTask::drawFrame`, while its RenderThread
waited in `BufferQueueProducer::dequeueBuffer` through
`ReliableSurface::hook_dequeueBuffer` and EGL `beginFrame`. This is an actual
first-draw blockage, not proof that Settings pixels were presented. The full
trace is retained externally as
`m1b81_settings_stack3_tombstones/trace_00`.

Another bounded run, `m1b81_dualstack1_`, made 73 host submissions but
Settings PID 1110 crashed in RenderThread before a useful SIGQUIT trace.
Tombstone `m1b81_dualstack1_tombstones/tombstone_04` records SIGSEGV in
`pthread_mutex_lock`, called from SwiftShader
`sw::DrawCall::run` at `vulkan.pastel.so` PC `0x199350`. The mutex address
in `rdi` points into libc read-only string data. The matching source call is
`draw->batchDataPool->borrow()` in `src/Device/Renderer.cpp`. This supports
an invalid pool/mutex pointer, but the allocation and corruption origin are
unidentified. No SwiftShader patch was made on this evidence alone. The
runtime remains timing sensitive, with a graphics crash distinct from the
earlier framework service blockers.

The boot run exposed repeated `EACCES` writes to
`/data/system/users/0/package-restrictions.xml` and settings files. The
diagnostic runner had pre-created `/data/system/users/0` as root. It now
assigns the `/data/system/users` chain to Android UID/GID 1000 and uses
init-compatible parent modes. In `m1b81_data_perm1_`, the same boot reached
completion and Settings focus; those exact PackageManager and SettingsState
write errors did not recur. This remains inherited, uncommitted runner work
until the full data topology and persistence are audited.

The inherited runner's recursive mode `0777` setup was changed to explicit
directory owners and modes. This remains uncommitted diagnostic work and
requires an init-rule and persistence audit before G5 can pass.

- **Key management:** Replace the opt-in SID diagnostic with a reviewed,
  source-based development policy that uses kernel caller identity, denies
  unknown callers, and does not advertise hardware guarantees. Verify actual
  key import and cryptographic round trip before treating KeyMint as functional.
- **Network statistics:** Build and ABI-check the new Android 16 Connectivity
  source patch, then replace the native binary diagnostic. Identify and patch
  the matching framework Java caller source, replacing the DEX diagnostic.
  Test missing, denied, corrupt, and valid BPF-map cases before live reuse.
- **Application data:** Validate the new explicit ownership and modes against
  Android init rules and persisted user data before treating the layout as secure.
- **Framework/UI/graphics:** Determine why SurfaceFlinger stops submitting
  after the startup screen, then capture actual Settings pixels. Verify
  PackageManager and ActivityManager functionality beyond registration. A
  full M1B.7.2 sustained graphics regression run remains outstanding.

## Tests and gates

Before diagnostic changes, the 73 Python tests, `make -C experiments/m1a test`,
and `scripts/android_workspace.py ... check` passed. The Binder probe compiled
with `-Wall -Wextra -Werror` and its two kernel transactions gave the expected
different replies. The UID-gate test passed for UID 1000, root, and app UID
10000. `python3 scripts/probe_binder_sid.py` also passed its bounded
end-to-end assertion. `python3 -m py_compile scripts/test_zygote_startup.py` and
`git diff --check` passed. After the later diagnostics, the 73 Python tests
and M1A tests passed again. The workspace check confirmed the intended NTFS3
mount, 17.1 GiB used against the 80 GiB ceiling, and more than the 20 GiB
reserve free. Live runs reached `sys.boot_completed=1` only with diagnostic
overlays. Settings did not complete a verified first draw and one run crashed
in SwiftShader, so stable boot and UI presentation remain unproven.

| Gate | Result | Evidence |
| --- | --- | --- |
| G1 historical work | PASS | Pre-edit snapshot, experiment inventory, untouched prior logs |
| G2 Keystore diagnosis | PASS | Live `-95`, scoped probe, isolated Binder flag A/B |
| G3 KeyMint functional | PARTIAL | Real `importKey` reached; crypto round trip unverified |
| G4 NetworkStats compatibility | PARTIAL | Diagnostic overlays only |
| G5 app-data correctness | PARTIAL | Real directory and narrowed modes; user settings write errors removed in one diagnostic run |
| G6 framework readiness | PARTIAL | 289 registered services and Settings focus with diagnostic overlays; functional probes incomplete |
| G7 boot completion | PARTIAL | Framework set `sys.boot_completed=1` in diagnostic runs; source fixes pending |
| G8 trusted activity | PARTIAL | Settings launch returned success and focus; first draw blocks in BufferQueue dequeue and one run crashed in SwiftShader |
| G9 Wayland activity pixels | FAIL | Startup progress pixels captured, no Settings pixels |
| G10 graphics baseline | PARTIAL | 59 host submissions in one live run; full sustained regression untested |
| G11 security/cleanup | PARTIAL | Isolated runs cleaned up; diagnostic SID handling remains insecure |
| G12 tests/reproducibility | PARTIAL | Baseline tests and new traces retained; fixes incomplete |

**M1B.8.1 remains partial.** No input bridge work was started.
