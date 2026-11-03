# Plan B — Implementation Guidance, Not Canonical Milestone Numbering

Plan A in [the canonical product roadmap](../roadmap.md) alone defines M0–M6. These phases guide technical sequencing; a phase may span canonical milestones or support part of one.

## Phase 0 — Research audit and architecture freeze

Verify source findings; select reusable, adaptable, and independent components; document licenses, dependencies, boundaries, and risks. Deliver an architecture specification, decisions, dependency map, and milestone gates.

## Phase 1 — Graphics feasibility proof

Investigate Lipstick, Qt HWC, libhybris, and compatible compositor approaches; evaluate Android-composed frames in a native Wayland surface. Deliver one Android-rendered surface in a native Linux window.

## Phase 2 — Minimal Android runtime

Integrate Android userspace, Binder, ART, Zygote, SurfaceFlinger, and necessary system services. Deliver booted Android services and a launched x86_64 Android application.

## Phase 3 — Independent desktop windows

Integrate Android task/window identity with Wayland xdg_toplevel, input, focus, resize, clipboard, and lifecycle. Deliver two independently manageable Android application windows.

## Phase 4 — ARM64 compatibility

Evaluate Digitalis/Teto and viable alternatives through Android Native Bridge; test JNI-heavy applications, native libraries, and mixed execution. Deliver an unmodified ARM64-only APK running on x86_64 Linux.

## Phase 5 — System integration and optimization

Implement audio, notifications, installation, file access, networking, lifecycle, and graphics optimization. Measure launch time and resource overhead. Deliver a usable alpha and reproducible performance comparisons.

## Phase 6 — Packaging and release

Create distro packages, installation tooling, documentation, CI, compatibility testing, and release processes.
