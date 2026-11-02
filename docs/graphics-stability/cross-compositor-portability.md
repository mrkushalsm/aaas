# Post-M1E compositor portability

Status: **PARTIAL/OPEN — real Android rendering verified on KWin, Weston and Sway; full configure/resize acceptance failed on Sway.**

The structured matrix and raw artifact references are in [acceptance.json](../../results/post-m1e/compositor-portability/acceptance.json). Graphics and frame-pacing results are also summarized in [frame-pacing-and-latency.md](frame-pacing-and-latency.md).

## Verified scope

| Compositor | Tested environment | Android rendering and feedback | Two windows | Resize/lifecycle | Result |
|---|---|---|---|---|---|
| KWin 6.7.5 | Host Wayland session | Real Android probe frames; `wp_presentation`, `CLOCK_MONOTONIC` | Existing baseline; two-probe runs available | Existing resize and lifecycle baseline retained | Baseline PASS |
| Weston 15.0.1 | Nested Wayland backend, GLES/llvmpipe over KWin | Real Android DMA-BUF frames; `wp_presentation`, `CLOCK_MONOTONIC_RAW` | Two Android windows visible in a separate live session | Full configure, resize, input and close/reopen matrix incomplete; one final buffer invalidated on teardown | PARTIAL |
| Sway 1.12 / wlroots 0.20.2 | Nested Wayland GLES backend over KWin | Real Android DMA-BUF frames; `wp_presentation`, `CLOCK_MONOTONIC` | Two independent Android toplevels and continuous outputs | Configure-to-Android resize convergence failed at 500×740; stale 720×1280 frames were safely rejected | FAIL for full acceptance |
| Hyprland | Not installed | Not tested | Not tested | Not tested | NOT VERIFIED |
| Mutter / GNOME Shell | Not installed | Not tested | Not tested | Not tested | NOT VERIFIED |

Sway advertises `zwp_linux_dmabuf_v1` v5 and `wp_presentation` v2 in the tested nested setup. Weston advertises DMA-BUF v3 and presentation-time v2. Neither nested compositor advertised explicit synchronization in the tested setup; the AaaS staged path continued to use its existing safe synchronization behavior. Sway direct feedback provided no refresh interval. Weston provided 16.667 ms and a `CLOCK_MONOTONIC_RAW` presentation clock. KWin provided 16.666 ms and `CLOCK_MONOTONIC`.

## Reproduced Sway resize failure

Under Sway, both 420×740 floating windows rendered Android source frames at 720×1280 without rejection. Resizing one to 500×740 caused the presenter to request generation 2 and the display broker to report `resized ... size=500x740`; Android `DisplayManager` then reported `widthPixels=500 heightPixels=740`. Composer continued delivering 720×1280 frames. The presenter logged `matches_configure=false` and `rejected_stale_or_format` with `release_ack=true`, then no further accepted frames for that window. The other virtual display continued presenting independently. Shutdown reported zero outstanding buffers. No synchronization or stale-frame validation was bypassed.

The resize request and Android display metrics therefore succeeded, but the output-buffer dimensions did not converge. This work did not identify the deeper SurfaceFlinger/Composer cause or apply a production fix. Sway is not accepted for full window-resize portability until that path is corrected and retested.

## Environment and evidence

Weston and Sway package trees were extracted under the external AaaS workspace and run as nested compositors. Android image, Composer, SwiftShader, and host compositor were not replaced. This tests protocol and DMA-BUF interoperability in nested software-rendered environments; it does not establish performance equivalence with native KWin output or universal Wayland compatibility. Hyprland and Mutter were absent and remain out of scope for the verified KWin/Weston/Sway baseline.

The performance acceptance record contains compositor versions, runtime session IDs, buffer accounting, frame statistics, and SHA-256 references. One failed runner attempt caused by supplying the same probe package twice under different requested package names is preserved as a harness misconfiguration and excluded from graphics results.
