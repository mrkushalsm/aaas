# M3 entry — ARM64 Native Bridge feasibility

**Status: READY — not implemented.** Canonical scope is defined by [Plan A](../roadmap.md). This document prepares the entry gate only.

## Objective and first experiment

Execute a deterministic ARM64 shared-library function inside the existing
x86_64 Android runtime through Android Native Bridge, then verify calls across
a Java/JNI boundary. The first experiment should use a minimal ARM64 `.so` and
an ARM64-only diagnostic APK with no x86_64 native-library fallback. A
successful loader message is insufficient; the test must execute a known
function and validate its exact result from Java.

## Entry prerequisites

- The Android 16 x86_64 runtime boots and runs installed APKs in the shared
  AaaS session.
- ART, Zygote, framework services and JNI-backed runtime components operate
  for existing x86_64 applications.
- The accepted M2 KWin two-window path is available for observing the
  diagnostic app in AaaS.
- `run_aaas.py` supports session-local APK/framework overlays; runtime logs,
  tombstones and binary provenance are retained per session.
- Android base image replacement is unnecessary for initial feasibility work.

These prerequisites are supported by existing M1 runtime evidence, current M2
acceptance, and the session overlay/provenance mechanism. ARM64 execution itself
has not been tested here.

## Candidate evaluation

At M3 start, inspect actual local source/release availability, Android 16
Native Bridge integration requirements, ABI coverage, maintenance state, and
license compatibility for Digitalis, Teto, and other viable implementations.
Do not assume any candidate is compatible from documentation or a successful
load alone. Record pinned revisions, build inputs, licensing, and any Android
image/API changes before selecting a candidate. Prefer isolated session
overlays; keep translation separate from graphics changes and remain rootless.

## Acceptance sequence

1. Detect and load the ARM64 `.so` through Android Native Bridge.
2. Execute deterministic exported functions and verify exact arguments/results.
3. Call ARM64 code through JNI; verify Java arguments and returned values.
4. Test supported callbacks plus basic JNI object/string interactions.
5. Run an ARM64-only diagnostic APK with no x86_64 native fallback.
6. Record app/runtime health, crashes, translator and image provenance, ABI
   limitations, and basic execution cost after functional correctness passes.

M3 can start independently of M5 performance and M6 compositor portability.
No ARM64 translator or translated application is claimed to work by this
readiness decision.
