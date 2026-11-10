# Portable Android development bundle

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
aaas apps close INSTANCE_ID
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

## Known limitations

- The bundle manifest reports runtime closure `PARTIAL`: helper APK/audio
  overlay rebuild inputs and a clean per-install signing flow are incomplete.
- Gallery app-specific external cache remains unavailable on the tested ext4
  backing filesystem because Android project-quota support is not configured.
  AaaS logs the emulated-storage limitation and keeps the Android runtime alive;
  this does not establish Gallery or full shared-storage compatibility.
- A strict test that hides the checkout from the systemd service could not
  complete: with `InaccessiblePaths` enabled, the host rejected `newuidmap`
  (`Operation not permitted`) during AaaS's rootless workspace accounting.
  The service's executable and runtime modules resolve from the installed
  bundle, but the mount-isolated source-independence gate remains unverified.
- Android SELinux enforcement and production security approval remain separate
  workstreams. Run only trusted APKs in this development profile.
