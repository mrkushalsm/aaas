# M1A host transport prototype

## Scope and build

This experiment is independent of Android, Composer3, Lipstick, Waydroid, and Droidloom. It uses C11, libwayland-client 1.26.0, Mesa GBM 26.2.4, libdrm 2.4.134, the installed Qt 6 package's Wayland XML (xdg-shell and linux-dmabuf v3), and wayland-scanner. The protocol source comes from locally installed packages; these package versions and XML SHA-256 values must be locked for repeatable rebuilding on another host. No host package or graphics configuration was changed.

```
make -C experiments/m1a all test
experiments/m1a/run-live.sh
experiments/m1a/tests/disconnect.sh
```

`AAAS_RENDER_NODE` overrides `/dev/dri/renderD129`; `AAAS_DURATION` overrides five seconds. Logs are retained in `results/m1a/`. The run script requires a working user Wayland session and the listed build packages. It opens an independent xdg_toplevel window titled `AaaS M1A DMA-BUF prototype`. A CPU-written changing XRGB8888 pattern is placed in a GBM BO, exported as a DMA-BUF, passed through a Unix socket, imported by the Wayland presenter, and attached to the surface. This proves the presenter handed the DMA-BUF to the compositor; it does not prove the compositor avoided internal copies.

## Wire contract, version 1

The transport is a private Unix `SOCK_SEQPACKET` socket. Each packet has exactly one fixed-size `aaas_msg` native-endian header with magic `0x53414141`, version 1, type, task generation, buffer ID, dimensions, DRM fourcc, 64-bit modifier, stride, offset, flags, and zero reserved field. `AAAS_BUFFER` must carry exactly one DMA-BUF FD via `SCM_RIGHTS`. Other current messages carry no FD. The receiver uses `MSG_CMSG_CLOEXEC`, rejects truncation, wrong FD count, malformed version, out-of-range dimensions, and non-DMA-BUF FDs, and closes received FDs on rejection. It closes the sender's local export FD after `sendmsg`.

`AAAS_RESIZE` advances the generation and supplies a bounded target size. `AAAS_BUFFER` registers/submits one frame by `(generation, ID)`. `AAAS_RELEASE` is sent only from `wl_buffer.release` for the same pair. The producer marks the BO busy at send and cannot write it again until matching release. Old-generation busy BOs survive resize until release. The presenter rejects a stale generation, unsupported format/modifier, bad stride, or unexpected packet. `AAAS_CLOSE` is a best-effort shutdown notification. This is a prototype wire ABI: it uses native-endian C layout and a single plane, so it is not yet a portable or multipane production protocol.

There is no acquire-fence FD in v1. The producer's CPU mapping is unmapped before export/send, and reuse waits for `wl_buffer.release`. No GPU writer or explicit synchronization path is exercised. The compositor advertises `wp_linux_drm_syncobj_manager_v1` but this prototype intentionally does not bind it because no timeline syncobj producer exists here. Successful presentation is not treated as a synchronization fence. GPU producers require a separately validated acquire/release synchronization design.

The Wayland client binds linux-dmabuf at v3, despite the compositor advertising v5. It records advertised XR24 modifiers, picks the producer's exported modifier only if advertised, and submits via `create_immed`. This has no per-surface feedback parsing; the existing `wayland-info` output records the compositor's v5 feedback. A safe reject is used when modifier negotiation fails. There is no SHM substitute and no claim of zero-copy.

## Observed host and results

`results/m1a/wayland-info.log`, `lspci.log`, `render-nodes.log`, and `uname.log` capture the current host. KWin advertises linux-dmabuf v5, xdg_wm_base v6, presentation-time v2, and DRM syncobj manager v1. Feedback names `/dev/dri/renderD129` as the main device, with XR24 LINEAR and Intel tiled modifiers. The second render node and NVIDIA driver are recorded but not tested. The presenter observed six XR24 modifiers via the v3 events.

`run-live.sh` completed with 300 imports/submissions, 298 compositor releases, 297 presented feedback events, and two discarded feedback events over five seconds. The final attached buffer can remain outstanding at shutdown. The trace checker verified matching release before every reuse. The application received two configure events; the second advanced the generation. Producer kill after one second was handled without a segmentation fault and logged disconnection. The runtime logs are evidence of DMA-BUF import and release callbacks; no screenshot or compositor internal copy trace was captured. CPU pattern writes are counted per frame, host CPU copies and GPU conversions are reported as zero **within this process only**, and presentation feedback plus presenter resource usage are instrumented. The final trace reports 2,772 KiB maximum presenter RSS, 20,962 microseconds user CPU time, and 55,294 microseconds system CPU time; the producer is a separate process and is not included in those figures.

## Missing gates

The window's changing pattern was inferred from successful buffer submissions, but not visually verified in a captured artifact. Rapid user-driven resize, close, compositor termination, stale-generation injection, hostile valid DMA-BUFs, runtime descriptor leak counts, producer resource metrics and explicit GPU synchronization have not been tested. The M1A milestone therefore remains **fail/incomplete** under its stated completion criteria. The next safe experiment is to add a compositor-aware resize/close harness and capture visual evidence, then test a GPU writer with syncobj fences on a compositor that confirms the required protocol.
