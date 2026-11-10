# Android-as-a-Service (AaaS)

AaaS runs Android 16 applications in individual Wayland windows on x86_64 Linux. A persistent Android runtime owns shared desktop bridges; launching an application creates its display endpoint and presenter, and closing it releases those resources.

This is an experimental **trusted development runtime**. Live acceptance currently covers one Arch Linux/KWin host. It is not a production security sandbox or a certified cross-distribution release.

## Installation and use

Use a complete portable development bundle containing `install`, the Android rootfs, runtime components and integrity metadata. A source checkout alone does not provision the prepared Android image. From an extracted bundle:

```sh
./install --workspace "$HOME/.local/share/aaas/workspaces/android16" \
  --installation "$HOME/.local/share/aaas/installations/android16" \
  --config-home "$HOME/.config/aaas" \
  --data-home "$HOME/.local/share/aaas"
```

Use the installed executable explicitly if it is not on your PATH:

```sh
AAAS="$HOME/.local/share/aaas/installations/android16/bin/aaas"
"$AAAS" runtime install-service
"$AAAS" runtime start
"$AAAS" runtime status
"$AAAS" apps install /path/to/trusted.apk
"$AAAS" apps list
"$AAAS" apps launch com.android.settings
"$AAAS" apps running
"$AAAS" logs
"$AAAS" runtime stop
```

The generated user service is `aaas-runtime.service`. Use `apps close INSTANCE_ID` to close one window. Updates use `update /path/to/bundle`; `rollback` restores the retained prior runtime. `uninstall` preserves userdata by default. See the [installation guide](docs/portable-development-release.md); dated acceptance sections there describe earlier candidates, not automatic acceptance of every new bundle.

## Implemented capabilities and boundaries

- Persistent Android with zero-window idle; dynamic independent windows, input, focus and Android framebuffer resizing.
- Historical nine-application simultaneous-window acceptance on KWin.
- ARM translation through the existing Native Bridge; tested applications do not establish universal ARM compatibility.
- PipeWire audio, microphone, clipboard and Plasma notifications. [Human listening evidence](results/audio/human-listening-2026-11-10.json) records audible playback on the development laptop.
- [Android networking](docs/android-networking.md) uses rootless slirp4netns and validated virtual Ethernet over the host connection. Android Wi-Fi hardware/SSIDs are unsupported.
- Scoped shared storage is implemented. Gallery external-cache/project-quota compatibility remains limited.
- Physical Bluetooth/peripheral mediation and other compositors have separate acceptance boundaries.

Android SELinux enforcement is unavailable in the diagnostic profile. Use only trusted APKs. Android image provenance, redistribution licensing, public release authentication and production security require further closure. A manifest hash verifies integrity, not publisher identity.

## Development and testing

```sh
./aaas doctor
./aaas help
python3 -m unittest discover -s tests -q
```

The Python suite passed 541 tests on 2026-11-10. Unit tests do not establish live graphical acceptance. Keep runtime tests and their exact bundle identity in `results/`.

The [M5 build-input guide](docs/m5-portable-development-release.md) describes reproducible helper APKs, per-install signing and audio overlays. The Android platform itself consumes a prepared diagnostic image; it is not currently reproduced entirely from AOSP source. The [image assembly guide](docs/android-rootfs-reconstruction.md) describes the separate incomplete upstream-image reconstruction path.

Do not commit userdata, private keys or generated binaries. Preserve existing work and use focused Conventional Commits with relevant regression evidence.

## Documentation

- [Runtime configuration and host diagnosis](docs/developer-runtime.md)
- [Portable install, update and uninstall](docs/portable-development-release.md)
- [Graphics architecture](docs/m1e-architecture.md)
- [Desktop integration](docs/milestones/m4-native-desktop-integration.md)
- [ARM compatibility](docs/compatibility/arm64-applications.md)
- [Networking](docs/android-networking.md)
- [Persistent userdata](docs/storage/android-persistent-userdata.md)
- [Storage capacity policy](docs/storage/workspace-capacity-policy.md)
- [Security boundaries](docs/security/rootless-android-architecture.md)
- [Dependency and license inventory](docs/dependencies-and-licenses.md)

Historical milestone documents retain their dated findings. No project-wide license grant should be inferred from upstream component licenses; redistribution clearance remains open.
