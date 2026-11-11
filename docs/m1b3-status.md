# M1B.3: secure ServiceManager and APEX activation boundary

**Determination: fail.** No development ServiceManager binary was built and no
APEX package was activated. G1–G7 retain the M1B.2 failure status. The
diagnostic rootfs and SELinux preload shim remain excluded from the milestone
path.

## Source and authorization boundary

The SDK image identifies itself as
`BE2A.250530.026.D1/13818094:userdebug/test-keys`. Google's public Android
build-number table does not map that ID to an AOSP release tag. The current
`frameworks/native` checkout is immutable commit
`fcbde2bcff56ca1d7bec9cabf8bdca5e288bf103` on
`android16-qpr2-release`; `android-16.0.0_r1` is a distinct commit
(`f31cdb78a72bc3f1d62e2371f20fb4f06e9748f1`). Neither has been proved
to match the SDK binary. A source patch or platform-linked replacement built
from either would have unverified ABI and security behavior. The exact image
source revision remains unresolved, so no ServiceManager replacement was
installed.

The inspected QPR2 `Access.cpp` unconditionally initializes SELinux on Android
and derives the caller UID and PID from `IPCThreadState`. It uses the Binder
SID when available and `getpidcon(pid)` as a fallback, then checks `add`,
`find`, and `list` through SELinux service contexts. `ServiceManager.cpp`
routes registration, lookup, enumeration, notifications, and accessor methods
through these checks; service replacement also compares Binder caller PID.
A future development backend must replace this authorization boundary only in
an explicitly selected build, fail closed on bad policy, and obtain UID/PID
from Binder rather than transaction payload. Android UID mapping inside a user
namespace must be measured before assigning allowlist identities. This
backend would provide limited experiment authorization, not Android MAC.

The stock ServiceManager control still aborts at `selinux_status_open` as
recorded in M1B.2. There is no real Binder allow/deny, death, or restart
evidence for a patched binary. G2 therefore remains failed.

## APEX metadata audit

`scripts/audit_m1b3_apex.py` inspects package archives in the retained
diagnostic rootfs without modifying them. It decodes the upstream AOSP
`ApexManifest` protobuf fields for name, version, native library provisions
and requirements, no-code and bootstrap flags; for CAPEX it checks the nested
`original_apex` identity. The script compares package identity to
`apex-info-list.xml` and any staged payload manifest. Its retained report is
`$AAAS_WORKSPACE/logs/m1b3-apex-inventory.json`.

The 47 declared modules have matching package names and versions and no
parser errors. Thirty-five have staged payload manifests; zero are marked
active. The inventory has 228 native-library requirements, many satisfied by
system libraries rather than another APEX. A blank `apex_providers` entry is
therefore *not* proof of a missing dependency. Metadata inspection does not
verify package signatures, payload hashes, ownership, labels, mount options,
versioned mount paths, linker namespace consistency, or `apexd` callbacks.
The diagnostic rootfs itself contains known modifications and is not an
authenticated source image. Its APEX claims cannot be promoted into trusted
activation evidence.

The retained `apexd.real` run attempted 47 activations and failed to open
`/dev/loop-control` inside its container. A host user namespace probe saw a
host loop-control node, but that does not grant safe loop setup or prove it is
available inside the isolated Android device view. A faithful activation
experiment requires a verified package source, isolated mount/device view,
documented loop or alternative payload mount capability, active-version
selection, and linkerconfig validation. No new mount or host device change was
made for this audit.

## Init and framework boundary

The transient cgroup v2 delegation probe from M1B.2 remains valid for CPU,
memory, and PIDs. Android task profiles still reference unsupported legacy
paths. Without an authorized ServiceManager and authenticated APEX activation
environment, starting init, Zygote, or system_server through the modified
diagnostic rootfs would not meet the required security/readiness gates. No new
framework boot was attempted. G1–G7 remain failed; no APK was run.

## Reproduction

```sh
export AAAS_WORKSPACE=$AAAS_WORKSPACE
python3 scripts/android_workspace.py --workspace "$AAAS_WORKSPACE" check
python3 scripts/audit_m1b3_apex.py \
  --rootfs "$AAAS_WORKSPACE/rootfs_m1b1" \
  --output "$AAAS_WORKSPACE/logs/m1b3-apex-inventory.json"
python3 -m unittest discover -s tests -v
```

The audit returned 0 with 47 metadata records and zero consistency errors;
the test suite passed 55 tests. No Android build, package install, source
checkout mutation, or host security change occurred. The first next
experiment is to identify a source graph matching the SDK image (or build a
new minimal image and ServiceManager coherently from one source graph), then
implement a narrowly scoped development `Access` backend and test its real
Binder authorization. Only after that should APEX activation and framework
startup be retried.
