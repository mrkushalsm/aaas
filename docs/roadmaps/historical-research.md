# Plan C — Historical Research and Technical Workstreams

This reference preserves the original experimental sequence and meaning. It does not define canonical product numbering; see [Plan A](../roadmap.md).

## Historical M0 — Reproducible research lab

Freeze revisions, host capabilities, licenses, benchmarks, and baseline builds. Original exit: reproducible source manifest, hardware report, dependency audit, build logs, and baseline tests.

## Historical M1 — Sailfish feasibility experiments

Investigate Lipstick simplecompositor and Qt HWC plugin. Original exit: actual build/run evidence and a reuse decision. The missing compatible Sailfish Qt package/toolchain remains part of the research record.

## Historical M2 — Virtual Composer3 MVP

Explore AOSP drm_hwcomposer/Goldfish patterns and full-client-target Android to host transport. Original exit: resizable Android Settings and correct long-run buffer synchronization, with zero-copy ambitions. The implemented Composer3 architecture superseded candidate paths without erasing their results.

## Historical M3 — Zero-copy, synchronization, and fallbacks

Explore allocation identity, subsurfaces, modifiers, GPU conversion, and CPU fallback. Original exit: verified zero-copy where supported and robust fallback. Staged composition does not satisfy the historical zero-copy goal; exact-output zero-copy remains optional and deferred.

## Historical M4 — ARM64 compatibility and isolation

Investigate Digitalis, Teto, JNI/NEON, and container/namespace tradeoffs. Original exit: ARM64-only JNI execution and evidence-based isolation choices. This maps mainly to canonical M3.

## Historical M5 — Desktop integration and lifecycle

Investigate runtime states, launchers, PipeWire, portals, notifications, and input. Original exit: manageable desktop applications with resource measurements. This maps mainly to canonical M2/M4.

## Historical M6 — Comparative evaluation and architecture freeze

Compare AaaS with Waydroid and Droidloom; evaluate optional Lipstick backend. Original exit: benchmark data, compatibility matrix, and v1 architecture decisions. This maps to canonical M0/M5/M6.

Historical objectives are not retroactively rewritten to match later results. The Sailfish build limitation remains recorded; Composer3 supersedes some early candidate approaches; historical M2 does not override canonical M2; and historical M3 zero-copy work does not override canonical M3 ARM64 compatibility.
