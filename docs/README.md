# Documentation index

The public-source history omits generated `results/` and `artifacts/` run
outputs. Historical milestone notes may describe those local records; any
non-clickable evidence path in those notes refers to the original maintainer
archive. Reproducible test inputs are kept under `tests/fixtures/`, and the
selected developer-preview screenshots are under `docs/media/`.

## Getting started

- [Root README](../README.md): project overview, tested scope, quick start, and limitations.
- [Contributing](../CONTRIBUTING.md): source tests, provenance expectations, and license boundary.
- [Third-party source notices](../THIRD_PARTY_NOTICES.md): known file-level terms and attribution guidance.
- [Portable development release guide](portable-development-release.md): local bundle install, CLI operations, update and uninstall behavior.
- [Developer runtime guide](developer-runtime.md): source checkout, host diagnosis, and image/build boundaries.
- [Troubleshooting](developer-runtime.md#host-diagnosis): host checks and runtime constraints.

## Architecture and operations

- [Architecture overview](architecture.md): Android userspace, namespaces, windows, Native Bridge, audio, network, and lifecycle.
- [Rootless Android security boundary](security/rootless-android-architecture.md): trust model and limitations.
- [Android networking](android-networking.md): virtual Ethernet and host uplink.
- [Persistent userdata](storage/android-persistent-userdata.md): workspace data boundaries.
- [Workspace capacity policy](storage/workspace-capacity-policy.md): reserves and enrollment checks.

## Release and provenance

- [v0.1.0-dev-preview notes](release/v0.1.0-dev-preview.md): exact candidate, acceptance, and release limitations.
- [M5 acceptance JSON](release/portable-preview-af3dcb4-acceptance.json): machine-readable exact-candidate results.
- [Licensing and external runtime inputs](dependencies-and-licenses.md): project-license status, upstream notices, and Android image limitations.
- [Bundle redistribution decision](release/bundle-redistribution-decision.md): evidence-based decision for the accepted binary.
- [Portable release guide](portable-development-release.md): install lifecycle and historical acceptance chronology.

## Development and historical records

- [M5 build-input guide](m5-portable-development-release.md): declared runtime inputs and build steps.
- [Android source lock](android-source-lock.md): source pins and reproducibility limits.
- [Android rootfs reconstruction](android-rootfs-reconstruction.md): incomplete image assembly path.
- [Roadmap](roadmap.md): canonical milestone planning, including historical status snapshots.
- [M1E graphics architecture](m1e-architecture.md): detailed presenter implementation notes.
- [M4 desktop integration](milestones/m4-native-desktop-integration.md): implementation history and acceptance records.
- [M3 ARM64 Native Bridge](milestones/m3-arm64-native-bridge.md): bounded translation feasibility evidence.

Historical milestone documents retain dated findings. Check the linked
candidate-specific acceptance record before treating a historical result as
current bundle acceptance.
