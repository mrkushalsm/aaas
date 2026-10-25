# Proposed independent boundaries (unverified)

`AOSP/SurfaceFlinger -> AIDL Composer3 service -> AaaS task/buffer transport -> native Wayland presenter -> desktop compositor`.

Composer3 service owns Android display/layer validation and buffer/fence bookkeeping. A private Unix `SOCK_SEQPACKET` channel carries versioned messages and `SCM_RIGHTS` DMA-BUF/fence FDs. A buffer is registered once by stable ID; every task incarnation has a generation ID. A bounded frame queue rejects stale generations. Release feedback maps to the exact buffer and generation before Android may reuse it. The presenter creates one `xdg_toplevel` per task, negotiates linux-dmabuf feedback and optional explicit sync, and records presentation feedback. No wire format or implementation is frozen at M0; fd ownership, failure atomicity, protocol versioning and trust boundary need test vectors before code.

Presentation tiers: direct subsurface, composed client target, GPU conversion, correctness-only SHM fallback. Missing explicit sync requires a separately proven safe path, not silent CPU waits. Production isolation and Native Bridge selection remain experiment outcomes. Lipstick/Qt HWC are isolated under `experiments/`, never runtime requirements by assumption.
