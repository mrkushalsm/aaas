# M1B prerequisite audit and stop decision (2026-10-25)

**Decision: M1B blocked before Android integration.** No M1A.1 implementation, test suite, or result directory exists in this checkout. M1A's only producer uses a CPU-mapped GBM BO. Its wire format has one DMA-BUF FD, no acquire or release fence FD, no timeline point, and no syncobj protocol binding. It treats `wl_buffer.release` as permission for the CPU producer to reuse a BO; it does not establish GPU-completion or Android release-fence semantics. The recorded live test was 300 synthetic frames, not 10,000 Android frames. Do not adapt Composer3 or claim SurfaceFlinger integration until those prerequisites have execution evidence.

## Audit evidence

The research report, all existing architecture/M0/M0.1/M1 documents, manifest, source code, tests, and retained M1A logs were reviewed. No M1A.1 files appeared in the repository inventory or Git history. `results/m1b/host-preflight.log` records the current host. It is EndeavourOS/Linux 7.2.9, KDE/KWin Wayland, Intel i915 and NVIDIA proprietary GPU, 12 logical CPUs, 15 GiB installed RAM (about 5.9 GiB available at capture), and 17 GiB free filesystem space. Wayland advertises linux-dmabuf v5 and DRM syncobj manager v1, but advertising a global does not prove end-to-end fence handling. Render nodes are present; Binder device nodes are absent. No AOSP source checkout was found under the existing project directory.

`python3 scripts/android_repo_lock.py inspect` found 1,015 effective Digitalis project paths, still unresolved to immutable revisions. `python3 scripts/android_repo_lock.py validate` exited 1 because `manifests/android16-locked.xml` does not exist. The pinned Digitalis manifest revision is `c04ff674ee0926fe79e690b20493c7b2f0e380b4`; this pins the manifest file, not its moving project graph. The current [AOSP workstation requirements](https://source.android.com/docs/setup/start) state at least 400 GB free for checkout/build and 64 GB RAM. A narrower build could differ, but no compatible minimal Android artifact or reproducible product configuration has been verified here. No large fetch or build was started on the 17 GiB free filesystem.

## M1A prerequisite repair and retest

Two local correctness defects were repaired in commit `4d2f812`:

- A compositor configure larger than the prototype's size cap could send a clamped producer size while retaining the unclamped validation size, rejecting every resulting frame. The presenter now stores the bounded target size.
- The presenter now rejects a second in-flight frame with the same generation and buffer ID; the wire parser also rejects unknown nonzero flags.

`make -C experiments/m1a all test` passed. The fresh five-second KWin execution in `results/m1b/m1a-live.log` exited 0 with 289 synthetic DMA-BUF imports, 287 `wl_buffer.release` events, 287 presentation feedback events, and one discarded feedback event. The trace checker found no reuse before a matching release in this CPU-producer run. Killing the producer after one second caused a logged disconnect and presenter exit 0. Eight repository unit tests passed. These tests do **not** validate a GPU writer, explicit synchronization, Android-originated buffers, user-driven rapid resize, compositor disconnect, or release-fence export. The duplicate-ID guard has no hostile-producer integration test yet.

## Exact stop boundary

The missing M1A.1 GPU synchronization contract is the first correctness blocker: there is no tested transfer from a producer acquire fence to the Wayland compositor, and no tested compositor completion fence suitable for return to Android. `wl_buffer.release` and `wp_presentation.presented` are not interchangeable with a release `sync_file`. Consequently, implementing an Android Composer3 service against the current wire ABI would risk premature Android buffer reuse. The source graph and host capacity independently block a reproducible local AOSP 16 image. No Composer3 source was copied or modified, no Android service was registered, and no Android application was run.

## Next gate

Build M1A.1 as an isolated host experiment: a GPU writer that exports a real acquire `sync_file`; negotiated Wayland `linux-drm-syncobj-v1` timeline points; verified release-fence export; buffer identity and FD accounting; stale-generation, resize, close, and compositor-disconnect tests; and a sustained multi-buffer trace. Only after that passes should the Android graph be locked and a compatible Composer3 upstream implementation be selected on a sufficiently provisioned build host or from a verified reproducible artifact. Preserve the existing M1A synthetic path as a separate regression test.
