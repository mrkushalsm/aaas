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

The UID-scoped probe allows ActivityManager ready phase and Settings
FallbackHome process creation, but `sys.boot_completed` never reaches `1`.
Both mediaserver and system_server abort at
`libcodec2_client.so: Codec2Client::CacheServiceNames` with
`Check failed: serviceManager Hardware service manager is not running`.
Tombstones `m1b81_keystore_uidprobe1_tombstones/tombstone_00` and `_01`
contain the matching native stacks. The next narrow experiment is to trace
why `defaultServiceManager()` for HIDL is unavailable in those processes,
checking hwservicemanager, hwbinder namespace access, and loaded libraries.
Do not suppress the Codec2 assertion without establishing its service contract.

## Remaining work

- **Key management:** Replace the opt-in SID diagnostic with a reviewed,
  source-based development policy that uses kernel caller identity, denies
  unknown callers, and does not advertise hardware guarantees. Verify actual
  key import and cryptographic round trip before treating KeyMint as functional.
- **Network statistics:** Identify the closest source baseline for the loaded
  tethering library and framework JAR. Replace diagnostic machine-code/DEX
  overlays with narrow source patches that distinguish unavailable BPF maps
  from valid empty results, then rebuild and retest.
- **Application data:** `/data/data` is now a real directory, which allows
  app spawning. The inherited runner still applies recursive mode `0777` to
  `/data` and `/data_mirror`; ownership and modes must be aligned with the
  image's init rules before calling this correct or secure.
- **Framework/UI/graphics:** Resolve Codec2 and later boot blockers, probe
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
| G5 app-data correctness | PARTIAL | Real directory; modes still too broad |
| G6 framework readiness | FAIL | Codec2 aborts system_server |
| G7 boot completion | FAIL | `sys.boot_completed` never `1` |
| G8 trusted activity | PARTIAL | FallbackHome forked, not sustained |
| G9 Wayland activity pixels | FAIL | Not tested |
| G10 graphics baseline | UNVERIFIED | Historical evidence retained; no new live test |
| G11 security/cleanup | PARTIAL | Isolated runs cleaned up; diagnostic SID and modes are insecure |
| G12 tests/reproducibility | PARTIAL | Baseline tests and new traces retained; fixes incomplete |

**M1B.8.1 remains partial.** No input bridge work was started.
