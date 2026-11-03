# Post-M1E compositor portability

Status: **PARTIAL/OPEN — Sway resize convergence is corrected and verified; Weston lifecycle acceptance and KWin 60 Hz performance remain incomplete.**

The structured matrix and raw artifact references are in [acceptance.json](../../results/post-m1e/compositor-portability/acceptance.json). Graphics and frame-pacing results are also summarized in [frame-pacing-and-latency.md](frame-pacing-and-latency.md).

## Verified scope

| Compositor | Tested environment | Android rendering and feedback | Two windows | Resize/lifecycle | Result |
|---|---|---|---|---|---|
| KWin 6.7.5 | Host Wayland session | Real Android probe frames; `wp_presentation`, `CLOCK_MONOTONIC` | Existing baseline; two-probe runs available | Existing resize and lifecycle baseline retained | Baseline PASS |
| Weston 15.0.1 | Nested Wayland backend, GLES/llvmpipe over KWin | Real Android DMA-BUF frames; `wp_presentation`, `CLOCK_MONOTONIC_RAW` | Two windows render; close/reopen preserves the remaining window | Resize and controlled input acceptance remain incomplete; teardown accounting is balanced | PARTIAL |
| Sway 1.12 / wlroots 0.20.2 | Nested Wayland GLES backend over KWin | Real Android DMA-BUF frames; `wp_presentation`, `CLOCK_MONOTONIC` | Two independent Android toplevels and continuous outputs | Resized output converged across repeated configure and resize-back transitions; full input/lifecycle matrix remains incomplete | Resize PASS; compositor acceptance PARTIAL |
| Hyprland | Not installed | Not tested | Not tested | Not tested | NOT VERIFIED |
| Mutter / GNOME Shell | Not installed | Not tested | Not tested | Not tested | NOT VERIFIED |

Sway advertises `zwp_linux_dmabuf_v1` v5 and `wp_presentation` v2 in the tested nested setup. Weston advertises DMA-BUF v3 and presentation-time v2. Neither nested compositor advertised explicit synchronization in the tested setup; the AaaS staged path continued to use its existing safe synchronization behavior. Sway direct feedback provided no refresh interval. Weston provided 16.667 ms and a `CLOCK_MONOTONIC_RAW` presentation clock. KWin provided 16.666 ms and `CLOCK_MONOTONIC`.

## Sway resize failure and correction

Under Sway, both 420×740 floating windows rendered Android source frames at 720×1280 without rejection. Resizing one to 500×740 caused the presenter to request generation 2 and the display broker to report `resized ... size=500x740`; Android `DisplayManager` then reported `widthPixels=500 heightPixels=740`. Composer continued delivering 720×1280 frames. The presenter logged `matches_configure=false` and `rejected_stale_or_format` with `release_ack=true`, then no further accepted frames for that window. The other virtual display continued presenting independently. Shutdown reported zero outstanding buffers. No synchronization or stale-frame validation was bypassed.

The resize request and Android display metrics succeeded, but the output-buffer dimensions did not converge. The original failed trace is retained in the acceptance JSON.

### Resize correction and live verification (2026-11-03)

A candidate normal Composer build exposed the cause: virtual-display layer state was only populated in `AAAS_ENABLE_MIXED_COMPOSITION_TEST` builds, while normal staged builds still validated virtual displays through that state. After display recreation, validation therefore reported no tracked layers and did not renegotiate CLIENT composition, so SurfaceFlinger stopped supplying the client target. The fix tracks virtual-display layers in normal builds; the optional mixed test can still choose its supported DEVICE layer. The existing generation, format, dimension, synchronization, and release validation is unchanged.

With the fix, live Sway sessions produced matching new-size CLIENT targets and accepted source frames after resize. In `m1b84_session_5tq1uyxc`, display 2 moved through 508×611, 636×871, 416×711, 496×711, then back to 416×711. Each first matching-size source frame had `matches_configure=true`; later transient previous-size frames remained marked false. The second window continued presenting. Final presenter accounting was 139 imports, 139 submissions, 138 normal releases, one teardown invalidation, and zero outstanding buffers. The runtime ended STOPPED. A second candidate run also showed 508×611, 636×871 and resize-back output. The dimensions reflect Sway's configured content area after decorations/output constraints, rather than the raw requested outer size.

This corrects the previously frozen resize path. It does not complete all Sway input, focus, close/reopen, and lifecycle acceptance, and does not complete Weston acceptance; overall compositor portability remains PARTIAL. The structured acceptance record contains binary and trace hashes.

### Weston two-window lifecycle follow-up (2026-11-03)

An isolated Weston 15.0.1 nested Wayland/GLES session over KWin ran the real two-app AaaS runtime with the same fixed Composer candidate. Both Android presenter surfaces submitted frames and received presentation feedback callbacks. Contacts was closed while Settings remained active, then Contacts reopened on a new virtual display. The three presenter summaries had zero outstanding buffers; each counted the final still-owned buffer separately as teardown-invalidated. The runtime stopped cleanly. This run did not enable timestamp tracing, so its feedback callbacks do not provide presentation timestamps. The earlier Weston protocol probe established its `CLOCK_MONOTONIC_RAW` clock ID 4.

The nested session used Weston kiosk-shell, which does not provide the desktop resize controls needed to exercise configure/resize convergence. No controlled Android input assertion was made in this follow-up. These gaps remain explicit; Weston is still PARTIAL. Session logs and hashes are recorded in the acceptance JSON.

## Environment and evidence

Weston and Sway package trees were extracted under the external AaaS workspace and run as nested compositors. Android image, Composer, SwiftShader, and host compositor were not replaced. This tests protocol and DMA-BUF interoperability in nested software-rendered environments; it does not establish performance equivalence with native KWin output or universal Wayland compatibility. Hyprland and Mutter were absent and remain out of scope for the verified KWin/Weston/Sway baseline.

The performance acceptance record contains compositor versions, runtime session IDs, buffer accounting, frame statistics, and SHA-256 references. One failed runner attempt caused by supplying the same probe package twice under different requested package names is preserved as a harness misconfiguration and excluded from graphics results.
