# AaaS product roadmap (canonical Plan A)

**Authority:** This is the canonical AaaS product roadmap. Its Plan A milestones govern future development. Plan B and Plan C are retained as supporting references and must not independently redefine milestone numbering or completion criteria.

AaaS runs unmodified Android applications as independently manageable native Linux desktop windows, with ARM64 application compatibility, host integration, on-demand operation, and efficient resource use.

## M0 — Architecture and feasibility

Audit Waydroid, Sailfish, AOSP, and translator source paths; determine what can be reused unchanged and what needs adapters. Expected outcomes are an architecture specification, source/dependency and licensing audits, reuse/adaptation decisions, feasibility analysis, risks, decision records, and a reproducibility baseline. Existing progress does not automatically close M0; formal criteria and remaining research limits must be assessed. Noncritical historical gaps do not block a working runtime unless they affect correctness or reproducibility.

## M1 — Minimal functional Android runtime

Boot a reproducible x86_64 Android container, install and run a real x86_64 APK, and understand the essential service set. Acceptance covers Android userspace, Binder, core services, ART, Zygote, sufficient SurfaceFlinger/Composer operation, APK installation, application launch, service dependencies, and reproducible startup/shutdown. Reuse the existing runtime evidence; do not rebuild a working image just to repeat feasibility work.

## M2 — Independent desktop windows

Run two Android applications as separately manageable Linux desktop windows. Each has an independent native Wayland toplevel; resize, focus, keyboard and pointer input work; closing one does not terminate the other; and the runtime shuts down cleanly. The supported acceptance compositor is KWin on Linux Wayland. M2 does not require universal compositor support, sustained 60 FPS, zero-copy, ARM64 translation, audio, portals, notifications, or packaging.

## M3 — ARM64 Native Bridge feasibility

Load and execute a small ARM64 shared library through Android Native Bridge on x86_64, including a Java/JNI boundary test. Evaluate viable translators and Android integration, execute deterministic ARM64 functions, verify JNI arguments/returns, investigate callbacks and common JNI operations, and record ABI/translation limits and ARM64-only APK feasibility. A load log alone is not acceptance: translated ARM64 execution is required. **Status: PASS/CLOSED** for the bounded Android 16/Digitalis feasibility proof; see the [M3 acceptance record](../results/m3/acceptance.json) and [implementation details](milestones/m3-arm64-native-bridge.md). This does not claim universal ARM64 application compatibility.

## M4 — Native desktop integration

Implement on-demand lifecycle control, audio, shared-file selection, desktop launchers, and clipboard integration. Expected outcomes include explicit stopped/warm/active behavior, efficient idle operation, host audio, file selection/shared access, launchers, clipboard, supported notifications, and resource cleanup. Bluetooth hardware remains optional backlog. **Current status: PARTIAL/OPEN.** The 2026-11-08 `PASS/CLOSED` campaign remains preserved as historical acceptance of the established installed configuration. Current relocated-installation acceptance has headless shared-storage, app-context MediaStore, restart-persistence, and dedicated-partition filesystem evidence, but interactive SAF/DocumentsUI and graphical acceptance remain open under the presenter safety pause after the KWin/Mesa incident. This does not attribute the crash to AaaS or permanently remove presentation. See the [M4 acceptance record](../results/m4/acceptance.json), [2026-11-09 storage record](../results/m4/shared-storage-partition-2026-11-09.json), [host graphics incident](incidents/host-graphics-impact-2026-11-09.md), and [implementation status](milestones/m4-native-desktop-integration.md). M5 performance and M6 portability remain separate.

## M5 — Graphics optimization and benchmarks

Measure and investigate buffer sharing, synchronization, copies, power, launch time, frame pacing, rendering overhead, CPU/memory/idle use, cold/warm launch, and GPU/vendor comparisons where feasible. Optimize only from reproducible evidence and preserve synchronization correctness. The current continuous frame-pacing/60 Hz investigation, Composer attribution, presenter staging, historical 326.704 ms stall, and optional exact-output zero-copy remain `PARTIAL/OPEN` or deferred as recorded in their evidence. This roadmap update does not close M5.

## M6 — Distribution and broader compatibility

Package AaaS for Linux desktops; provide installation, upgrade/removal, dependency validation, cross-desktop/compositor/GPU testing, compatibility matrix, release documentation and automated release validation; evaluate optional store/service compatibility. Weston and Sway work is partial where desktop input/resize/lifecycle gates remain open; Hyprland and Mutter are unverified. This roadmap update does not close M6.

## Portable developer runtime foundation (scoped M4.5 tranche; PARTIAL/OPEN)

This is implementation work feeding into M6, not a new canonical product milestone. The shared XDG configuration resolver, `aaas` bootstrap/CLI, host doctor, workspace capability enrollment, Android profile inspection, and local M4 diagnostic bundle/relocation commands are implemented. A local bundle can pass file integrity in a clean installation, but its runtime closure is partial and its security is not approved: the legacy rootfs has unverified modifications and SELinux authorization-success shims, and the host lacks verified Android SELinux enforcement. The current runner also requires a per-installation helper signing flow. Therefore fresh setup still cannot produce a generally runnable/secure installation; normal `aaas verify/start` remains fail-closed. M4's 2026-11-08 closure is retained as historical evidence, while the current canonical M4 status and portable runtime remain `PARTIAL/OPEN`. See [portable runtime documentation](developer-runtime.md) and the [restricted local bundle guide](developer-bundle.md).

The 2026-11-08 reconstruction continuation records the shared-kernel SELinux boundary and classifies the existing profile as `DIAGNOSTIC_LEGACY`. A bounded QPR2 Soong attempt reached bootstrap but stopped at missing registered HIDL/AIDL/XSD module types before compiling graphics artifacts. No new rootfs or Android session was produced; see [runtime integrity evidence](android-runtime-integrity.md) and the [rootless security decision](security/rootless-android-architecture.md).

Later on 2026-11-08, the retained original Android 16 SDK r02 archive was assembled into a fresh, structurally verified `ASSEMBLED_INCOMPLETE` rootfs candidate. The builder and `aaas images build` command preserve source provenance and exclude the diagnostic SELinux shims; they do not activate or provision the candidate. No Android session was started. Portable provisioning remains `PARTIAL/OPEN`, and M4's historical `PASS/CLOSED` status is unchanged. See the [rootfs assembly record](android-rootfs-reconstruction.md) and [transformation map](../manifests/android16-reconstruction-transformations.json).

## Existing work mapped to Plan A

| Existing work | Canonical destination |
|---|---|
| Source, architecture, and feasibility research | M0 |
| Android runtime startup and APK execution | M1 |
| Composer3 desktop display bridge | M2 |
| Two native Android application windows | M2 |
| KWin resize, input, focus, and lifecycle | M2 |
| ARM64 Native Bridge | M3 |
| Desktop lifecycle, audio, portals, and clipboard | M4 |
| Frame pacing and graphics optimization | M5 |
| Exact-output zero-copy | M5 optional/deferred |
| Bluetooth hardware integration | M4 optional/deferred |
| Cross-compositor portability | M6 |
| Packaging and distribution | M6 |

## Roadmap governance

1. Only Plan A defines product milestones M0–M6.
2. Lettered experiments such as M1A, M1B, and M1E are technical subdivisions, not top-level product milestones.
3. Each experiment links to a Plan A milestone or explicitly deferred backlog.
4. Status describes demonstrated evidence. Completing an experiment does not automatically close its parent; a parent does not require optional research to be complete.
5. Deferred work retains its historical status. New milestone names require an explicit update to this roadmap.
6. Acceptance gates must match the product objective, not an unrelated experiment's ambitions.

## Supporting plans

- [Plan B — implementation guidance](roadmaps/implementation-guidance.md)
- [Plan C — historical research](roadmaps/historical-research.md)
- [M2 acceptance record](milestones/m2-independent-desktop-windows.md)
- [M3 Native Bridge implementation and acceptance](milestones/m3-arm64-native-bridge.md)
- [M3 structured acceptance](../results/m3/acceptance.json)
- [M5 frame pacing and latency](graphics-stability/frame-pacing-and-latency.md)
- [M6 compositor portability](graphics-stability/cross-compositor-portability.md)

## Status snapshot

| Canonical milestone | Current status |
|---|---|
| M0 | Incomplete; see [M0 status](m0-status.md). Runtime progress does not close the research/build-lock criteria. |
| M1 | Existing x86_64 Android runtime and APK execution are established. |
| M2 | PASS/CLOSED; see [M2 acceptance](milestones/m2-independent-desktop-windows.md). |
| M3 | PASS/CLOSED for the bounded Android 16 Native Bridge feasibility proof; arbitrary ARM64 app compatibility is not claimed. |
| M4 | PARTIAL/OPEN. The 2026-11-08 integrated campaign and historical M2/M3/M4 evidence remain preserved, but resumed acceptance has not completed all required integrations in the relocated installation. Headless shared-storage and MediaStore restart checks passed on 2026-11-09; interactive SAF and graphical acceptance remain unverified while the KWin/Mesa presenter safety investigation is open. See the [supplemental headless storage evidence](../results/m4/headless-shared-storage-2026-11-09.json), [host graphics incident](incidents/host-graphics-impact-2026-11-09.md), and [historical M4 acceptance](../results/m4/acceptance.json). |
| M5 | PARTIAL/OPEN; graphics performance and historical tail-latency work remain separate. |
| M6 | PARTIAL/OPEN; KWin/Weston/Sway portability is not fully accepted; Hyprland/Mutter unverified. |
