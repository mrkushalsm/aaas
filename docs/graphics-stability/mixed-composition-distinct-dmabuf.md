# Mixed-composition distinct DMA-BUF integration

Status: **OPEN — real Android mixed composition and staged Wayland presentation verified; exact Composer-output-to-Wayland buffer lifetime is blocked**

Evidence date: 2026-11-02

This is a separate post-M1E workstream. It does not change the closed M1E,
Bluetooth runtime-health, or SwiftShader v4 decisions.

## Scope and composition contract

The test implementation exercises a constrained Android Composer3 mixed path:
SurfaceFlinger supplies a real client target, the test Composer advertises a
supported topmost Android layer as DEVICE, and the Composer blends that layer
over the client target into a distinct SurfaceFlinger output allocation. The
test accepts only linear RGBA/BGRA8888 buffers, supported blend and alpha
settings, no transform, integral one-to-one crop/frame geometry, and no
unsupported display color operations. Other layer/configuration requests are
not proof of arbitrary mixed composition and remain unsupported by this test
path.

Backing allocation identity is compared using `fstat(st_dev, st_ino)` on the
DMA-BUF descriptors, rather than comparing descriptor integers. Component
tests also verify that duplicated descriptors identify the same backing while
independent allocations do not.

## What passed

The real Android pipeline used SurfaceFlinger client targets and a distinct
Composer output buffer. The Composer's independent visible-pixel oracle
matched the client target plus the selected Android layer. For example, in
enhanced session `m1b84_session_5eqxw9tb`, 168 exact mixed-frame pixel checks
were recorded on virtual display 101. Display 100 used the existing alias
path. A later enhanced session, `m1b84_session_hv2klsh6`, recorded 35 further
exact pixel checks on display 101 while both Settings and Contacts were
running. These sessions stopped cleanly.

The current session's presenter summaries were:

| Presenter | Imports | Submissions | Releases | Rejected | Outstanding |
|---|---:|---:|---:|---:|---:|
| Settings | 86 | 86 | 86 | 0 | 0 |
| Contacts | 58 | 58 | 58 | 0 | 0 |

The enhanced session used source-LMKD with delegated cgroup policy. The runner
removed the cgroup at shutdown. Neither the current session's logcat nor the
earlier enhanced session recorded a fatal Android exception, fatal signal, or
ANR. The Contacts hamburger menu, Settings destination, and Create label
dialog were visibly exercised in the earlier enhanced run.

In the staging path, the presenter copies the Composer output into its own
Wayland-importable GBM buffer. The presenter imports and releases that staging
buffer correctly. The result proves real Android pixels survive the
Composer-to-staging-to-Wayland path, but it does **not** prove that Wayland
imports the exact Composer output allocation.

## Exact-output experiment and lifetime barrier

The direct-import diagnostic variant disabled the staging-copy completion
capability and passed the Composer output DMA-BUF to Wayland. The presenter log
recorded matching `st_dev:st_ino` identities for transport receipt and Wayland
import (`staged_copy:false`), and the frame was committed. It did not receive a
compositor release while the synchronous Composer `presentDisplay` call was
waiting for transport completion. The presenter could not submit a replacement
buffer until that call returned. This creates a cycle: SurfaceFlinger awaits
Composer's present result before it can advance/recycle the output buffer,
while Composer awaits Wayland release before returning the present result.
That run is not acceptance; one presenter exited without a rendered frame and
the session's lifecycle result is preserved in its raw record.

Returning a signaled or absent present fence early is not a valid repair. It
would allow SurfaceFlinger to reuse the output allocation while Wayland may
still read it. Keeping the buffer reference in the presenter does not prevent
SurfaceFlinger from writing the same allocation again.

The Wayland explicit-sync protocol provides a compositor-signaled release
timeline point, but the current Android Composer contract needs a native fence
that can be returned from `presentDisplay` before that future release occurs.
The tested SwiftShader opaque-fd semaphore implementation uses a process-shared
memfd semaphore and is not a Linux `sync_file`. The host has no `/dev/sw_sync`.
Exporting a sync file from a newly-created unsignaled DRM sync object returned
`EINVAL`. A host Vulkan probe on the current NVIDIA DRM device advertised
opaque-fd semaphores and sync-fd fences, but failed to import the DRM syncobj
fd (`VK_ERROR_INITIALIZATION_FAILED`), so that route cannot provide the
required future release fence here. These results are probes of the current
host/runtime stack, not a claim that every Linux GPU driver lacks an interop
mechanism.

The exact-output integration remains open until a supported asynchronous
fence/ownership bridge can return a genuine pending native fence to Android
without early reuse, unbounded retention, privileged host changes, or a
compositor-specific product dependency. The safe staging path remains the
verified current behavior.

## Regression and provenance

DMA-BUF identity tracing is opt-in: `run_aaas.py` enables it only when a
hash-checked diagnostic Composer overlay is selected. Normal sessions avoid
the per-frame `fstat` and identity log events. Session
`m1b84_session_rwepqje9` exercised that opt-in after the presenter rebuild;
both presenters emitted the expected identity pairs and finished with balanced
ownership.

The mixed pixel regression covers same-backing and distinct-backing identity,
premultiplied blending, distinct source/destination strides, padded rows,
visible pixels, untouched destination padding, odd width/height including the
last row and column, overflow rejection, bounds rejection, and an oracle
negative control that detects a changed pixel. All three isolated Composer
tests pass. A normal non-diagnostic two-output Composer also builds.

Current diagnostic Composer SHA-256:

`992b5755694802fea00a4c057114ca4226f6c7dcf35c7c5730b8075abf250493`

Normal non-diagnostic two-output Composer build SHA-256:

`14f42f33d0d9b4081a6950b9c545cf8b7ebafeebc0846ba2d5696467e61f236e`

The historical production SwiftShader overlay remains
`1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`; the
corrected no-tracing candidate remains
`e42a0bd8dfe3e0eea6c3d6753f9f9fa254d348366847241ca3c7e4b9ac9affee`.

At the 2026-11-02 checkpoint, 232 Python tests, M1A tests, presenter tests,
input adapter build, isolated Composer tests, display broker build, and
workspace guard passed. That checkpoint's incomplete resize status is
superseded by the scoped staged-path acceptance below. See
**`acceptance.json`** (maintainer archive only)
for commands, session IDs, evidence paths, hashes, and gate-by-gate status.

## Supported and unsupported claims

- **Verified:** constrained real Android client-target plus one DEVICE layer
  copied/composed into a distinct Composer output allocation, then copied into
  a separate Wayland staging allocation and presented.
- **Verified:** existing alias output path remains operational.
- **Not verified:** Wayland importing and presenting the exact Composer output
  allocation with a correct Android present/release fence.
- **Not claimed:** arbitrary multi-layer mixed hardware composition, format
  conversion, nonlinear modifiers, transformed/scaled layers, color transforms,
  protected content, or cross-GPU operation.

This broad workstream remains **OPEN/BLOCKED** because exact-output
presentation remains unresolved. The staged resize and dual-display gates
were later completed as described below.

## Scoped staged-path result (2026-11-03)

The constrained staging path has since completed a separate live acceptance:
two concurrent mixed displays, mixed/alias coexistence in both directions,
resize and resize-back, exact visible-pixel checks, and buffer/fence release
ordering passed in default and enhanced sessions. See
[`staged-mixed-composition.md`](staged-mixed-composition.md) and its
**acceptance record** (maintainer archive only).
This result does not close this broader record: exact Composer-output
allocation presentation to Wayland remains **OPEN/BLOCKED**.
