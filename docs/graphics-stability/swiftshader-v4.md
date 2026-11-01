# Historical SwiftShader v4 buffer lifetime investigation

Status: **advanced; root cause unresolved**
Evidence date: 2026-11-02
M1E status: unchanged; this investigation is separate from M1E closure.

## New reconstruction from the preserved crash

The v4 crash is a stale access after unmapping, not the separate odd-height
bounds defect. In SurfaceFlinger PID 222, TID 262 (`Thread<15>`) executed
`PixelRoutine_00000042`. At routine offset `0x125f`, the 8-byte load
`movq (%rcx,%rax,1),%xmm1` calculated `0x7f31c8ba4100 + 0xf00`, exactly the
base `0x7f31c8ba5000` of AHardwareBuffer `3560527888403`. The allocation was
960x578 with a 3840-byte row stride; if mapped, the computed offset is zero,
inside its advertised extent. The tombstone says that page was unmapped at the
fault. The distinct 960x557 paired-row correction does not explain this even-
height access.

The v4 trace records the matching `AAAS_AHB_VK_REF_RELEASE_END` on TID 235,
the SurfaceFlinger `RenderEngine` thread, 32.5 ms before the crash. The
AHardwareBuffer usage flags are `0xb00`, which include GPU sampled-image
(`0x100`), GPU framebuffer (`0x200`), and composer overlay (`0x800`) bits. The
JIT byte-pattern/source match identifies this particular load in
`PixelRoutine::writeColor()` while reading the color attachment. Together,
these facts tie the stale address to an allocation released by the RenderEngine
thread and later accessed as a color target by a SwiftShader renderer worker.
They do not name the Vulkan object chain.

At tombstone capture, TID 264 was in
`CmdEndRendering::execute -> Renderer::synchronize -> marl::Ticket::wait`.
TID 235 was in ANGLE `GL_Finish -> CommandQueue::finishResourceUse ->
 vk::Device::waitForFences`. Thus renderer work had not drained at the crash
boundary and the RenderEngine was waiting on a Vulkan fence. Neither stack
contains an AHardwareBuffer, VkImage, framebuffer, or submission identity, so
these observations do not prove that either wait governed the released buffer.
The release event is emitted from SwiftShader's external-memory unlock/release
path; v4 did not log the owning VkDeviceMemory handle or its destruction call.

## What remains unproven

Two ownership explanations remain viable:

1. ANGLE/SurfaceFlinger retired the imported memory while a submitted draw still
   referenced its color attachment.
2. SwiftShader retained a target pointer in a renderer job after the caller's
   Vulkan lifetime boundary had completed.

A third independent source concern is semaphore completion ordering in the
pinned SwiftShader queue implementation: `Queue::submitQueue()` signals
semaphores before its optional end-of-task renderer synchronization. The Vulkan
queue-submit contract requires signal operations to cover the commands in the
batch ([`vkQueueSubmit`](https://docs.vulkan.org/refpages/latest/refpages/source/vkQueueSubmit.html)). However, the historical v4 trace has no
queue/submission events, while later v10 runtime traces recorded no
signal-semaphore events. This ordering concern is not linked to the v4
AHardwareBuffer and is not claimed as its cause or as an AaaS runtime
reproduction. No speculative change was made.

The v10 trace infrastructure already records `AAAS_DRAW_TARGET`, including
AHardwareBuffer-backed memory, image/view identity, submission, draw, and
renderer completion. In healthy SurfaceFlinger PID 261, AHardwareBuffer
`9650791514121` mapped to memory 273, image 272, and view 276 at 960×578. Its
last recorded target draw (submission 412, draw 1332) completed and renderer
synchronization returned before view/image destruction and AHardwareBuffer
unlock/release. This confirms the instrumentation can preserve the full chain
for a healthy 960×578 target. It is a different SurfaceFlinger process and a
different AHardwareBuffer; it does not identify or explain the v4 release.

## Next required diagnostic observation

If this crash recurs, preserve one same-process trace containing all of:

- The faulting AHardwareBuffer identity and mapping base.
- Its VkDeviceMemory, VkImage, VkImageView, framebuffer/color-attachment, and
  draw-target links.
- Queue submission and renderer worker completion for the faulting draw.
- The ANGLE/RenderEngine resource-retirement and fence event that caused
  `vkFreeMemory`/AHardwareBuffer unlock.
- The virtual-display resize generation associated with the target.

The coherent v10 diagnostic build has the target/submission tracing needed for
that observation. Do not repeat identical resize trials solely to seek a crash;
use a bounded run only when the trace can preserve this missing link. Keep the
production overlay unchanged. The historic v4 tombstone and trace remain
preserved externally with hashes in
[`swiftshader_v4_ownership_narrowing_20261102.json`](../../results/graphics-stability/swiftshader_v4_ownership_narrowing_20261102.json).
