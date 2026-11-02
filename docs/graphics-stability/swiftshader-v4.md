# Historical SwiftShader v4 fault

Status: **PASS/CLOSED — paired-row bounds defect established and corrected**
Evidence date: 2026-11-02
M1E and Bluetooth status: unchanged.

## Causal reconstruction

The historical `m1b84_session_hqgkycni` fault was not a read from the released
960×578 AHardwareBuffer. It was an out-of-bounds paired-row read from a live
960×557 color target; its address happened to equal the adjacent, already
unmapped 960×578 buffer's base. This resolves the previously reported
stale-buffer interpretation.

In SurfaceFlinger PID 222, TID 262 executed
`PixelRoutine_00000042` at routine offset `0x125f`:

```asm
movq (%rcx,%rax,1),%xmm1
```

The original registers give `r8=0x7f31c8ba3400`, `rdx=0xd00`,
`rcx=0x7f31c8ba4100`, and `rax=0xf00`. The v4 JIT code dump confirms the
preceding instructions set `rcx = r8 + rdx` and load the row pitch into `rax`.
The original trace identifies a 960×557 AHardwareBuffer at
`0x7f31c899a000`, with a 3840-byte row pitch and GPU framebuffer usage. The
address arithmetic is:

```text
r8 - target_base = 0x209400 = 556 × 3840
rdx              = 0x00d00 = 832 × 4
fault             = target_base + 556 × 3840 + 832 × 4 + 3840
                  = target_base + 557 × 3840 + 832 × 4
                  = 0x7f31c8ba5000
```

The tombstone maps the 557-row target from `0x7f31c899a000` through
`0x7f31c8ba4fff`, exactly `0x20b000` bytes. The fault address is the first
byte after that mapping: row 557, pixel 832, beyond a 557-row image.

The trace also records a different 960×578 AHardwareBuffer at
`0x7f31c8ba5000`, released 32.5 ms before the crash. That release explains why
the one-past-target address was unmapped. It does not make the released buffer
the object read by the instruction. The 960×557 mapping remained present in the
tombstone. The earlier inference that the load was at offset zero of the 578
buffer considered the fault address relative to that buffer but did not account
for the adjacent live 557 target.

## Reproduction and correction

This is the same `PixelRoutine::writeColor()` odd-height paired-row bounds
defect corrected in commit
[`f38251d`](../../experiments/m1e/patches/swiftshader_coherent_diagnostic.patch).
The fix carries the color attachment height into `DrawData`, clamps the
second-row preservation-read pitch to zero on the last odd-height quad, and
masks invalid helper-row color/depth/stencil writes.

The independent v41 replay, built with the correction intentionally omitted,
crashed at the first unmapped byte after its 960×557 target with the same
`writeColor` paired-row instruction. The replay also had a retired allocation
at that virtual address, demonstrating why address-only attribution is unsafe.
The earlier v8 pre-fix run independently linked the faulting JIT access to its
960×557 VkImage, VkDeviceMemory, draw, and render area.

The corrected no-tracing candidate is
`m1e_swiftshader_fixed_notrace_v2.so`, SHA-256
`e42a0bd8dfe3e0eea6c3d6753f9f9fa254d348366847241ca3c7e4b9ac9affee`, Build ID
`603ff4f389a1050a89743c1adef98c7a39dfefb4`. Its manifest records pinned
SwiftShader revision `cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5` and source diff
SHA-256 `49c1ce42f0cb09dd69a81645c9a3bec91a390c958ac3d49ff2bd3edf4df86ece`.
The default AaaS runner selects this diagnostics-disabled candidate. It passed
the actual 720×1280 → 960×578 → 960×557 → 960×565 → 720×1280 sequence in both
default and enhanced LMKD/cgroup sessions. Both ended STOPPED, matched Android
source frames to requested sizes, survived without SurfaceFlinger or
system_server fatal events, balanced presenter buffer accounting, and ended
with zero outstanding buffers. Enhanced-mode cgroup cleanup passed.

The v4 run itself remains a historical FAILED session. The original tombstone,
trace, and JIT code are unchanged. The preserved historical production overlay
also remains byte-identical at SHA-256
`1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181`.

## Scope and separate questions

The evidence establishes the actual out-of-bounds mechanism and connects it to
the existing source correction. It does not establish an additional
SwiftShader/ANGLE use-after-free, a premature Vulkan retirement defect, or a
semaphore-ordering defect. No such correction is claimed or needed to explain
this fault. The independent bounded current-build ownership verification
record remains intact.

The initial stale-buffer interpretation in
[`swiftshader_v4_ownership_narrowing_20261102.json`](../../results/graphics-stability/swiftshader_v4_ownership_narrowing_20261102.json),
and the earlier unresolved conclusion in
[`v4_idtrace_replay_20261102.json`](../../results/graphics-stability/buffer-lifetime/v4_idtrace_replay_20261102.json),
are preserved as dated analyses and superseded by the register-and-mapping
reconstruction in
[`v4_fault_geometry_reconstruction_20261102.json`](../../results/graphics-stability/buffer-lifetime/v4_fault_geometry_reconstruction_20261102.json).
