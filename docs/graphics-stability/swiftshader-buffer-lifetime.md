# SwiftShader buffer lifetime verification

Status: **PASS/CLOSED for bounded current-build ownership verification**

Historical v4 incident: **UNRESOLVED**

Evidence date: 2026-11-02

This is a separate post-M1E stability workstream. It does not change the M1E
closure or the historical incident classification.

## Historical v4 observation

In session `m1b84_session_hqgkycni`, SurfaceFlinger PID 222, TID 262,
`PixelRoutine_00000042` executed an 8-byte load at routine offset `0x125f`.
The effective address was `0x7f31c8ba5000`, the base of AHardwareBuffer
`3560527888403` (960×578, 3840-byte row stride). The mapping was absent at the
fault. The matching external-memory release was recorded on RenderEngine TID
235 approximately 32.5 ms earlier. This is a stale access after unmap at
allocation offset zero. It is distinct from the corrected odd-height 960×557
paired-row bounds defect.

The tombstone and JIT trace are preserved externally and their existing hashes
are recorded in
[`swiftshader_v4_ownership_narrowing_20261102.json`](../../results/graphics-stability/swiftshader_v4_ownership_narrowing_20261102.json).
The available v4 data does not identify the VkDeviceMemory, image/view,
framebuffer, queue submission, renderer job, or retirement fence for that
allocation. It therefore cannot establish whether the caller retired an
in-flight resource or a worker outlived a valid Vulkan lifetime boundary.
**No root cause or fix is claimed for that historical process.**

## Ownership model audited

The pinned source is
`cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5`, from the pre-existing external
checkout. That checkout contains unrelated local modifications and was not
reset or overwritten.

The relevant ownership path is:

1. `AHardwareBufferExternalMemory::importAndroidHardwareBuffer()` acquires an
   AHardwareBuffer reference and locks its planes into the SwiftShader memory
   object.
2. `Image::bind()` records the `DeviceMemory` object and offset; it does not
   independently own the memory object.
3. Renderer draw setup resolves color-attachment views into raw image pointers
   and row/slice pitches in `DrawData`.
4. `DrawCall::run()` schedules Marl jobs. Pixel workers access that draw data;
   the `DrawCall` finalizer tears down the draw and completes its draw ticket
   after worker ticket dependencies finish.
5. `Renderer::synchronize()` takes a later ticket and waits for earlier draw
   tickets. It returns after those draw jobs complete.
6. `CmdEndRenderPass::execute()` and `CmdEndRendering::execute()` call
   `Renderer::synchronize()` before command-buffer submission returns.
7. `Queue::submitQueue()` signals submit semaphores after command buffers
   return. If the submission has a fence, it synchronizes the renderer before
   completing the fence event.
8. Freeing imported device memory calls AHardwareBuffer unlock/release.

Vulkan callers must not destroy/free objects while they are being accessed by
pending work. The source audit and deterministic test below exercise the
renderer ticket boundary; they do not prove which caller-side object was
associated with the v4 fault.

## Queue signal-order hypothesis

The source does signal semaphores before its optional final queue-level
renderer synchronization. For render-target work, however, both legacy and
dynamic render-pass end commands synchronize the renderer before the command
buffer returns to the signal loop. The fence path synchronizes before its fence
event completes. This makes the observed AaaS render-target path's completion
boundary explicit in the source. The separate queue-signal experiment did not
exercise a signal semaphore, and the healthy v10 trace recorded 485 queue
submissions but zero signal-semaphore events. The v4 trace has no queue IDs.
Therefore semaphore ordering is **not implicated in the observed v4 path**;
no queue patch was made. This is not a claim about untested queue commands or
all possible SwiftShader submissions.

The Vulkan contract requires queue submission signals to follow completion of
the batch's work ([queue submission](https://docs.vulkan.org/spec/latest/chapters/devsandqueues.html),
[synchronization](https://docs.vulkan.org/spec/latest/chapters/synchronization.html)).
Whether a caller-side object lifetime was valid in v4 remains unknown.

## Deterministic lifetime regression

`experiments/graphics-stability/renderer_ticket_lifetime.cpp` uses the actual
pinned SwiftShader Marl `Ticket::Queue` primitive used by renderer draw tickets
and synchronization. A gated worker remains in flight while a later
synchronization ticket is taken. The valid case verifies synchronization does
not complete and the modeled mapping remains live until the worker completes;
the caller then retires the mapping. The negative control retires the modeled
mapping while the worker is gated and detects the invalid order through a
liveness check without dereferencing freed memory.

Run it with:

```sh
python3 experiments/graphics-stability/run_renderer_ticket_lifetime_test.py
python3 experiments/graphics-stability/run_renderer_ticket_lifetime_test.py --sanitize
```

Both runs passed on the pinned source. The sanitizer run reported no ASan or
UBSan error. This is a synchronization-primitive contract test, not a complete
Vulkan/AHardwareBuffer integration test.

The event analyzer in `scripts/correlate_swiftshader_composer_buffers.py` now
also follows target attachments, rather than only descriptor-referenced
resources. On the healthy v10 same-process trace, 21 of 23 target-backed memory
identities had observed draw completion, renderer synchronization, then
AHardwareBuffer release. Two had no explicit release before trace end and
remain unknown. The analyzer labels this as trace event order, not standalone
happens-before proof. For the v10 target path, the source's ticket wait is the
completion mechanism represented by the synchronization event. Details and
hashes are in
[`v10_target_retirement_order.json`](../../results/graphics-stability/buffer-lifetime/v10_target_retirement_order.json).

## Current-candidate runtime checks

The no-tracing corrected candidate was used for two bounded, no-resize
two-application startup/render/shutdown checks on 2026-11-02:

- Default: `m1b84_session_7a1ffr5h`.
- Enhanced source-LMKD/cgroup with resource diagnostics:
  `m1b84_session_aq8gm9gq`.

Both reached RUNNING with Settings and Contacts and ended STOPPED. Logcat scans
found no fatal exception, fatal signal, ANR, or Bluetooth crash signature.
Presenter import/submit/release counts balanced and both presenters reported
zero outstanding buffers. Enhanced session cgroup removal was verified. These
sessions were smoke checks, not resize trials. Existing bounded resize and
resize-back evidence for this same corrected no-tracing candidate is retained
in the M1E live records; those records are not reinterpreted as proof of the v4
root cause. Machine-readable summaries and raw log hashes are in
[`current_candidate_two_app_smoke_20261102.json`](../../results/graphics-stability/buffer-lifetime/current_candidate_two_app_smoke_20261102.json).

## Closure decision

**PASS/CLOSED: supported current-build ownership verification; historical v4
cause unresolved.** The controlled ticket test includes a safe invalid-order
negative control; same-process v10 tracing joins target allocation identity to
draw completion, synchronization and release; and the accepted current
candidate has bounded default/enhanced resize evidence plus fresh two-app
smoke runs. No source defect that would justify a product fix was demonstrated
in these current supported paths. The historical v4 stale access remains an
unresolved incident and is not relabeled fixed. A future recurrence should use
the v10 identity trace and preserve the associated RenderEngine fence/resource
retirement identity before any new queue or lifetime change is considered.

This closure is bounded to the cited source, build and exercised paths. It is
not a universal claim that SwiftShader or Android graphics cannot fail.

## Separate historical v4 defect status

The PASS/CLOSED result above applies only to the earlier current-build ownership
verification route. It does not close the historical v4 defect. That defect
remains **OPEN / UNRESOLVED** until its stale-access cause and responsible
ownership boundary are established and corrected. The 2026-11-02 v4-behavior
identity-trace replay reproduced a distinct 960×557 guard-page bounds fault and
healthy 960×578 release ordering in later processes; neither result identifies
the historical v4 object's submission or retirement fence. See
[`swiftshader-v4.md`](swiftshader-v4.md) and
[`v4_idtrace_replay_20261102.json`](../../results/graphics-stability/buffer-lifetime/v4_idtrace_replay_20261102.json).
