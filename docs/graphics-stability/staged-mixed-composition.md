# Staged mixed-composition integration

Status: **PASS/CLOSED — real Android staged mixed composition verified for the constrained supported contract**

Evidence date: 2026-11-03

This scoped result closes the staged path. The older broad mixed-composition record remains **OPEN/BLOCKED** for exact Composer-output allocation presentation; this document does not change it. The M1E, Bluetooth, and SwiftShader decisions are unchanged. Machine-readable run details and hashes are in **acceptance.json** (maintainer archive only).

## Supported path

Real SurfaceFlinger CLIENT target content and one supported topmost DEVICE layer are composed by the diagnostic Composer3 into a distinct output DMA-BUF allocation A. The presenter waits for the incoming synchronization boundary, copies visible pixels into its own GBM allocation B using the stride-aware staging path, then submits B to Wayland with explicit synchronization. B remains unavailable until Wayland releases it. A and B are tracked independently.

The validated composition contract is limited to linear RGBA8888/BGRA8888 buffers, supported alpha/blend modes, untransformed layers, integral one-to-one crop/frame geometry, and one DEVICE layer over the CLIENT target. Unsupported formats, modifiers, transforms, color operations, protected content, and arbitrary multi-layer DEVICE composition are not claimed; unsupported requests must be rejected or negotiated to CLIENT composition.

The Composer allocation identity is checked with DMA-BUF `fstat(st_dev, st_ino)`. Live traces correlate that identity from Composer output to presenter transport receipt. Wayland imports a different staging backing. The Composer pixel oracle records exact visible-pixel checks. Per-frame presenter events establish copy start, source-copy completion, Wayland import, commit, and release order.

## Live matrix

Six independent sessions passed the evidence validator: three default and three enhanced source-LMKD/cgroup sessions. Frame-level Composer classification confirms both presenters executed mixed composition in all six sessions; the two coexistence sessions also contain frames from both alias and mixed modes on each display. Four sessions exercised both displays in mixed mode concurrently throughout their principal resize coverage. The default full resize run covered both windows through 960×578, 960×557, 960×565, and resize-back to phone geometry. A separate enhanced run resized both windows to 955×578 and 952×582. Each accepted session ended STOPPED; presenter imports, submissions, and releases balanced with zero outstanding buffers or teardown invalidations. Enhanced session cgroups were removed. Logcats had no fatal exception, signal, or ANR marker.

The default coexistence session verified Settings mixed with Contacts alias, then Contacts mixed with Settings alias. The enhanced coexistence session verified Contacts mixed with Settings alias at startup, then Settings mixed with Contacts alias; it also closed and reopened Contacts within the shared runtime. The close/reopen session produced two presenter summary lifecycles for that slot, and the validator aggregates both rather than discarding one.

Six genuine desktop screenshots are preserved under `results/post-m1e/staged-mixed-composition/screenshots/`. Screenshots document two mixed windows, resized windows, both default coexistence directions, and enhanced Contacts mixed interaction. Session reports contain hashes for the raw Composer logs, presenter logs, and STOPPED journals.

## Measurements and limits

Matched alias/mixed frames in the same runtime show presenter staging-pipeline p95 values of 1.6–2.0 ms. The timer includes GBM allocation, DMA-BUF synchronization, mapping, visible-row copy, unmap/sync, and export; it excludes acquire-fence wait and Composer-side blending, so it is not a memcpy-only measurement. One default resize session recorded an isolated 326.7 ms sample after acquire-fence wait. The instrumentation does not identify which staging-pipeline step stalled, and the outlier remains unresolved rather than being presented as a copy-bandwidth result. The coexistence measurements do not show a sustained mixed-path regression, but they do not explain that outlier.

The exact-allocation direct Wayland import remains **OPEN/BLOCKED** because the tested synchronous Composer present/release path stalled and a correct asynchronous native-fence bridge is unavailable in this host configuration. The safe staging copy is the accepted ownership boundary. Other compositors, arbitrary DEVICE-layer sets, hardware formats/modifiers, protected content, and color transforms remain outside this acceptance.

## Verification

The final regression run and current test count are recorded in `acceptance.json`. The isolated Composer tests cover backing identity, visible pixel and stride correctness, odd dimensions, padding, blend behavior, and invalid bounds. M1A synchronization and transport tests cover malformed packets, invalid fence descriptors and cleanup, delayed acquire fences, and out-of-order releases. The new live evidence validator covers output-to-transport identity, staging allocation distinction, frame synchronization order through compositor release, terminal status, and repeated presenter lifecycles. End-to-end fault injection for GBM allocation failure, Wayland disconnect during a pending copy, and forced termination during copy was not run; those cases remain listed in the acceptance record.
