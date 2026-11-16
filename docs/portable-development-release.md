# Portable Android development bundle

**Current engineering candidate:** `engineering-af3dcb4`, bundle ID
`43d04579ec874746a7c9da5152419bd6`, built from source commit
`af3dcb4711d13197826942f0a1c7f2b1698589ec`. Its manifest SHA-256 is
`d638937b4bcb16f550b2e204175c70ec247190ca10b6e7229447560909db2a64`.
Host and Fedora acceptance passed for Android readiness, application
presentation, ARM64, network, audio transport, lifecycle, and isolated
uninstall. Portable developer-preview engineering acceptance is
**PASSED/CLOSED**. Fedora SELinux enforcing support, runtime security approval,
and binary redistribution clearance remain separate, deferred decisions. See
the [machine-readable acceptance record](release/portable-preview-af3dcb4-acceptance.json).

This page's dated acceptance sections below are historical records for their
respective candidates. The current exact-candidate tests are summarized in the
acceptance record above. In particular, the earlier update/rollback success
belongs to its named earlier candidate; cross-version migration is not claimed
as an `af3dcb4` acceptance gate.

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

The installed CLI provides persistent runtime and application controls. The
current command names are `aaas runtime start/status/stop` and top-level
`aaas restart`; application control is through `aaas apps`:

```sh
systemctl --user start aaas-runtime.service
systemctl --user status aaas-runtime.service
aaas apps list
aaas apps launch com.android.settings
aaas apps install /path/to/trusted.apk
aaas apps close SLOT
aaas runtime stop
aaas restart
```

The CLI exposes update and rollback commands. They stage/restore the installed
release family, but cross-version migration was not part of the exact-candidate
`af3dcb4` acceptance record. Uninstall removes installed files and owned
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

## Historical release limitations — 2026-11-11

The following findings describe the then-current candidate and are retained as
historical evidence, not as the state of `engineering-af3dcb4`.

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

The licensing finding above reflects the state on 2026-11-11. On 2026-11-16
the owner authorized Apache-2.0 for eligible original AaaS source code and the
root [LICENSE](../LICENSE) was added. This does not clear third-party source,
historical privacy concerns, or the Android image/bundle for redistribution.

## Earlier cross-distribution packaging follow-up — 2026-11-16

This section records the state before `engineering-af3dcb4` was built; it is
superseded by the exact-candidate acceptance record below.

The isolated `engineering-b736090` candidate remains the last packaged
candidate. Its Fedora functional testing used a temporary compatibility
overlay; Fedora SELinux was set permissive only inside the disposable VM and
restored to enforcing afterward. Fedora enforcing-mode compatibility is not
claimed. The user confirmed hearing the Android audio probe through QEMU's
PipeWire output.

The source now resolves Bubblewrap from system executable directories and
validates the binary rather than invoking whichever `bwrap` appears first on
`PATH`. A user-local diagnostic tracing wrapper remains available only through
the explicit `AAAS_BWRAP_TRACE_WRAPPER` setting. Focused regression tests cover
PATH hijacking, explicit binary validation, and opt-in tracing. This source fix
has not been packaged into a new candidate.

After the source change, the full Python suite ran **569 tests: 563 passed and
6 skipped**. The documentation link check covered 99 Markdown/license-named
files and 355 local references with no broken links. Machine-readable results,
including the failed bounded Fedora startup attempt and the earlier audible
Fedora probe, are in
[`bubblewrap-path-2026-11-16.json`](../results/release/bubblewrap-path-2026-11-16.json).

The latest root filesystem measurement showed 19,411,955,712 bytes available,
2,062,880,768 bytes below the configured 20 GiB reserve. The existing bundle's
rootfs and workspace payload alone occupy 3,525,828,608 allocated bytes. A full
copy candidate and isolated host installation cannot be created without
further consuming reserved capacity, so no final bundle was built and no
reserve was bypassed. Cross-distribution acceptance of a single final bundle
remained open at that point.

## Lifecycle-corrected candidate acceptance — 2026-11-16

The immutable `engineering-af3dcb4` bundle contains the process ownership fix
from `af3dcb4`: `slirp4netns` now remains in the AaaS runtime process group,
and shutdown waits for that owned group to empty before reporting completion.
The full Python suite passed **574 tests with 6 skipped**. Bundle integrity
passed for 8,795 artifacts and runtime dependency closure passed for 26
declared inputs. The manifest SHA-256 is recorded above.

On the original host, a fresh isolated install reached Android `RUNNING`;
Settings, Contacts, the network probe, the audio probe, and the ARM64 JNI
fixture opened. Presenter counters balanced imports, submissions, and releases
with zero outstanding ownership and nonzero presented frames. Android reported
DNS resolution and HTTPS 204 over TLS 1.3. The audio bridge delivered PCM
through PipeWire. Berberis logged the deterministic `M3 ARM64 Native Bridge
PASS mask=255` result. Normal persistent-runtime stop, a subsequent start/stop,
and supported isolated uninstall completed; workspace/userdata were preserved.

On Fedora 45/KWin 6.8.2, the same bundle installed and reached `RUNNING`.
Settings/Contacts and the ARM64, networking, and audio probes launched. The
ARM64 fixture emitted its deterministic pass signature; networking returned
HTTPS 204 over TLS 1.3; the PipeWire bridge closed after receiving PCM. The
initial presentation attempt recorded 105 submitted/released buffers and zero
presented frames. Its evidence showed the Fedora desktop session was locked:
KWin reported the AaaS toplevel as `suspended=true` and discarded all frame
feedback; the black full-desktop screenshot showed the locked display. This was
a VM test-session state, not a candidate graphics regression. The controlled
reproduction unlocked the session and held it awake for the test. Settings and
Contacts then appeared on the live Fedora desktop, and their presenter logs
recorded 43 submitted, 43 presented, and 43 released frames, zero discards, and
zero outstanding ownership. See the awake desktop and app-window screenshots
and the `virtual-presenter-awake-reproduction.log` and
`virtual-presenter2-awake-reproduction.log` files in the Fedora acceptance
evidence directory.

The isolated Fedora uninstaller then removed the candidate installation and
its owned service while preserving the workspace and Android userdata. The
VM's SELinux mode was restored to Enforcing after testing. The permissive mode
used during AaaS runtime acceptance is a temporary developer-VM requirement;
it is not Fedora enforcing compatibility or a safe general-user default.

An opt-in `AAAS_KEYSTORE_TRACE=1` diagnostic run exceeded the disposable
systemd service's stop timeout under tracing load. The temporary setting was
removed, and the following untraced service cycle stopped cleanly. This traced
run is recorded as a diagnostic limitation; it is not counted as a passing
shutdown. Fedora SELinux enforcing support, runtime security approval, and
binary redistribution clearance remain deferred.

Detailed machine results: [`portable-preview-af3dcb4-acceptance.json`](release/portable-preview-af3dcb4-acceptance.json). Portable preview engineering gates are closed for this exact candidate. SELinux enforcing support, security approval, and public binary redistribution remain deferred and are not implied by functional acceptance.
