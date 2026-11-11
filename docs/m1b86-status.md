# M1B.8.6 status — opt-in rootless cgroup v2 memory policy

**Overall: PASS for the opt-in rootless policy; no production Android memory-policy parity is claimed.**

AaaS now has an explicit `--memory-policy=cgroup` mode that discovers the current user's delegated cgroup v2 scope, creates a disposable session hierarchy, classifies live Android processes from ActivityManager state, and applies conservative `memory.low` / `memory.high` values. The default `python3 scripts/run_aaas.py` path is unchanged. Source-built LMKD, ActivityManager connectivity, PSI/vmstats fallback, Settings, and the SwiftShader/Wayland graphics path remain intact.

## Scope and starting state

- Branch `master`, starting HEAD `86f8688`, no Git remote.
- Inherited uncommitted M1B.8 files remained unstaged and unchanged: `experiments/m1b/shim_selinux.c`, `scripts/test_zygote_startup.py`, `docs/m1b8-status.md`, `experiments/m1b/shim_dns_helper.c`, `experiments/m1b/shim_netd_updatable.c`.
- `results/m1b86/preservation_manifest.json` records the inherited hashes, overlay hashes, workspace check, and initial Git status.
- No `sudo`, `pkexec`, root helper, host-wide cgroup change, global procfs weakening, or host pressure was used.
- No prior milestone result was deleted or rewritten.

## Delegated hierarchy discovery

`scripts/aaas_cgroup.py` discovers the AaaS scope from the current process's cgroup rather than a hardcoded boot path:

1. Parse exactly one `0::` entry from `/proc/self/cgroup`.
2. Find the enclosing `user@<uid>.service`.
3. Use its `aaas` child, or a validated `AAAS_CGROUP_ROOT` override.
4. Verify the cgroup2 mount, `memory` in `cgroup.controllers`, and the no-internal-process constraint before enabling `+memory`.

The live root is `/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/aaas`; the cgroup2 mount carries `nsdelegate,memory_recursiveprot,memory_hugetlb_accounting`, and the root has `cpu memory pids` controllers with `memory` in `cgroup.subtree_control`. `system` and `apps` are the existing Android libprocessgroup branches. Full details are in `results/m1b86/delegation_inventory.json`.

## Design

The session creates:

```text
aaas/m1b86-<session>/
  critical/
  foreground/
  background/
  cached/
```

Android's existing `system/uid_*/pid_*` and `apps/uid_*/pid_*` leaves remain the identity boundary. Non-anchor processes are moved into the class leaves. **cgroup v2 does not migrate existing memory charges when a process moves**, so the original pid leaf that owns the already-faulted pages receives the same class protection in place. This is essential for effective protection of a running Android process.

Policy table (values are byte counts for `memory.low`/`memory.high`; no hard Android `memory.max` is used):

| Class | Class leaf `memory.low` | Class leaf `memory.high` | Original leaf `memory.low` | Original leaf `memory.high` |
| --- | ---: | ---: | --- | ---: |
| critical | 512 MiB | max | `min(128 MiB, max(8 MiB, current/2))` | max |
| foreground | 384 MiB | max | `min(128 MiB, max(8 MiB, current/2))` | max |
| background | 0 | 512 MiB | 0 | 256 MiB |
| cached | 0 | 256 MiB | 0 | 128 MiB |

`memory.oom.group=0` is written explicitly. Boot-chain anchors (`init`, `ueventd`, `system_server`, `zygote`, `servicemanager`, `hwservicemanager`, `lmkd`) are protected in place with `memory.low=256 MiB` and are not moved, preserving libprocessgroup/zygote lifecycle management.

`memory.low` is best-effort relative protection. `memory.high` is a soft reclaim throttle for background/cached classes. No `memory.max` is set on Android classes, so this policy does not create a second kernel OOM killer next to LMKD.

## Authoritative priority source

`ProcessPolicyMonitor` runs `dumpsys activity processes` inside the system_server namespaces with `nsenter`, then parses each `ProcessRecord`'s:

- `oom adj: ... cur=<n>`
- `curProcState=<n>`
- `cached=true|false`

Classification:

- **critical**: `cur < 0` or `procState <= 1` (persistent/persistent UI).
- **foreground**: `cur <= 200` or `procState <= 6` (top/visible/important foreground).
- **cached**: `cached=true`, `cur >= 900`, or `procState >= 14`.
- **background**: the remaining ActivityManager-managed processes.
- **unknown**: leave the process unmanaged rather than guessing; a process in the `apps` branch without ActivityManager state falls back to `background` with no extra protection.

This matters because Settings reports `cur=0`, `procState=2` (TOP) while `/proc/<pid>/oom_score_adj` remains `200` after the rootless write failure. The authoritative ActivityManager value correctly places Settings in `foreground`; the kernel-visible value alone would not.

Native processes absent from ActivityManager are classified from their libprocessgroup branch: `system/*` is critical, `apps/*` is background. Process names are not used to infer foreground state.

## Process identity and PID reuse

Every candidate is verified with:

- host PID and `/proc/<pid>/stat` start time;
- host UID and `NSpid` mapping (the last `NSpid` is the Android-visible PID, used to join ActivityManager records);
- current cgroup path, required to be under the delegated `aaas` root;
- start time at or after the session start, so stale processes from an earlier boot are rejected;
- `pidfd_open` held across the migration, then the identity is re-read after the move.

A stale identity is rejected if the start time changed, the process exited, the UID changed, the cgroup changed, or the process is outside the AaaS scope. Tests cover unrelated host processes and PID reuse.

## Live acceptance run

Target command:

```sh
python3 scripts/run_aaas.py --use-source-lmkd --memory-policy=cgroup
```

Session: `$AAAS_WORKSPACE/tmp/m1b84_session_a_op34s_`
Cgroup: `/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/aaas/m1b86-625505`

Observed at the snapshot:

- 64 Android processes in policy class leaves: 55 critical, 5 foreground, 0 background, 4 cached.
- Foreground included Settings, Launcher3, `android.ext.services`, the Latin IME, and the permission controller.
- Cached included `com.android.cellbroadcastreceiver`, its module, `com.android.sdksetup`, and `com.android.devicelockcontroller`.
- `system_server`, `lmkd`, `ueventd`, and `servicemanager` were protected in place; `system_server` original leaf had `memory.low=256 MiB`.
- 26 policy ticks, 0 errors, 0 degraded ticks, 72 class assignments/updates.
- Policy log: `results/m1b86/acceptance_policy_events.jsonl`; snapshot: `results/m1b86/live_policy_snapshot.json`.

Rendering and Android health:

- 254 frames presented, 2 discarded, **0 rejected**.
- `ActivityManager: Connection with lmkd established`.
- `LMKD memevents ring buffer unavailable (2); using vmstats fallback`.
- Repeated `Error writing /proc/<pid>/oom_score_adj; errno=13` was observed and is reported honestly: rootless non-positive `oom_score_adj` remains impossible.
- A live cached-process `force-stop` produced an `exit` event; the original pid leaf was reset from `memory.high=128 MiB` to `max`, proving the prune path does not leave stale policy.

## Measured protection

`scripts/probe_cgroup_protection.py` uses only disposable children of the delegated `aaas` scope:

- Two sibling workloads hold 96 MiB of file-backed pages each.
- Protected sibling: `memory.low=48 MiB`; unprotected sibling: `memory.low=0`.
- A bounded 64 MiB anonymous pressure child runs under a 224 MiB parent `memory.max`.

Result (`results/m1b86/cgroup_protection.json`):

- Protected sibling lost **544,768 bytes**; unprotected sibling lost **41,267,200 bytes**.
- Parent hit its soft/hard budget (`memory.events.max` increased) but **`oom_kill=0`** in the parent and all children.
- Both workers were alive when measured; the hierarchy was removed (`cleaned_up=true`).

This is a relative protection measurement, not a guarantee. It demonstrates that the configured `memory.low` changes sibling reclaim behavior without creating a kernel OOM event.

## LMKD and background behavior

The source-built LMKD hash was unchanged at `a36135b6948342163186fe57acb9de0245fe00aeafcb9556c48a2e4c52f291ce`. ActivityManager connectivity and the vmstats fallback were re-verified. The kernel-visible `oom_score_adj` failure remains the known rootless limitation; no claim of LMKD/production parity is made.

This milestone did not rerun the isolated two-process LMKD victim-selection matrix under the new class hierarchy. The M1B.8.5 selection evidence remains in `results/m1b85/lmkd_selection.json` and is not replaced or reinterpreted.

## Default-path regression

`python3 scripts/run_aaas.py` with no policy flag:

- Session `$AAAS_WORKSPACE/tmp/m1b84_session_76148693`.
- Reached RUNNING, then clean STOPPED.
- 259 frames presented, **0 rejected**.
- No `m1b86-*` cgroup was created.

The default diagnostic LMKD selection and the pre-existing runtime behavior are unchanged.

## Cleanup and restart

- Session hierarchy removed: `removed=True`, `failures={}`.
- No `m1b86-*` cgroup remained after shutdown.
- Zero non-default empty pid leaves and zero non-default uid-level leaves remained in `system`/`apps` after the acceptance run.
- Shutdown resets original leaf policies even when Android processes exit before cleanup.
- `prune()` resets original policies when a managed process exits mid-session.
- `cleanup_stale_in_place()` sweeps empty leaves at session start for interrupted/crashed runs.
- A second live start after a prior run recreated the hierarchy cleanly.

## Regressions

- `python3 -m unittest discover -s tests`: **111 tests OK**.
- `make -C experiments/m1a test`: all wire, sync, and stress tests PASS.
- Workspace check: `used_bytes=18,687,909,376` (17.40 GiB), `free_bytes=352,212,221,952` (328.02 GiB), 80 GiB ceiling and 20 GiB reserve intact.
- Presenter still uses the verified SwiftShader overlay `1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`.
- No GPU zero-copy, security isolation, or production parity claim is made.

## Gate report

| Gate | Status | Evidence |
| --- | --- | --- |
| G1 preservation | PASS | `results/m1b86/preservation_manifest.json`; inherited hashes unchanged; HEAD `86f8688` |
| G2 delegated root discovery | PASS | `results/m1b86/delegation_inventory.json`; discovered from `/proc/self/cgroup` |
| G3 hierarchy lifecycle | PASS | acceptance cleanup `removed=True`, `failures={}`; no session cgroups remain |
| G4 identity / PID reuse | PASS | `tests/test_m1b86_memory.py`; starttime/UID/NSpid/cgroup/session checks; pidfd |
| G5 authoritative priority | PASS | ActivityManager `cur`/`procState`; Settings TOP, system_server persistent |
| G6 Android class placement | PASS | 55 critical, 5 foreground, 0 background, 4 cached in the acceptance snapshot |
| G7 protection measurement | PASS | protected 0.54 MiB vs unprotected 41.27 MiB lost; no OOM |
| G8 bounded pressure isolation | PASS | disposable hierarchy only; workers alive; hierarchy removed |
| G9 LMKD preservation | PASS | connection established; vmstats fallback; errno=13 reported |
| G10 Settings/Wayland | PASS | 254 frames presented, 0 rejected |
| G11 default launcher | PASS | default session 259 frames presented, 0 rejected; no policy cgroups |
| G12 cleanup/restart | PASS | prune reset, shutdown reset, stale sweep, zero non-default leaves |
| G13 automated regressions | PASS | 111 Python tests; `make -C experiments/m1a test` |
| G14 workspace budget | PASS | 17.40 GiB used, 328.02 GiB free, 80 GiB ceiling / 20 GiB reserve |
| G15 honest limitations | PASS | limitations below are explicit and not hidden |

Acceptance JSON: `results/m1b86/acceptance.json`.

## Limitations and next experiments

1. **Non-positive `oom_score_adj` is impossible rootlessly.** `capable(CAP_SYS_RESOURCE)` checks the initial user namespace; LMKD logs `errno=13`. Android foreground and negative priorities are not reproduced at the kernel-visible level. Next experiment: none for parity; this remains out of scope.
2. **Existing charges do not move.** The policy writes to both the class leaf and the original pid leaf. This is intentional; a future optimization could allocate new processes directly into class leaves.
3. **Activity-level transitions were not triggered.** Settings is the only Wayland window; hiding or closing it would terminate the `--exit-on-close` presenter. Controlled disposable transitions and a real cached-process exit/prune were used instead. Next experiment: add a controlled HOME/foreground input path and observe a real Settings transition.
4. **SurfaceFlinger is outside the `aaas` cgroup** in this runtime and was left untouched. Next experiment: verify libprocessgroup/freezer semantics before moving it into `critical`.
5. **No new LMKD kill selection under policy.** The M1B.8.5 two-round selection evidence is retained. Next experiment: run isolated LMKD selection with disposable processes in the new classes.
6. **`memory.low` is best-effort.** It is not a guarantee; the policy sets no `memory.max` on Android classes. `memory.high` throttling was not exercised against live Android workloads.
7. **No production/security/hardware claims.** Security isolation and hardware zero-copy remain out of scope.

## Reproduction

```sh
python3 -m unittest discover -s tests
make -C experiments/m1a test
python3 scripts/android_workspace.py \
  --workspace $AAAS_WORKSPACE check
python3 scripts/probe_cgroup_protection.py \
  --output results/m1b86/cgroup_protection.json
python3 scripts/run_aaas.py --use-source-lmkd --memory-policy=cgroup
```
