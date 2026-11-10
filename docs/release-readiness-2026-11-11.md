# AaaS local release readiness — 2026-11-11

This report covers the latest locally built bundle and a disposable update/
rollback run. Source commit `cc2dffbffc22c720d231e760c99d472a5f325242` adds an
uninstall cleanup fix after the bundle build; the bundle does not include that
fix. An update is not equivalent to a clean fresh install.

## Release identity

- Bundle source revision: `7226838e908e071d971d37e5a9989f111c72d47d`.
- Runtime source revision tested: `cc2dffbffc22c720d231e760c99d472a5f325242` (uninstall-only runtime fix after bundle build; subsequent commit is documentation/evidence only).
- Bundle: `engineering-7226838`, ID `fd386b95a7a949de9da3bb18c88e5c64`.
- Bundle location: `$XDG_DATA_HOME/aaas-release-artifacts/engineering-7226838`.
- Manifest SHA-256: `1d743363858b5836f7364d7d6b67c22cfb190c4eda10dfa6b58e0805f774faa2`.
- Integrity: **PASS**, 6,999 manifest entries.
- Runtime closure: **PASS**, 24 inputs checked, no missing inputs.
- Candidate metadata records `source_tree_dirty_at_capture=true`; this bundle is tied to the commit but was assembled while documentation changes were uncommitted.

## Capacity override used for disposable update/rollback

The host had 6,088,290,304 bytes free before the update and the staged update
needed about 3,491,054,905 bytes. At the user's explicit one-time direction,
only the disposable `aaas-m5-final-test.service` and its CLI invocation received
`AAAS_ROOT_FREE_RESERVE_GIB=1`. The original `aaas-runtime.service` and global
systemd environment were not changed. The override drop-in was removed and
`systemd --user daemon-reload` completed after rollback. No reserve guard or
security check was changed in source. The candidate test service was then
stopped; the 10 GiB workspace marker remains intact.

## Exact-candidate update and rollback

- Starting installation C used previous bundle `52926e6cb5e54766918af1a4dd7b0ec7` and a separate userdata/workspace.
- Supported `aaas update` to `fd386b95a7a949de9da3bb18c88e5c64` completed, reinstalled the user service, and reported Android runtime `RUNNING`.
- Android catalog had 15 applications after update, including Apotris, VLC, Audio Probe, and Network Probe; these also remained present after rollback.
- After update, Apotris launched on display 3 and reported `RUNNING`; presenter log contained 1,109 `frame_presented` events in that session at the check. VLC launched on display 7 and the presenter log count reached 671. VLC's Android ARM translation library load was directly established on the prior candidate in earlier evidence; this pass confirms VLC app/window execution on this candidate, but does not independently recapture the `libvlcjni.so` load.
- Network Probe was launched from Android. Its live app view reported `network=100`, `INTERNET=true`, `VALIDATED=true`, `iface=eth0`, DNS `10.0.2.3`, default gateway `10.0.2.2`, successful lookup `142.251.150.120`, HTTPS 204, and TLS 1.3 (`TLS_AES_128_GCM_SHA256`). Screenshot: [`installed candidate network result`](release/network-probe-engineering-fd386b95.png), SHA-256 `9f009184a50bda9210c81b1af06f30fe5041e5ed948988caa03ebb126a37e040`. Optional MediaStore export reported an `InvocationTargetException`; the visible app result passed.
- Android Audio Probe launched from this candidate. The AaaS bridge opened and closed a 48 kHz stereo S16 playback stream with 2,223,360 bytes. A 12-second independent PipeWire Headphones monitor capture recorded 4,521,984 raw S32 bytes / 1,130,496 samples, 372,284 nonzero samples, peak 4,653,056 (about 71 in S16-equivalent units), RMS 1,716,638 (about 26.2 S16-equivalent over signal plus silence), no clipping, SHA-256 `6260bf8c8772dd7ecb93e7867036f8e305f91d7ba1b10b2b2588c3388eccf63b`. The Android stream was released. This is objective transport evidence; no new human listening confirmation was requested for this candidate. Historical audible-and-clear confirmation is in `results/audio/human-listening-2026-11-10.json`.
- Supported `aaas rollback` restored `52926e6cb5e54766918af1a4dd7b0ec7`, restarted Android to `RUNNING`, retained the failed/new generation separately, and launched Settings on display 3. Its presenter log contained 151 `frame_presented` events at the check.
- The candidate test installation was then uninstalled with userdata preservation. The workspace/userdata markers were unchanged, but uninstall restored the test profile's own backup unit; the now-stale unit was manually removed after ownership checks. The current source fix prevents restoring that same-profile unit, with a regression test for preserving a different profile's unit. This fix is not included in bundle `fd386b95`.
- The original installation and userdata were not modified.

Update and rollback are **PASS for this isolated lifecycle**, with a temporary explicit 1 GiB root reserve for the test only. Live uninstall is **FAIL on the bundle as built; source fix verified by tests but not yet rebuilt/retested**. The normal 10 GiB capacity check remains in place outside the temporary candidate service override.

## Fresh installation and reliability

- A pristine first-boot test of this exact new bundle was **NOT RUN**; the earlier pristine C test belongs to bundle `52926e6cb5e54766918af1a4dd7b0ec7`.
- An earlier failed update attempt to this bundle was automatically rolled back when the normal 10 GiB free-space reserve rejected startup. That failure and rollback state were preserved. The later authorized, narrowly scoped acceptance run above completed update and rollback.
- Historical installation B had an intermittent SurfaceFlinger first-boot crash; other pristine runs succeeded. Reliability across multiple fresh installations remains unestablished.
- Five start/readiness/Apotris frame/close/stop cycles were completed against the previous bundle after temporarily applying the committed desktop launcher fix. They are not five-cycle acceptance of `fd386b95a7a949de9da3bb18c88e5c64`. Evidence remains local at `[lifecycle-cycle record](release/lifecycle-five-cycles-2026-11-11.json)`.
- The exact candidate was started once by update and stopped after rollback validation. A five-cycle run against it is not complete.

## Automated tests and documentation

- `python3 -m unittest discover -s tests -q`: 549 passed, zero failures/errors (15.732 s) on runtime source revision `cc2dffb`. The focused CLI suite passed 21 tests, including two uninstall-backup regressions.
- Focused desktop tests: 18 passed. Previously built native regression binaries: 17 passed; no native code changed in this pass.
- Documentation audit: 89 Markdown/license-named files inventoried, all read/hashed, local links checked; zero broken local links. The audit distinguishes current operational docs reviewed against the implementation from historical records whose old experiments were not rerun.
- Audit inventory: [`documentation audit`](release/documentation-audit-2026-11-11.json).
- Bundle SBOM/path inventory: [`SBOM`](release/sbom-engineering-fd386b95.json).

## Security and redistribution

The bundle is diagnostic-only and has runtime security `NOT_APPROVED`: it
contains SELinux authorization shims, Android enforcement is unverified, and
untrusted APKs are unsupported. Publisher authenticity is not established.
The SBOM records `NOASSERTION`/`NOT_CLEARED` where source or license evidence is
absent. There is no project-level license file. **Public source and binary
publication remain blocked** until licensing/provenance and security issues
are resolved. A checksum establishes byte integrity, not rights or publisher
identity.

## Decision

**AAAS NOT YET READY.** Update/rollback, live audio transport, Android
application networking, and app windows passed on the exact candidate in an
isolated profile. The live uninstall exposed a defect fixed in source but not
rebuilt into the candidate. Fresh installation, five lifecycle cycles against
this exact bundle, direct ARM library-load evidence on this exact bundle,
production security approval, and public redistribution clearance remain open.
The one-time capacity exception has been used and removed. At this final check,
the root filesystem had 12,690,132,992 bytes free and the external workspace
had 3,342,888,960 bytes free. These amounts do not establish enough space for a
complete staged candidate rebuild/update while preserving the configured
reserve. The original service was explicitly restarted after disposable-test
teardown and the installed CLI reports Android `RUNNING`; the disposable test
unit is absent and its temporary override is removed.
