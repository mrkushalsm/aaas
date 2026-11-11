# ext4 workspace controlled recovery — 2026-11-08

## Decision

The UUID-scoped `DEVICE_FAILURE_SUSPECTED` incident remains in the policy
history. Its recovery evidence permits **`HEALTHY_FOR_CONTROLLED_TESTING`** for
the ext4 workspace UUID `$AAAS_WORKSPACE_UUID`. This is a
bounded testing classification, not a declaration that the SSD or USB path is
fault-free. Any new device-correlated I/O, UAS, USB, JBD2, or ext4 error after
the recovery checkpoint returns the workspace to quarantine.

## Offline filesystem check

The user ran the following with the filesystem unmounted:

```text
sudo e2fsck -fn /dev/disk/by-uuid/$AAAS_WORKSPACE_UUID
e2fsck 1.47.4 (6-Mar-2025)
Pass 1: Checking inodes, blocks, and sizes
Pass 2: Checking directory structure
Pass 3: Checking directory connectivity
Pass 4: Checking reference counts
Pass 5: Checking group summary information
Aaas: 507709/8003584 files (0.2% non-contiguous), 20221919/32000000 blocks
```

All five passes completed without an inconsistency report. `-n` was used, so
this did not repair or write filesystem metadata. The terminal output did not
include the exact command completion time; it was reported on 2026-11-08 and
is recorded at evidence capture time below.

## Device evidence and limitation

The user supplied passive SMART output for parent device
`$WORKSPACE_DEVICE_SERIAL`, captured at 2026-11-07 19:27:51 IST. Overall
SMART self-assessment was `PASSED`; reallocated, pending, offline-uncorrectable,
reported-uncorrectable, and end-to-end error counts were zero. Interface history
was nonzero: UDMA CRC count 717, SATA PHY ICRC 3, data FIS R_ERR 3, and COMRESET
41. This snapshot predates the later UAS and block-I/O events. It is evidence
against known media-error counters at that time, not a fresh post-incident
device test. No SMART test or scan was run. The AaaS process could not repeat
the privileged SMART query, so the user-provided report is retained with this
limitation.

## Post-check observation

At evidence capture, the workspace was mounted from `$AAAS_WORKSPACE_DEVICE` as ext4 with
UUID `$AAAS_WORKSPACE_UUID`, mount ID `246`, and options
`rw,nosuid,nodev,relatime,errors=remount-ro`. Parent identity resolved to model
`local USB SSD`, ATA serial `REDACTED_LOCAL_SERIAL` (`udev ID_SERIAL`
`$WORKSPACE_DEVICE_SERIAL`). The workspace marker and persistent
userdata manifest parsed and matched the workspace UUID/path; the userdata
backing directory was present. `df` reported 75 GiB used, 39 GiB available on a
120 GiB filesystem, satisfying the 20 GiB reserve and 80 GiB workspace ceiling.

The current-boot filtered journal contained the previously recorded UAS
aborts, block read errors, and 23:08:11 ext4 journal write failure. All are
before this offline-check/recovery report. A bounded query from 2026-11-08
01:20:00 through 01:20:46 IST found no matching storage errors. This is a
short post-check window; runtime health monitoring must continue during any
controlled session.

## Guard transition

The original incident fields and `DEVICE_FAILURE_SUSPECTED` source state are
preserved. The generic recovery attestation records the offline e2fsck result,
the SMART evidence and its interface-history limitation, and the post-check
mount/journal/manifest observations. The guard validates the evidence hashes,
UUID, device serial, boot ID, and mount ID. It evaluates only journal events
after the recovery checkpoint for renewed quarantine, so old incident messages
remain visible without blocking forever.

No Android session was started as part of this recovery transition.
