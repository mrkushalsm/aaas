# Portable Android development bundle

**Current release state:** This guide describes installed-bundle operations;
it is not an assertion that a public bundle is currently available. The latest
candidate and its open acceptance gates are recorded in
[`release-readiness-2026-11-11.md`](release-readiness-2026-11-11.md).

This directory bundle is for local, trusted development use. It is not a
production-secure Android environment and has no signed release provenance.

## Install and operate

From the extracted bundle directory, verify and install into distinct
per-user paths. The bundle includes its own bootstrap installer, so a source
checkout is not needed:

```sh
./install --workspace "$HOME/.local/share/aaas/workspaces/android16" \
  --installation "$HOME/.local/share/aaas/installations/android16" \
  --config-home "$HOME/.config/aaas" \
  --data-home "$HOME/.local/share/aaas"
```

After installation, use the installed CLI to verify its copy and operate it:

```sh
"$HOME/.local/share/aaas/installations/android16/bin/aaas" bundle verify \
  "$HOME/.local/share/aaas/installations/android16"
```

The equivalent install operation is available from an existing AaaS CLI:

```sh
aaas bundle install /path/to/portable-development-bundle \
  --workspace "$HOME/.local/share/aaas/workspaces/android16" \
  --installation "$HOME/.local/share/aaas/installations/android16" \
  --config-home "$HOME/.config/aaas" \
  --data-home "$HOME/.local/share/aaas"
```

The installed CLI provides persistent runtime and application controls:

```sh
systemctl --user start aaas-runtime.service
systemctl --user status aaas-runtime.service
aaas apps list
aaas apps launch com.android.settings
aaas apps install /path/to/trusted.apk
aaas apps close SLOT
aaas runtime stop
```

Updates stage and verify a new bundle before activation. The prior immutable
runtime is retained for rollback; uninstall removes installed files and owned
desktop/service entries while preserving the workspace and Android userdata by
default:

```sh
aaas update /path/to/new-bundle
aaas rollback
aaas uninstall
```

Keep the workspace on persistent storage. Do not delete its `android-userdata`
directory to repair an install. Updates replace immutable runtime artifacts;
user configuration, installed APKs and userdata live separately.

## Local acceptance, 2026-11-10

Bundle ID `9d89316e70424a489000bd7344d75989` contains 6,980 manifest entries;
bundle integrity passed. Its installed runtime was exercised in a clean XDG
profile: Android booted, Settings, Contacts and Apotris opened as separate
Wayland windows, and a trusted APK remained installed after service restart.
An update to this bundle succeeded, Apotris launched afterward, rollback to
the previous bundle succeeded, and uninstall preserved the isolated workspace.
The full Python suite passed 530 tests. The matching runner artifact has SHA-256
`9d5215b66b32cad91b6e2f26108d7c68297f3da2cfa00004702afad10235aa21`.

This is local development evidence, not cross-distribution certification.
Nine-window multiwindow operation and M4 desktop bridges were accepted on the
existing runtime before this packaging pass; they were not all rerun against
the fresh profile in this acceptance.

## Current release limitations

- The newest bundle's integrity and 24-input runtime closure pass, but it has
  not completed fresh installed boot acceptance. Its update was automatically
  rolled back when the host's 10 GiB free-space reserve prevented startup.
- Runtime security is not approved: the diagnostic image includes SELinux
  authorization shims, enforcement is unavailable/unverified, and untrusted
  APKs are outside the supported trust model.
- Android rootfs and third-party artifact provenance/licensing are not cleared
  for public redistribution. The repository has no project-level license.
- A SurfaceFlinger crash occurred in one earlier pristine first-boot run; other
  first boots succeeded. Reliability is not established from the available
  sample.
- Gallery app-specific external-cache/project-quota behavior remains limited on
  the tested filesystem. Physical Android Wi-Fi and Bluetooth mediation are
  unsupported; Android internet access uses virtual Ethernet.
- The strict mount-isolated checkout-independence test was not completed because
  hiding the checkout prevented `newuidmap` from operating. Installed path
  checks and runtime dependency closure are evidence, but not equivalent to a
  full repository-absence test.

See [current release readiness](release-readiness-2026-11-11.md) and the
[dependency/licensing inventory](dependencies-and-licenses.md) before using or
distributing a candidate.
