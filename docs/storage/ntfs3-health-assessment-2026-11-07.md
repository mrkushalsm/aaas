# NTFS3 workspace health assessment — 2026-11-07

## Classification

**`DEVICE_FAILURE_SUSPECTED`; workspace-backed Android activity is blocked.**
This is a quarantine decision, not a finding that the SSD itself has failed.
The kernel recorded read I/O errors and UAS recovery on the same USB storage
device as four NTFS3 attribute-enumeration errors. The underlying media versus
USB bridge/cable/transport cause is not established. Passive SMART data could
not be read by the current unprivileged process.

No Android runtime was started for this investigation. No repair, unmount,
remount, filesystem write, userdata mutation, or workspace-backed test occurred.

## Correlated evidence

The current mount is `/dev/sda2` at `/run/media/mrkus/Homework`, filesystem
`ntfs3`, UUID `A2ACEDF2ACEDC0C1`. The parent device is the USB-attached
`CT500BX500SSD1`, serial `2421E8B20AE0`, reached through UAS at USB 2-3. The
kernel reports Linux `7.2.9-arch1-1`; the NTFS3 module vermagic matches that
kernel. `lsblk` reports `ROTA=1` despite the SSD model, so that field is not
treated as evidence of a rotating disk.

All four `mi_enum_attr` messages have kernel priority 3 (error), source
`ntfs3(sda2)`, and boot ID `70f8e0d326cf4da08dbd862256b1391a`. Journal JSON
preserves both realtime and monotonic timestamps:

| Realtime (+05:30) | Monotonic | MFT inode | Name |
|---|---:|---:|---|
| 2026-11-06 03:39:38.919288 | 21,118,900,187 µs | `1a472` | `install_sessions.xml.new` |
| 2026-11-06 23:18:06.309832 | 81,853,248,116 µs | `447ca` | `install_sessions.xml.new` |
| 2026-11-07 01:14:25.179917 | 88,832,118,201 µs | `50414` | `install_sessions.xml.new` |
| 2026-11-07 03:12:11.994839 | 95,898,933,123 µs | `cb85d` | `install_sessions.xml.new` |

The distinct MFT record numbers and repeated basename are consistent with
repeated temporary-file creation/replacement; they do not prove that the same
record was persistently damaged. The likely Android path is
`/data/system/install_sessions.xml.new`, which maps to
`android-userdata/data/system/install_sessions.xml.new`; the basename alone
does not establish the owning process. A single bounded `lstat` of that
expected backing path returned `ENOENT`; the parent `data/system` directory
was readable. The named temporary file is therefore absent now. No XML content
was read, and no broader userdata traversal was performed.

The same kernel boot also recorded UAS command aborts and successful USB host
resets at 2026-11-05 23:50:06–08 and 2026-11-06 02:20:44–02:21:14 (+05:30). At
02:21:14 it reported block read I/O errors on `/dev/sda` at sectors
`632982552` and `18969152`. These messages establish storage-path read errors;
they do not distinguish SSD media, enclosure, cable, power, or host-controller
fault. No additional block I/O errors were found in the bounded filtered
review. The four later NTFS3 reports are on the same partition.

## NTFS3 source interpretation

In upstream Linux v7.2 `fs/ntfs3/record.c`, `mi_enum_attr()` validates MFT
record bounds, attribute ordering/alignment, resident and nonresident sizes,
and allocation extents. On invariant failure it calls `_ntfs_bad_inode()` and
returns no attribute. That is consistent with an invalid record view; the log
does not tell whether the bytes on disk are persistently malformed or whether
the in-memory view was inconsistent.

A particularly relevant upstream patch posted 2026-10-30 describes a race in
`ni_write_parents()` during fsync: it walks attributes without `ni_lock` while
another operation can rearrange a record. The patch says this can make
`mi_enum_attr()` mark a healthy inode bad and the volume dirty, and its
reproducer uses concurrent write/sync operations. This is a strong candidate
for the message shape, not a proven cause here. The installed kernel was built
2026-10-03, before that patch was posted; the exact Arch source commit and
backport set were unavailable locally. The separate UAS and block read errors
also prevent attributing this incident solely to that race.

References: [Linux v7.2 NTFS3 record.c](https://github.com/torvalds/linux/blob/v7.2/fs/ntfs3/record.c), [upstream `ni_lock` race patch](https://lists.openwall.net/linux-kernel/2026/10/30/11).

## Device-health limits and data preservation

`smartctl -x -n standby /dev/sda` was attempted without initiating a test; it
failed with `Permission denied`. Noninteractive sudo required a password, so
no privileged device query was attempted. NVMe tooling was not installed, and
the device is exposed through USB/SCSI rather than a direct NVMe node. SMART
health, media-error counters, and SSD wear are therefore **unknown**, not
healthy. No self-test, surface scan, reset, or firmware operation ran.

The volume contains the persistent Android `/data` backing, Android shared
media, workspace artifacts, and project/test data. No verified independent
backup of this complete volume was found in the repository records. No backup
was created because no healthy destination and capacity were authorized or
established. Avoid further writes and broad reads. Before any repair, identify
a healthy destination with at least the used-data capacity (preferably a full
sector image target of at least the device's 500 GB nominal capacity), capture
passive device health with authorized access, and prioritize a verified image
or copies of irreplaceable workspace data and Android userdata. Verify copied
files by size and hashes. Do not assume unreadable or damaged files are
recoverable.

## Guard changes

`scripts/android_workspace.py check` and the runtime monitor now consult a
tracked UUID-scoped pause policy before capacity traversal. For NTFS3, missing
health evidence is `HEALTH_UNKNOWN` and blocks. Current-boot device-matched
NTFS3 errors classify `INTEGRITY_WARNING`; the committed incident policy
classifies this volume `DEVICE_FAILURE_SUSPECTED`. A bounded 30-second cache
avoids repeated journal queries in the foreground monitor. The explicit
`health` action reports mount identity, matching current-boot journal events,
and an optional passive `smartctl` information query. It performs no repair or
filesystem consistency check. A normal mount/capacity pass can no longer
override a tracked pause.

Clearing the pause requires a reviewed policy change with structured evidence:
successful offline consistency checking, post-check UUID/boot ID and clean
NTFS3 metadata probes, and healthy device evidence. An incomplete recovery
attestation remains `HEALTH_UNKNOWN` and blocks NTFS3 startup. There is no
automatic transition based on elapsed time or absence of new log messages.

The attestation is bound to the volume UUID, stable device serial, current
boot ID, and current mount ID. It requires hash-referenced offline, device,
workspace-manifest, userdata-manifest, and metadata-probe evidence with bounded
ages. While that status is active, the guard checks device-correlated NTFS3,
block-I/O, UAS, and USB reset/disconnect events since the post-check timestamp;
a new event re-blocks the guard. A changed boot, mount epoch, source identity,
stale evidence, truncated/unavailable journal, or inaccessible device identity
returns `HEALTH_UNKNOWN`.

## Recovery gate (procedure only; not performed)

1. Keep Android stopped and do not write to or remount this volume.
2. Establish device health with a passive SMART query through authorized
   access. If hardware errors persist or the device is unstable, prioritize a
   read-only image to a healthy disk or professional recovery before repairs.
3. Make and verify an independent backup/image on a different healthy device;
   preserve the original source and record hashes for copied files.
4. Only after backup, safely stop all writers and detach the volume using the
   normal desktop/device workflow. Confirm it is not mounted anywhere.
5. On Windows, run an NTFS consistency check and record its exact result.
   Do not run repair until the backup decision is complete; use Windows
   `chkdsk` only under a separate, explicitly authorized recovery operation.
   Do not substitute `ntfsfix`.
6. Return to Linux and inspect the mount UUID, kernel log from a new boot,
   targeted metadata access, device transport errors, and userdata manifest.
   Confirm no new NTFS3 or block I/O errors.
7. Update the UUID policy only with recorded offline-check, device-health, and
   post-mount evidence. Then run the normal workspace guard and only a bounded
   AaaS post-recovery regression.

Until those steps and evidence are complete, the current classification stays
`DEVICE_FAILURE_SUSPECTED` and **all Android sessions and workspace-backed
tests remain blocked**.

## Guard validation

The focused workspace-guard tests passed 21 tests. The full suite ran 368
tests: 367 passed, zero failed, zero errored, and one was skipped. The skip is
`test_run_aaas.ForegroundRunnerTests.test_single_instance_lock_rejection`,
which deliberately skips when the external workspace guard is unhealthy; it
was not bypassed. Python compilation, both JSON validations, and
`git diff --check` passed. No Android regression was run because the health
gate remains active.

## Post-CHKDSK Linux verification attempt (2026-11-07)

The repository and bounded local search did not find a CHKDSK transcript,
exported Windows event, command flags, completion result, repair summary, or
bad-cluster report. The user reports running CHKDSK, but execution, completion,
repair, and clean status remain unverified.

After boot `c0a7b7de-753c-4c02-9042-2103818b72ef` started at
2026-11-07 09:08:05 +05:30, the drive reappeared as `/dev/sda`, and `lsblk`
reported `/dev/sda2`, NTFS, UUID `A2ACEDF2ACEDC0C1`, 465.7 GiB, and no
mountpoint. Udev identified the same Crucial BX500 SSD (revision M6CR072,
serial `2421E8B20AE0`) behind a USB 3.0 bridge, VID:PID `152d:0578`, UAS driver,
USB path 2-3. The reported `ROTA=1` conflicts with the SSD model and udev's ATA
rotation rate 0, so it is not used to infer a mechanical disk.

The bounded current-boot journal contains no NTFS3 mount errors, UAS aborts,
USB resets/disconnects, or block I/O errors for this device from enumeration
through 09:12:42. The observation covers about four minutes while the
partition was unmounted; it is not a transport stability test. A fresh
passive `smartctl -x -n standby /dev/sda` again failed with permission denied.
No SMART health or media counters are available.

Because the volume is unmounted, the workspace marker, userdata manifest,
PackageManager records, shared storage, and targeted NTFS metadata could not
be checked. No mount or remount was attempted. The normal workspace check
exited 2 because the marker was absent at the expected mount path. The explicit
device diagnostic reported the tracked `DEVICE_FAILURE_SUSPECTED` quarantine,
the UUID, no current-boot storage errors in the bounded observation, and
unavailable SMART data. The policy remains unchanged; no Android session ran.

This observation does not clear the quarantine. The next evidence needed is
the actual CHKDSK result, authorized passive device-health data, an approved
backup decision, and a user- or system-managed normal mount followed by
post-mount metadata and stability checks. The exact structured result is
`post_chkdsk_assessment_2026_11_07` in
[`acceptance.json`](../../results/m4/acceptance.json).

The post-repair guard suite passed 24 tests. The full Python suite ran 371
tests and failed with 18 errors and 7 skips: 11 real cgroup-hierarchy tests
could not find the delegated `user@1000.service/aaas` scope, and 7 audio
runner tests could not find their Android HAL factory fixture on the unmounted
workspace. The other 346 tests passed. Python compilation, JSON validation,
and `git diff --check` passed. No test started Android or accessed userdata.
