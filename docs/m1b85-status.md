# M1B.8.5 status — source-built LMKD and delegated memory control

**Overall: PARTIAL.** The Android 16 LMKD source is now built reproducibly from pinned revisions, its exact patch set is verified, and the binary runs inside the existing AaaS Android/Wayland session. Rootless `oom_score_adj` behavior is characterized, delegated cgroup v2 memory control is demonstrated with bounded pressure, and a real LMKD instance selects the highest-priority disposable victim under cgroup-local PSI. Android foreground and negative priorities still cannot be written through procfs without initial-user-namespace `CAP_SYS_RESOURCE`, and the selection probe lowers one LMKD stall threshold so bounded pressure reaches the kill decision. No host-wide memory policy or security setting was changed.

## Preservation and starting state

Initial branch `master`, HEAD `963a606`, no Git remote. The inherited M1B.8 worktree files listed in `results/m1b85/preservation_manifest.json` were not staged or rewritten. The external workspace remained `/dev/sda2` on NTFS3 (`A2ACEDF2ACEDC0C1`). The existing diagnostic LMKD overlay remained SHA-256 `9780759ba36e50d061064f05c77520809f3291edad6a43a1495e9d91f21d54bd`; the SwiftShader overlay remained SHA-256 `1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`. No Android image or inherited diagnostic binary was overwritten.

## Reproducible LMKD build and provenance

`scripts/build_lmkd.py` builds the pinned Android 16 `lmkd` sources against the existing Android rootfs and Bionic/libc++ headers. Two independent builds produced the same SHA-256 `a36135b6948342163186fe57acb9de0245fe00aeafcb9556c48a2e4c52f291ce` (193,696 bytes). The receipt is `results/m1b85/lmkd_build_receipt.json`.

Before compiling, the script now verifies:

- each source checkout is at the commit pinned in `results/m1b85/source_manifest.json`;
- the working tree contains only the pinned patches;
- `git diff HEAD` is byte-identical to the applied patch files for `lmkd-android16`, `libmeminfo-android16`, and `connectivity-android16`;
- no unexpected untracked files exist.

The verified patch set is `patches/m1b83/lmkd-absent-memevents-fallback.patch` (LMKD), `patches/m1b81/libmeminfo-unavailable-gpu-map.patch`, and `patches/m1b81/connectivity-networkstats-unavailable-map.patch`. The LMKD patch remains necessary because the container has no BPF loader and no `/sys/fs/bpf/memevents/map_bpfMemEvents_lmkd_rb`; it makes `ENOENT`/`EACCES` on the ring buffer select the existing vmstats fallback instead of waiting forever. Build flags and the resulting binary hash are unchanged by the provenance checks.

`results/m1b85/lmkd_abi.txt` records the ABI: ELF64 x86-64 PIE, interpreter `/system/bin/linker64`, build ID `96eadc7560482189dfeb5772c0150e3728cc30ac`, and all `NEEDED` libraries resolved by `linker64 --list` inside the rootfs.

## Live source-built LMKD

`python3 scripts/run_aaas.py --use-source-lmkd` selects the source build through `AAAS_LMKD_OVERLAY`; the default command still selects the checksum-guarded diagnostic overlay.

| Run | Session | Result |
| --- | --- | --- |
| default diagnostic LMKD | `m1b84_session_i38__rmm` | RUNNING in 16.8 s, 479 imports / 453 presented, 0 rejected, clean STOPPED |
| source-built LMKD | `m1b84_session_m9gqzlrg` | RUNNING in 16.8 s, 486 imports / 462 presented, 0 rejected, clean STOPPED |

Both runs used the inherited runner and presenter, reached `RUNNING` only after `sys.boot_completed=1` and `pidof com.android.settings` succeeded, logged `ActivityManager: Connection with lmkd established`, and left no `lmkd`, `bwrap`, presenter, or Settings process. The source run additionally logged `LMKD memevents ring buffer unavailable (2); using vmstats fallback`; the default run did not, confirming the selected binary. In both runs the live LMKD process was UID `101068`, `oom_score_adj=200`, with effective capabilities `0000000001804022` (including raw `CAP_SYS_RESOURCE`).

Structured evidence: `results/m1b85/live_default.json`, `results/m1b85/live_source_lmkd.json`.

## Rootless oom_score_adj

`scripts/probe_oom_score_adj.py` tested disposable children only, on the host, inside a bubblewrap user namespace, and inside a user namespace with `CAP_SYS_RESOURCE` added. In all three environments:

- `100`, `900`, and `1000` were written successfully;
- `0`, `-1`, `-900`, and `-1000` failed with `EACCES` (errno 13);
- adding namespace-scoped `CAP_SYS_RESOURCE` did not change the result.

The kernel checks `capable(CAP_SYS_RESOURCE)`, which resolves against `init_user_ns`; a capability in the container user namespace cannot satisfy it. The inherited session floor is also visible: `user@.service` carries `OOMScoreAdjust=100`, the user manager defaults to 200, and session processes observed at 200. Rootless Android foreground/negative priorities are therefore **blocked**, not merely unimplemented. Evidence: `results/m1b85/oom_score_adj_host.json`, `oom_score_adj_bwrap.json`, `oom_score_adj_cap.json`.

## Delegated cgroup v2 memory control

`scripts/probe_cgroup_memory.py` used only a disposable child of the delegated AaaS scope `/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/aaas` (controllers `cpu memory pids`). Results are in `results/m1b85/cgroup_memory.json`.

- `memory.min`, `memory.low`, `memory.high`, `memory.max`, `memory.oom.group`, and `memory.reclaim` were all writable by the delegated user.
- `memory.high=32M` with a 96 MiB generator produced `high` throttling events and **zero** `oom_kill` events.
- `memory.max=48M` with a 160 MiB generator produced a kernel `oom_kill` confined to the disposable cgroup; this is explicitly not LMKD selection.
- `memory.reclaim` returned `EAGAIN` (11) rather than performing unbounded reclaim.
- The probe cgroup was empty and removed on exit.

Pressure remained cgroup-local. `systemd-oomd` was inactive and no host-wide pressure was generated.

## LMKD victim selection under bounded pressure

`scripts/probe_lmkd_selection.py` starts an isolated second LMKD (source-built binary) with a private control socket and the test-only shim `experiments/m1b85/lmkd_test_props.c`, registers three disposable targets at distinct Android-style priorities, and generates pressure only inside a disposable child cgroup (`memory.high=8M`, `memory.max=128M`, no swap). The shim enables `ro.config.low_ram`, disables per-app memcg, enables LMKD debug logging, and lowers `ro.lmk.psi_complete_stall_ms` to 20 ms. Real LMKD selection code, socket protocol, kill syscall, reaper, and notification path run unchanged; the threshold is adapted so a bounded cgroup stall reaches the decision point.

Two fresh LMKD instances produced two independent results (`results/m1b85/lmkd_selection.json`):

| Round | Requested priorities (cached/service/visible) | Killed | Kernel OOM |
| --- | --- | --- | --- |
| 1 | 900 / 500 / 100 | 900 (`cached`) | `oom_kill=0`, `oom_group_kill=0` |
| 2 | 300 / 200 / 100 | 300 (`background`) | `oom_kill=0`, `oom_group_kill=0` |

The `LMK_PROCKILL` notification matched the expected highest-priority PID each time; the other two targets stayed alive. Each daemon had effective `CAP_SYS_RESOURCE` (`0000000001000000`), and both were stopped and their cgroups removed. No `lmkd` process was left running.

This demonstrates ordering and containment, not production pressure fidelity: the stall threshold is test-only, per-app memcg is disabled, and the pressure is cgroup-local rather than device-wide.

## Regression and budget

- `python3 -m unittest discover -s tests`: **89 tests passed** (77 inherited + 12 new M1B.8.5 tests).
- `make -C experiments/m1a test`: all wire v1/v2, synchronization, and stress tests passed.
- Workspace check: 17.36 GiB used, 328.07 GiB free; 80 GiB ceiling and 20 GiB reserve intact.
- Both live runs reached Settings, presented frames, and left no owned processes or socket.

## Acceptance gates

| Gate | Result | Evidence boundary |
| --- | --- | --- |
| B1 preservation | PASS | Inherited file and overlay hashes match; no inherited binary overwritten. |
| B2 reproducible build | PASS | Two builds produced SHA-256 `a36135b6…f291ce`. |
| B3 provenance | PASS | Pinned commits and exact patch diffs verified before build. |
| B4 ABI | PASS | ELF/PIE, build ID, and all dependencies resolved by `linker64`. |
| B5 source LMKD live | PASS | `--use-source-lmkd` reached Settings and logged the source fallback. |
| B6 default LMKD unchanged | PASS | Default run used the diagnostic overlay and regressed cleanly. |
| B7 oom_score_adj characterization | PASS | Positive writes succeed; non-positive writes fail with `EACCES` in all rootless cases. |
| B8 Android negative/foreground parity | FAIL (blocked) | Requires initial-user-namespace `CAP_SYS_RESOURCE`; not achievable rootless here. |
| B9 delegated cgroup control | PASS | All required memory files writable; bounded high/max tests confined and cleaned up. |
| B10 pressure containment | PASS | `memory.high` produced no OOM kill; only disposable cgroups were used. |
| B11 victim selection | PASS | Highest registered priority killed first in two independent rounds; no kernel OOM. |
| B12 Settings regression | PASS | Both live runs presented Settings frames with zero rejections. |
| B13 automated regressions | PASS | 89 Python tests and all M1A tests passed. |
| B14 workspace budget | PASS | 17.36 GiB used, well below the 80 GiB ceiling with the reserve intact. |
| B15 device-wide pressure fidelity | PARTIAL | Pressure is cgroup-local and one stall threshold is test-only. |
| B16 production security / hardware zero-copy | NOT TESTED | This remains a diagnostic CPU-copy runtime. |

## Remaining blockers

1. Negative and zero Android priorities cannot be written rootlessly because the kernel capability check is bound to `init_user_ns`.
2. LMKD cannot run its production PSI/BPF memevents path without the Android BPF loader; vmstats fallback is verified, memevents is not.
3. Victim selection was proven with bounded cgroup pressure and a test-only complete-stall threshold, not with device-wide pressure.
4. No claim is made about production security isolation or hardware zero-copy rendering.

## Reproduction commands

```sh
# Rebuild and verify pinned sources; writes a receipt.
python3 scripts/build_lmkd.py --output /run/media/mrkus/Homework/aaas-workspace/tmp/m1b85_lmkd_source_built \
  --receipt results/m1b85/lmkd_build_receipt.json

# Rootless OOM permission matrix (host, then inside bubblewrap).
python3 scripts/probe_oom_score_adj.py --output results/m1b85/oom_score_adj_host.json

# Delegated cgroup v2 bounded-pressure probe.
python3 scripts/probe_cgroup_memory.py --output results/m1b85/cgroup_memory.json

# Isolated real-LMKD victim-selection probe (refuses if a session is running).
python3 scripts/probe_lmkd_selection.py

# Live sessions.
python3 scripts/run_aaas.py
python3 scripts/run_aaas.py --use-source-lmkd
```
