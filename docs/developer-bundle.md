# Local M4 developer bundle

The bundle commands package the existing `rootfs_m1b1` diagnostic installation
for local relocation. This is a preservation/relocation workflow, not Android
image reconstruction and not a supported release artifact.

## Trust and status

The bundle manifest separates:

- `installation_integrity`: hashes and required filesystem entries match.
- `runtime_closure`: whether all runtime inputs are present.
- `runtime_security`: whether the Android workload is approved.

For the historical M4 image, installation integrity can pass while runtime
closure remains partial and runtime security remains `NOT_APPROVED`. The image
contains known SELinux authorization-success shims, its APEX/security behavior
is not approved for untrusted APKs, and its unsigned local bundle has no
authenticity guarantee. Neither bundle installation nor a successful hash
check changes the production `aaas verify` / `aaas start` gate. No normal CLI
startup exception is provided.

## Create, inspect, verify, install

From a checkout with the existing M4 workspace selected:

```sh
./aaas bundle create --profile android16-ranchu-x86_64 \
  --local-development --output "$AAAS_WORKSPACE/bundles/android16-local-dev"
./aaas bundle inspect "$AAAS_WORKSPACE/bundles/android16-local-dev"
./aaas bundle verify "$AAAS_WORKSPACE/bundles/android16-local-dev"
./aaas bundle install "$AAAS_WORKSPACE/bundles/android16-local-dev" \
  --workspace "$HOME/.local/share/aaas/workspaces/android16-local-dev" \
  --installation "$HOME/.local/share/aaas/installations/android16-local-dev" \
  --config-home "$HOME/.config/aaas-local-dev" \
  --data-home "$HOME/.local/share/aaas-local-dev"
```

Creation is restricted to the selected `rootfs_m1b1` and requires a stopped
AaaS session plus a passing enrolled-workspace check. It copies Android system,
system_ext, product, vendor and APEX contents, selected runtime code, and 145
retained generated workspace inputs. Android userdata, mutable `/data`, caches,
session logs, host credentials, signing keystores, and unrelated test captures
are excluded. The source diagnostic rootfs is read-only and is never modified.

The format is a directory with a versioned `manifest.json`. Every file has a
SHA-256, size and mode; symlink targets and directories are recorded. Bundle
verification detects missing, modified, extra, or mode-changed entries. This
unsigned local manifest detects accidental changes but does not authenticate
the bundle against a malicious replacement. The installer verifies the
manifest before and after copying, checks xattrs, numeric ACLs, SQLite, hard and
symbolic links, atomic rename, and enforces the configured 20 GiB free-space
reserve. It refuses existing installation/config paths and nonempty workspaces.

After installation, the copied command is available at:

```sh
"$HOME/.local/share/aaas/installations/android16-local-dev/bin/aaas" status
```

The install records its new workspace and rootfs paths in its XDG config and
installation manifest. `aaas bundle verify <installation-path>` verifies the
installed copy. `status` works without starting Android. The regular runtime
`verify` and `start` remain fail-closed; a bundle is not a runnable or secure
Android installation merely because its files verify.

## Known runtime closure gaps

The bundle stages the generated overlays, native bridge files, audio HAL
outputs, Android helper APKs, APK tools, and system partition used by the
current audio preparation step. The production runner still rebuilds helper
APKs and audio overlays during startup. It expects a private storage-scan
signing keystore; that keystore is intentionally excluded. A clean
per-installation signing/provisioning flow has not been implemented. Host
Wayland, PipeWire, Binder, DRM, namespace, and cgroup capabilities remain
host-discovered. The bundle is therefore currently `runtime_closure: PARTIAL`.

The copy preserves file content, modes and symlinks. Android SELinux labels
are not portable host xattrs, hardlink relationships are not guaranteed, and
ownership is represented by the installing host user for the namespace's UID
map. Licensing review for redistribution has not been performed. Do not upload
or publish this local bundle.

## Portability evidence

Automated tests create and relocate synthetic bundles, detect tampering, install
two instances under different config/data/workspace roots, and verify that
runtime security remains blocked. A real local installation uses a separate
XDG config/data root, workspace and installation path. The bundle and installed
copy each verified 6,946 entries for bundle ID
`e7efd621aeeb4297a36a770d57eadf22`. The installed workspace has staged bundle
inputs but is not enrolled: `aaas setup` refused to adopt the nonempty directory
without the explicit adoption option, and no workspace marker was created. The
installed `aaas start` exited 2 before launching a session because the known
SELinux bypass was detected, enforcement is unverified, the workspace is
unenrolled, and runtime closure is partial. Status remained `STOPPED`. This
confirms relocation and integrity, not Android boot. M4's historical live
acceptance remains evidence for the original diagnostic installation only.
The tests and observed statuses are recorded in
[local bundle acceptance](../results/m6/local-bundle-acceptance-2026-11-08.json).
