# Rootless Android security architecture decision

**Status:** accepted for the current host architecture; Android execution remains
blocked until a safe runtime profile is implemented and validated.

**Date:** 2026-11-08

## Decision

AaaS keeps the on-demand, shared-kernel, rootless container architecture. It will
not claim Android SELinux enforcement unless Android init has loaded the selected
policy into a kernel with the SELinux LSM enabled and live positive and negative
policy tests pass. The current host exposes `capability,landlock,lockdown,yama,bpf`
and has no SELinux policy load/enforce interface. The Android container shares
that kernel, so it cannot independently enable SELinux or load a private Android
policy. Changing host kernel configuration, boot parameters, or global LSM policy
is outside this decision.

The existing `android16-ranchu-x86_64` profile is classified
`DIAGNOSTIC_LEGACY`. It contains known SELinux-success and Binder-flag shims and
is not eligible for portable provisioning, `aaas verify`, or production
`aaas start`. Static image inspection cannot promote a profile. The classes
`RECONSTRUCTED_EXPERIMENTAL`, `SECURITY_VALIDATED`, and `DISTRIBUTABLE` are
evidence labels, not user-selectable security modes. Promotion requires the
corresponding independent evidence and explicit profile metadata changes.

No separate experimental launch command is introduced. An experimental label
alone does not establish a safe containment boundary, and the current repository
does not yet prove that the diagnostic runtime can operate without bypassing
SELinux checks. The production launcher therefore remains fail-closed. Do not
install or execute untrusted APKs in the diagnostic environment.

## Trust boundaries and guarantees

| Boundary | Available mechanism | Current guarantee |
|---|---|---|
| Host versus Android processes | User, mount, PID, and network namespaces; read-only base mounts; explicit bind mounts; seccomp/Landlock/cgroups where individually detected and enabled | Useful containment layers only; the aggregate host-isolation profile has not passed a fresh adversarial test campaign. |
| Android application identity | Android UID assignment and filesystem DAC, assuming distinct UIDs are preserved through the user namespace | Not independently validated on a reconstructed image. |
| Android runtime permissions | PermissionController, PackageManager, and AppOps | Accepted on the historical M4 diagnostic configuration; does not replace kernel MAC. |
| Android SELinux | Kernel SELinux LSM plus loaded Android policy and correct labels | Unavailable on the current host; no enforcement claim. |
| Distribution/untrusted APK use | Complete provenance, policy enforcement or separately validated equivalent architecture, app isolation tests, and licensing review | Not approved. |

Namespaces, seccomp, Landlock, DAC, Android runtime permissions, and Binder
service checks are complementary controls; none is represented as equivalent to
Android SELinux. Android framework permission tests from M4 remain historical
feature evidence and are not a security validation of this diagnostic image.

## Alternatives considered

1. **Rootless shared-kernel runtime with limited, explicit guarantees — selected
   as the architecture direction, not yet an executable profile.** It preserves
   AaaS's current lifecycle and avoids host-global changes. The implementation
   must be proven to boot without authorization-success shims and must fail
   closed when a required Android security check cannot be honored.
2. **Host-kernel SELinux — not performed.** A host SELinux LSM does not by itself
   prove that Android init can load and enforce the Android policy in a shared
   kernel already governed by the host's LSM/policy. Kernel and policy changes
   require an independently designed and tested host integration.
3. **Established container Android implementations — reference only.** Projects
   such as Waydroid demonstrate containerized Android deployment patterns, but
   their existence does not establish Android SELinux equivalence or validate
   this AaaS image. No upstream rootfs or security claim is adopted by analogy.
4. **Isolated guest — contingency only.** A separate kernel could provide a
   distinct SELinux policy domain, but introducing a VM changes the approved
   lightweight architecture and is not implemented or authorized here.

## Activation and failure policy

- A profile classified `DIAGNOSTIC_LEGACY` cannot be provisioned or started by
  the normal production CLI.
- No SELinux, Binder, or policy API may be stubbed to return success.
- No absent kernel LSM may be inferred from image properties or `getenforce`
  output alone.
- Any missing policy load, unexpected denial, authorization shim, or unverified
  containment condition blocks profile activation.
- Only a separately validated profile may claim experimental host containment;
  that classification still does not authorize untrusted APKs or distribution.

## References

- [AOSP SELinux implementation](https://source.android.com/docs/security/features/selinux/implement)
- [AOSP SELinux validation](https://source.android.com/docs/security/features/selinux/validate)
- [Linux Security Module usage](https://www.kernel.org/doc/html/latest/admin-guide/LSM/index.html)
- [Waydroid project](https://github.com/waydroid/waydroid) (implementation reference, not a security-equivalence claim)

