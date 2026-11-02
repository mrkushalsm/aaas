# SwiftShader graphics stability and historical v4 fault

Status: **PASS/CLOSED — historical fault mechanism established and corrected**

Evidence date: 2026-11-02

This is a separate post-M1E stability workstream. It does not change the M1E
closure or the independent Bluetooth runtime-health decision. The earlier
bounded current-build ownership verification remains a separate completed
result.

## Historical v4 fault resolution

The first interpretation of `0x7f31c8ba5000` as an offset-zero read from the
released 960×578 AHardwareBuffer was wrong. The v4 tombstone and trace show a
960×557 framebuffer mapping ending at `0x7f31c8ba4fff`; JIT register arithmetic
computes the access as row 557, x=832 of that framebuffer. The 960×578
allocation's base happened to be the next address and was released 32.5 ms
earlier. See the complete equations, raw artifact hashes, and pre/post runtime
identities in
[`v4_fault_geometry_reconstruction_20261102.json`](../../results/graphics-stability/buffer-lifetime/v4_fault_geometry_reconstruction_20261102.json).

The causal defect is the odd-height paired-row `PixelRoutine::writeColor()`
out-of-bounds access, corrected by commit `f38251d`. The historical v4 session
remains FAILED, but its fault mechanism is now established. This is not evidence
of a Vulkan/ANGLE stale-resource retirement defect, and no such fix is claimed.
The earlier analysis records remain preserved and are superseded as explained
in [`swiftshader-v4.md`](swiftshader-v4.md).

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

**PASS/CLOSED: the historical v4 JIT out-of-bounds read is causally identified
and the source correction is active in the default AaaS runtime candidate.**
The pre-fix behavior was reproduced in isolated 960×557 runs, including the
same `writeColor` paired-row instruction and mapping-end address calculation.
The correction clamps the invalid helper-row access and masks invalid writes.
Default and enhanced runtime runs using the diagnostics-disabled corrected
candidate completed the complete odd-height resize and resize-back sequence,
matched Android source buffers, survived without fatal graphics/framework
events, balanced presenter ownership, and drained to STOPPED. These are bounded
acceptance results, not a universal no-crash guarantee.

The separate ticket-lifetime test and v10 resource traces remain useful current
ownership evidence, but they were not the causal proof for v4. The semaphore
ordering observation remains a separate unproven hypothesis and is not
attributed to this incident.
