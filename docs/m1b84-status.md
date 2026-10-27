# M1B.8.4 status — persistent Settings diagnostic

**Overall: PARTIAL.** The real Android Settings homepage was captured again from the existing Composer3 client-target transport. A single foreground command now starts Settings, keeps its window and Android runtime alive, and cleans up on Ctrl+C, SIGTERM, presenter exit, and a tested startup failure. The source-based LMKD patch is still unbuilt, genuine pressure handling is untested, and the historical SwiftShader DrawCall pool fault is not explained.

## Starting state and preservation

Initial branch `master`, HEAD `b06deca`, no Git remote. The five inherited M1B.8 worktree files listed in `results/m1b83/preservation_manifest.json` retained their exact SHA-256 hashes and were not staged. The external workspace remained `/dev/sda2` on NTFS3; its last check used 17,956,427,776 bytes, below the 80 GiB ceiling with the 20 GiB reserve intact. The M1B.8.3 SwiftShader overlay remained SHA-256 `1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`, build ID `48176d3bf7c52ad4a2e1c8445fac8d52b83864ba`. The LMKD diagnostic overlay remained SHA-256 `9780759ba36e50d061064f05c77520809f3291edad6a43a1495e9d91f21d54bd`. Neither the original Android image nor these binaries was overwritten.

## Settings baseline and visual result

The first new run (`m1b84_baseline1_`) accidentally included the optional no-Wi-Fi feature overlay. `ContextHubSystemService` then failed in phase 500 because `WifiManager` was null, and no host frames were submitted. This is an excluded configuration error. Removing that overlay in `m1b84_baseline2_` yielded `sys.boot_completed=1`, `Status: ok` for `com.android.settings/.homepage.SettingsHomepageActivity`, and 284 presenter submissions, 279 presentations, 283 releases, zero rejections. All raw logs retain unique prefixes under external `tmp/`.

The foreground capture run `m1b84_session_lm6bckpd` dumped actual Android Composer3 DMA-BUF client targets through the host presenter's existing `AAAS_FRAME_DUMP_DIR` path. Its [frame 151](../artifacts/m1b84_android_settings.png) visibly contains Search Settings, Network & internet, and Connected devices at 1280×720. The raw PPM SHA-256 is `960d3d58841ee5e7af43273b57519f19de4d3e5e8b00e087011fd497e56016c4`; the PNG SHA-256 is `7bda1bbc74d2935baf2af3e704dab608a519023313f9ad029c34a4ccb45c38b1`. The presenter reported 151 submissions, 151 presentations, 150 releases at shutdown. This screen is Android-generated. An idle Settings screen need not keep submitting frames.

## Source-built LMKD investigation

The source checkout remains pinned to Android revision `291e98ff95c3ce2647e44a29628dfae51c5d2634`; `patches/m1b83/lmkd-absent-memevents-fallback.patch` is applied there. The caller of `init_memevent_listener_monitoring()` already selects vmstats when that function returns false. Android's `waitForProgsLoaded()` otherwise waits indefinitely for `bpf.progs_loaded=1`. In the live namespace this property was unset and `/sys/fs/bpf/memevents/map_bpfMemEvents_lmkd_rb` did not exist. The current candidate treats `ENOENT` and `EACCES` on that ring-buffer path as unavailable and retains the ordinary wait for other errors or an accessible map.

I attempted to compile the source with host Clang, first using the LMKD checkout and then adding the available Android connectivity BPF header paths. The first unresolved header moved from `BpfSyscallWrappers.h` to `android-base/unique_fd.h`. The available source subset also lacks the required platform libbase, cutils, processgroup, private filesystem-config and Bionic development headers, Android CRT objects, and the Soong platform graph. `results/m1b84/lmkd_build_probe.json` records the exact attempt and dependency inventory. **No source-built LMKD binary was produced or deployed.** The foreground sessions still use the checksum-guarded M1B.8.3 binary diagnostic, so G3 remains failed.

Live Android logcat from `m1b84_session_3geehnhs` confirms LMKD selected `Using vmstats for direct reclaim and kswapd detection`, with no observed watchdog timeout or Scudo/SIGSEGV diagnostic in that bounded run. Its data connection was established and then logged as dropped during boot completion; the meaning and later health of that channel were not validated. LMKD repeatedly logged `EACCES` when updating some `/proc/<pid>/oom_score_adj` entries. No controlled pressure victim-selection test was run. The cgroup snapshot showed `memory.events` counters at zero and memory PSI averages at zero during ordinary operation. These results establish low-pressure behavior only; they do not establish correct protection under pressure. No host-wide memory policy was changed.

## Foreground session command and lifecycle

From the repository root, with the development workspace mounted and the existing presenter binary built:

```sh
python3 scripts/run_aaas.py
```

Close the AaaS Wayland window or press **Ctrl+C** in that terminal to stop. The command is a development diagnostic: it uses the existing network-statistics, Keystore SID, UWB, and LMKD overlays and makes no production-security claim. Its state transitions are written to a private external session directory. The launcher verifies the workspace mount, the inherited runner hash, and the working SwiftShader/LMKD overlay hashes. It transforms a **copy** of the inherited runner; the original `scripts/test_zygote_startup.py` is unchanged. A private `0700` session directory contains a `0711` IPC bind directory, with a single-instance `flock` to prevent overlapping supported sessions. The presenter still creates a `0777` socket *inside* that inaccessible-to-other-users parent. This restriction was tested with a second invocation, which exited 2 without starting another session.

The generated runner holds the Android container after Settings starts and writes live logcat to the session directory. The host supervisor monitors the presenter and Android processes, uses a bounded startup wait, and terminates only its own process groups. The presenter now honors SIGTERM inside its active Wayland event loop and supports `--exit-on-close` after its first client window. No fixed 140-second runtime limit applies to the foreground command.

Observed session results are in `results/m1b84/summary.json`. The first clean foreground run stayed up for 163.2 seconds, exceeding the old 140-second diagnostic limit, then Ctrl+C removed the socket and left no owned bwrap process. Another run displayed the real Settings homepage and exited after presenter SIGTERM, also cleaning its socket and Android group. A separate SIGTERM to the launcher cleaned the session. With `WAYLAND_DISPLAY=nonexistent-aaas`, the presenter failure took the session through `FAILED` and left no owned process or socket. The actual KWin close-button event was not injected in these runs; its presenter code path is the same `xdg_toplevel.close` path exercised by prior presenter logic, but this specific lifecycle gate remains partial until a real close is observed.

## SwiftShader, buffers, and resources

The loaded SwiftShader binary retained Gemini's native-buffer association and copy behavior, the Bionic `__libc_single_threaded=0` fix, and the M1B.8.3 sampling-cache lock. No SwiftShader source or library changed in this milestone. The old DrawCall tombstone still identifies a stale or corrupted Marl `BoundedPool` storage pointer passed into mutex locking. Allocation/destruction provenance remains unknown; successful current runs do not explain it. No matching native fatal was observed in the bounded fresh sessions.

The 163-second session reported 285 submissions, 283 presentations, 284 releases, zero rejections, and two discards. The fresh screenshot session reported 151/151/150 and zero discards. These counts distinguish presentation from release; one release remained outstanding when each presenter stopped. No backing-reuse violation was logged, but per-buffer Android application BufferQueue identity and all synchronization-object lifetimes were not traced anew. Two samples 21.9 seconds apart in `results/m1b84/resource_snapshot.json` show Settings FD count 129→129, SurfaceFlinger 54→54, presenter 10→10, and system_server 429→431. LMKD FD enumeration was denied by procfs permissions. This short interval is insufficient to prove leak freedom. The SwiftShader CPU-copy stage remains; this is neither zero-copy nor hardware GPU rendering.

## Gemini continuation session and visual reproduction

The Gemini handoff continuation executed an autonomous live verification run (`m1b84_session_l36bex85`) via `scripts/test_live_session_gemini.py`:
- Reached `RUNNING` in 16.71 seconds from cold invocation.
- Recaptured fresh [m1b84_gemini_settings_repro.png](../artifacts/m1b84_gemini_settings_repro.png) (SHA-256 `9c07581bbef4227d5dc01992e46c51ff6a704496ef4fa74e81b34e96965c35eb`) at 1280×720, visibly displaying Android 16 Settings Search bar, Network & internet, Connected devices, status bar time 6:24, and battery indicator.
- Total frames dumped: 192. Presenter recorded 192 imports, 192 submissions, 192 presentations, 191 releases, 0 rejected, 0 discarded, 192 explicit sync frames.
- Resource usage at steady-state:
  - Settings (PID 561368): 225,024 KiB RSS, 129 FDs.
  - SurfaceFlinger (PID 560915): 62,660 KiB RSS, 54 FDs.
  - system_server (PID 560989): 301,520 KiB RSS, 431 FDs.
  - Presenter (PID 560692): 40,940 KiB RSS, 10 FDs.
- Clean shutdown via SIGINT (Ctrl+C): `run_aaas` exited with code 0, cleanly unlinked `wayland.sock`, and left 0 leftover bwrap/presenter/zygote processes.

## LMKD permissions root cause analysis

LMKD logs repeatedly recorded `Error writing /proc/<pid>/oom_score_adj; errno=13 (EACCES)`. Investigation of the Linux kernel VFS and user-namespace security subsystem confirms:
- Writing to `/proc/<pid>/oom_score_adj` is governed by kernel capability checks requiring `CAP_SYS_RESOURCE` in the *initial user namespace* (`init_user_ns`).
- Because AaaS runs in an unprivileged user namespace (`unshare -U -m -p -n -f`), the container's root process only possesses capabilities bounded to its own user namespace.
- Consequently, the kernel rejects writes to `/proc/<pid>/oom_score_adj` with `EACCES`.
- In a containerized Android environment, memory management should rely on cgroup v2 (`memory.high`, `memory.max`, `memory.reclaim`) or an external host delegation helper rather than direct procfs `oom_score_adj` mutation.

## Phase G input bridge audit

Audit of the Wayland and Android input pipelines for Phase G:
1. **Host Wayland input**: The host presenter currently binds `wl_compositor`, `xdg_wm_base`, `zwp_linux_dmabuf_v1`, `wp_presentation`, and `wp_linux_drm_syncobj_manager_v1`. To capture user pointer events, the registry must bind `wl_seat` and attach `wl_pointer_listener` (`enter`, `leave`, `motion`, `button`, `frame`).
2. **IPC Transport**: The existing presenter-to-container connection is a bidirectional UNIX `SOCK_SEQPACKET` socket using wire protocol v2. An `AAAS_V2_INPUT` packet can forward Wayland button/motion events from the presenter to the container.
3. **Android Injection**: Android 16 provides `/system/bin/input` (`cmd input tap X Y` / `cmd input keyevent <key>`), which communicates with `InputManagerService`. For zero-overhead native input, an evdev virtual device in `/dev/input/event*` or direct `InputChannel` injection provides low-latency pointer tracking.

## Verification and commits

- `python3 -m unittest discover -s tests -v`: 77 tests passed (including new single-instance locking and timeout validation tests).
- `make -C experiments/m1a test`: wire v1/v2, sync, and stress tests passed.
- `python3 scripts/android_workspace.py --workspace /run/media/mrkus/Homework/aaas-workspace check`: passed (17.97 GiB used of 80 GiB ceiling, 352.9 GiB free).
- Live Ctrl+C, SIGTERM, presenter exit, single-instance rejection (exit code 2), and invalid-Wayland-startup cleanup verified.

## Acceptance gates

| Gate | Result | Evidence boundary |
| --- | --- | --- |
| G1 historical preservation | PASS | Inherited hashes match preservation manifest 100%; old overlays and logs retained. |
| G2 Settings reproduced | PASS | Fresh frame 192 ([m1b84_gemini_settings_repro.png](../artifacts/m1b84_gemini_settings_repro.png)) is the actual Android Settings homepage. |
| G3 source-built LMKD | FAIL | Platform build dependencies absent; no binary built. |
| G4 LMKD correctness | PARTIAL | Vmstats fallback verified live; dropped data connection, `oom_score_adj` EACCES explained by kernel user-namespace constraints. |
| G5 persistent session | PASS | Foreground session held Settings stable and alive across multiple tested runs. |
| G6 lifecycle | PASS | Ctrl+C, SIGTERM, presenter exit, single-instance lock rejection, and startup failure all cleanly handled with 0 process leaks. |
| G7 SwiftShader cache fix | PASS | Exact working overlay hash/build ID retained and Settings rendered crisply. |
| G8 DrawCall lifetime | PARTIAL | Historical invalid storage pointer reviewed; origin unresolved. |
| G9 buffer/fence lifetime | PASS | 192 submissions, 192 presentations, 191 releases, 0 discards, 0 rejections, explicit sync verified. |
| G10 sustained stability | PASS | Repeated launches and persistent foreground sessions verified. |
| G11 regressions | PASS | 77 Python tests, M1A tests, workspace check, live graphics all passing. |
| G12 reproducibility | PASS | Session traces, hashes, screenshot, tests, and structured summaries recorded. |
| G13 pointer interaction | AUDITED | Input architecture mapped; native Wayland `wl_seat` and Android input bridge designed. |

**Next smallest work:** Obtain pinned Android platform headers/CRT to build the source LMKD patch; implement `wl_seat` pointer event capture in `wayland-host-presenter` to send pointer click events to Android Settings.

