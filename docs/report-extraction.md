# Report extraction and decisions deferred

Source: `research-report.pdf`, 36 pages, report SHA-256 `6568294b6fc38ecc9c84b8d0a558fded06abbac64ba9820412ea16acc3023e87`. Read in full on 2026-10-25. `manifests/sources.json` records all named repositories with available pins; `results/m0/source-verification.json` records remote checks. The `lineage-20` HAL branch is mutable; the following have no exact report pin: libhybris, libgbinder, Goldfish, AOSP Berberis, drmfb-composer, LXC, QEMU, Mesa/Zink, PipeWire, portals, and the AOSP product/manifest. These cannot yet form a fully immutable build closure.

## Report experiments and acceptance

1. Freeze sources and capture host: immutable manifest and hardware evidence.
2. Lipstick simplecompositor on x86_64: launch nested, two clients, focus/resize/close, no mobile daemon. Compile alone is insufficient.
3. Qt HWC: plugin discovered and loaded, virtual HWC communication without inversion or duplicate full-frame composition; otherwise reference only.
4. Virtual Composer3: Settings in resizable xdg_toplevel, no CPU framebuffer copy, 10,000 fence-correct frames, clean resize/close.
5. Direct import: producer buffer identity equals host imported buffer; zero blits on supported RGBA/GLES Intel/AMD path.
6. Sync torture: hundreds of thousands of transitions including reuse, minimize, resize generation, destruction, out-of-order release.
7. Fallback: unsupported modifier, multi-GPU, YUV, HDR and protected paths degrade without corruption/crash; protected content may be explicitly unsupported.
8. Digitalis/Teto: ARM64-only JNI suite, threads, signals, NEON, dlopen, Vulkan, AHardwareBuffer, Binder; QEMU differential instruction oracle. Android x86_64 image and AArch64 ELF must be proven.
9. LXC versus direct namespaces: same image, Binder/render nodes, readiness and 30-run cold-start/first-frame protocol.
10. Lifecycle: stopped/warm/frozen; package/activity readiness and first presentation, with background-work trade-off explicit.
11. Baselines: Waydroid, Droidloom, AaaS minimal, AaaS Lipstick; 10 cold boots, 30 cold launches, 100 warm launches, idle/animation, 1000 resizes, multiple windows and GLES/Vulkan/video.
12. Portability: GNOME, KDE, wlroots; Arch, Fedora, Ubuntu/Debian; Intel, AMD, NVIDIA; 60/120+ Hz and scaling modes.

## Architectural risks (all unverified)

- Qt HWC is documented in Qt-to-Android-HWC direction; reverse adaptation may make it unsuitable.
- Lipstick has many Sailfish service dependencies and may add an extra composition pass.
- AIDL Composer3 reference code targets DRM/KMS or emulator transports, not this proposed Unix transport.
- DMA-BUF format/modifier and GPU topology may prevent direct import; explicit sync protocol may be absent.
- Buffer and fence lifetime across Android and Wayland remains unproven.
- Digitalis project tests do not prove real-app Native Bridge compatibility or stable SIMD speed.
- LXC unprivileged device/Binder integration and direct-namespace security require controlled trials.
- Stopping Android loses background services; portals/audio/clipboard integrations remain designs only.
- Droidloom parity requires measured p95/p99 frame pacing and launch within 5%; Sailfish retention needs >=10% improvement or broader compatibility with <=5% regression.

The report's recommended Android 16/API 36 baseline is provisional. Desktop, GPU, distribution and Android API remain experimental variables.
