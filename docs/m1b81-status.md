# M1B.8.1 status — 2026-10-27

**Overall: PARTIAL.** Keystore2's first failure is explained and reproduced at the
Binder kernel boundary. A scoped diagnostic advanced framework startup into
synthetic-password key import. Stable boot, production-equivalent caller
authorization, source-based NetworkStats repair, and Settings presentation are
not yet established.

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
- **Framework/UI/graphics:** Resolve libmeminfo and later boot blockers, probe
  PackageManager and ActivityManager while alive, launch a genuine Settings
  activity, and verify its pixels through the existing Wayland presenter. No
  M1B.7.2 live graphics regression run was performed in this investigation.

## Tests and gates

Before diagnostic changes, the 73 Python tests, `make -C experiments/m1a test`,
and `scripts/android_workspace.py ... check` passed. The Binder probe compiled
with `-Wall -Wextra -Werror` and its two kernel transactions gave the expected
different replies. The UID-gate test passed for UID 1000, root, and app UID
10000. `python3 scripts/probe_binder_sid.py` also passed its bounded
end-to-end assertion. `python3 -m py_compile scripts/test_zygote_startup.py` and
`git diff --check` passed. Live runs did **not** pass framework boot.

| Gate | Result | Evidence |
| --- | --- | --- |
| G1 historical work | PASS | Pre-edit snapshot, experiment inventory, untouched prior logs |
| G2 Keystore diagnosis | PASS | Live `-95`, scoped probe, isolated Binder flag A/B |
| G3 KeyMint functional | PARTIAL | Real `importKey` reached; crypto round trip unverified |
| G4 NetworkStats compatibility | PARTIAL | Diagnostic overlays only |
| G5 app-data correctness | PARTIAL | Real directory and narrowed modes in diagnostic runner; full audit pending |
| G6 framework readiness | PARTIAL | Reached phase 1000; libmeminfo then aborts system_server |
| G7 boot completion | FAIL | `sys.boot_completed` never `1` |
| G8 trusted activity | PARTIAL | FallbackHome forked, not sustained |
| G9 Wayland activity pixels | FAIL | Not tested |
| G10 graphics baseline | UNVERIFIED | Historical evidence retained; no new live test |
| G11 security/cleanup | PARTIAL | Isolated runs cleaned up; diagnostic SID handling remains insecure |
| G12 tests/reproducibility | PARTIAL | Baseline tests and new traces retained; fixes incomplete |

**M1B.8.1 remains partial.** No input bridge work was started.
