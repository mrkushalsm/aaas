# AaaS artifact retention policy

## Retention set

Keep at most two engineering bundles in one bundle-output directory:

1. One known-good bundle used as the recovery baseline.
2. One current candidate under validation.

Keep the source repository, acceptance evidence, required Android inputs,
active installation/userdata, signing material, and protected build outputs
outside this two-bundle limit. A bundle's directory name or age alone is not a
reason to remove it. Verify its manifest identity, active service references,
open files, mounts, and evidence dependencies first.

## Build safeguards

`aaas bundle create` checks the output directory before copying payloads. It
refuses to create a third bundle, refuses to proceed when an incomplete
`.staging-*` directory exists, refuses to overwrite an existing output path,
and checks that the target filesystem will retain a 2 GiB free-space reserve
after the estimated bundle copy. The builder never deletes old bundles or
staging directories automatically; inspect and remove only a verified
disposable item, then retry.

The release workflow must keep multi-gigabyte archives outside the bundle
directory and record a checksum and bundle ID for each approved archive. Do
not create an archive when an identical archive is already retained. This
repository currently has no archive-generation command; packaging is therefore
an explicit release operation and must not be repeated as an unattended build
step.

## Storage-health rule

Do not delete or write release artifacts on an external filesystem while its
health gate reports an error or unknown state, or while kernel logs contain
device-correlated I/O errors. Do not run filesystem repair tools against a
mounted volume. Preserve uncertain artifacts until the filesystem is safely
unmounted and assessed. Active runtime dependencies and evidence remain
protected during that process.

## Verification

Run the focused policy tests with:

```sh
PYTHONPATH=scripts:tests python -m unittest -v test_aaas_bundle
```

The bundle builder tests cover the two-candidate limit, interrupted staging
refusal, and the free-space reserve check. No cleanup test removes host data.
