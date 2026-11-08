# Portable developer runtime foundation

This work introduces a user-local configuration layer and the `aaas` command
while preserving the documented M4 runtime. It is a scoped engineering tranche
feeding into M6; it does not change the canonical M0–M6 numbering or M4's
`PASS/CLOSED` status.

## Current commands

Run `./aaas help` from a checkout. `aaas` with no arguments displays the same
command list. After setup, a user-local symlink can be installed with
`./aaas setup --install-command`; the shell must include `~/.local/bin` in
`PATH`.

The CLI includes `doctor`, `setup`, `status`, `start`, `stop`, `restart`,
`apps list`, `apps launch`, `apps install`, `apps uninstall`, `images list`,
`images inspect`, `verify`, `logs`, and `version`. `--json` is available for
diagnostic and inspection output. `doctor`, `status`, `verify`, `images list`,
and `version` are read-only and do not download files.

`setup` enrolls a workspace only after a health check and disposable filesystem
capability probes. It will not rewrite an existing configuration or adopt a
nonempty unmarked directory without `--adopt-existing`. It then verifies the
runtime profile and reports an incomplete installation as a nonzero result.
It does not claim that workspace enrollment alone provisions Android.

## Configuration

The resolver in `scripts/aaas_config.py` applies this precedence:

1. Explicit CLI values.
2. `AAAS_*` environment overrides.
3. `$XDG_CONFIG_HOME/aaas/config.toml`.
4. `$XDG_DATA_HOME/aaas/installation.json`.
5. XDG-derived defaults.

When XDG variables are unset, the standard home-directory locations are used.
The runtime directory falls back to a UID-specific directory under `/tmp`.
The selected profile is `android16-ranchu-x86_64`; other profiles and graphics
backends are rejected until validated.

Example configuration:

```toml
[paths]
workspace = "/home/developer/.local/share/aaas/workspace"

[installation]
profile = "android16-ranchu-x86_64"

[runtime]
idle_timeout_seconds = 60
resource_limit = "none"

[features]
audio = false
clipboard = true
notifications = true

[graphics]
backend = "kwin-wayland"
```

Audio can also be enabled for one run with `aaas start --audio` or persistently
with `AAAS_AUDIO=1` / `features.audio = true`. Permission prompts remain owned by
Android. `resource_limit = "cgroup"` selects the existing delegated cgroup v2
policy when the host supports it; `"none"` leaves that optional policy off.

## Workspace safety

The workspace marker enrolls the filesystem UUID, type, and mount target for
that installation. A different UUID at the same path is rejected. Enrollment
probes ownership, modes, hard links, symlinks, atomic rename, user xattrs, ACLs,
and SQLite behavior in a disposable child directory. It checks `ro` and `noexec`
mount flags, available capacity, free-space reserve, and the storage health
policy. No permissions are rewritten. A clean current-boot journal observation
does not certify device hardware health, and existing incident records remain
blocking until the policy is legitimately reconciled.

## Android profile and provisioning status

The profile manifest records the observed M4 Android 16 build identity and
Ranchu audio/graphics interfaces. The public Google SDK image recorded in
`manifests/android-images.json` is the Android Emulator system-image package
`x86_64-36_r02.zip`, not the prepared rootless runtime image. See Google's
[emulator command-line documentation](https://developer.android.com/studio/run/emulator-commandline)
and [AVD documentation](https://developer.android.com/studio/run/managing-avds).

The profile is currently marked **not automatically provisionable**. The
repository's prepared `rootfs_m1b1` is a modified diagnostic image, and the
pinned Digitalis Android source graph does not yet have a complete materialized
source lock and image assembly recipe. The SDK package's historical SHA-1 is
useful for matching the repository's recorded SDK index, but the index does not
provide a SHA-256. `images inspect` therefore reports archive identity and
layout separately from rootless runtime compatibility. It never treats matching
build properties as proof of trusted provenance.

As a result, a fresh checkout can diagnose the host and configure a safe
workspace, but it cannot yet provision a complete runnable Android 16
installation. `verify`, `start`, and package-management operations fail closed
when provenance or required runtime artifacts are absent. This is the remaining
release blocker for the portable developer runtime, not a change to M4's
accepted installed-runtime evidence.

## Host diagnosis

`aaas doctor` performs local checks only. It probes the active Wayland/KWin
environment, user namespaces, an unprivileged BinderFS mount inside a throwaway
user/mount namespace, FUSE access, PipeWire client availability, memory, and the
configured rootfs path. A passing host report does not imply that an Android
image is provisioned or that an untested compositor/GPU combination is
supported.

## Portability boundary

The active runtime path now takes its workspace and rootfs from the shared
resolver rather than the original external-drive path or UUID. Historical
health-policy records and experiment-specific diagnostics retain their
historical device identities. They are not generic defaults. The supported live
matrix remains Linux x86_64, Android 16 x86_64, KWin/Wayland, and the accepted
Ranchu-compatible image build. A second physical host has not been validated.

## Local M4 relocation bundle (2026-11-08)

The `aaas bundle` commands now collect the existing M4 diagnostic rootfs,
selected runtime code, and 145 retained generated workspace artifacts into a
SHA-256 manifest-backed local directory bundle. A fresh user-local installation
can be created with separate workspace, installation, XDG config, and XDG data
paths. Installation integrity is reported separately from runtime closure and
security status. See the [local bundle guide](developer-bundle.md).

This advances artifact relocation, not independent runtime provisioning. The
source rootfs remains `UNVERIFIED_PROVENANCE`; known SELinux-success shims are
preserved and called out; the bundle is unsigned, not approved for untrusted
APKs, and the normal runtime start gate remains blocked. The runtime currently
rebuilds helper APKs and audio overlays and expects a signing keystore, which is
not bundled. Host integration dependencies remain host-specific and are
discovered at use time. A successful install or manifest check does not imply
Android boot. The local development bundle must not be published or treated as
a source-reproducible image.

## Provisioning status check (2026-11-08)

A clean XDG configuration and workspace on the host's persistent ext4 volume
successfully enrolled and passed the workspace guard, then correctly returned
`BLOCKED` because the Android rootfs was absent. No Android session was started
and no existing userdata or prepared rootfs was adopted. The available
`x86_64-36_r02.zip` archive matches its recorded size and Google-indexed SHA-1;
its recorded SHA-256 is computed locally from that matching archive and is not
an independently published Google digest. Archive identity still does not
establish rootless runtime compatibility.

The workspace enrollment defects found during this check are fixed: enrollment
now checks the selected workspace's nearest existing parent for write access,
and the ACL probe asks `getfacl` for numeric IDs. The complete runtime remains
unprovisionable: the diagnostic rootfs has unproven binary/init transformations,
the SELinux success shim is not suitable for untrusted applications, and the
source-built replacements needed for a policy-preserving runtime have not been
built against a matching Android image ABI. See
[`android-runtime-integrity.md`](android-runtime-integrity.md) and
[`android-source-lock.md`](android-source-lock.md).

The 2026-11-08 assessment confirmed that the host kernel exposes no SELinux
LSM or SELinux policy interface. The profile inspector now reports the
diagnostic shim as `BYPASS_DETECTED` and cannot mark SELinux enforcement
verified from static image contents. `aaas setup`, `verify`, and `start` must
continue to fail closed for this profile until a policy-preserving runtime
architecture and fresh live security tests exist. The accepted M4 results
describe the controlled diagnostic configuration and do not certify it for
untrusted applications or distribution. The trust boundary and profile
promotion rules are recorded in the
[rootless Android security decision](security/rootless-android-architecture.md).
The installed Android 16 profile is explicitly `DIAGNOSTIC_LEGACY`; normal CLI
verification also rejects `RECONSTRUCTED_EXPERIMENTAL` profiles even if their
other metadata is set to passing values.

## Independent Android 16 base assembly

The CLI now exposes `aaas images build android16-ranchu-x86_64`. It constructs
a fresh, versioned rootfs candidate from the verified SDK r02 archive using
the portable workspace and profile configuration. The output is marked
`ASSEMBLED_INCOMPLETE`, is not an installation, and cannot be started. This
is a reproducible base extraction milestone, not a completed `aaas setup`
provisioner: APEX, graphics, security, Native Bridge, audio, and session helper
components remain unresolved. See the [rootfs reconstruction procedure](android-rootfs-reconstruction.md).
