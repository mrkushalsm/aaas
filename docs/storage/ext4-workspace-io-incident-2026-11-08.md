# ext4 workspace I/O incident — 2026-11-08

## Classification

`DEVICE_FAILURE_SUSPECTED`. AaaS startup and workspace-backed tests are
blocked by the UUID-scoped guard entry for ext4 UUID
`094120c3-e1f8-4a61-a95a-c347ecb711d1`. The filesystem is currently visible as
read/write, but that does not clear the incident.

## Device and mount

The workspace is `/run/media/mrkus/Aaas/aaas-workspace`, on `/dev/sda3`, ext4,
UUID `094120c3-e1f8-4a61-a95a-c347ecb711d1`, mounted at `/run/media/mrkus/Aaas`.
Its parent is USB/UAS SSD `/dev/sda`, model `CT500BX500SSD1`, serial
`2421E8B20AE0`. At observation, kernel boot ID was
`019bfef2-ef76-45a4-971b-9612ccf7a155`.

## Kernel evidence

The current-boot kernel journal reports UAS aborts and read I/O failures on
`/dev/sda` around 21:20 on November 7, followed by a UAS host reset and a
SuperSpeed USB reset around 21:21. At 23:08:11, while ext4 UUID
`094120c3-e1f8-4a61-a95a-c347ecb711d1` was mounted, the kernel reported:

- `Buffer I/O error on dev sda3, logical block 15761408, lost sync page write`
- `JBD2: I/O error when updating journal superblock for sda3-8.`
- `EXT4-fs (sda3): shut down requested (2)`
- `EXT4-fs (sda3): unmounting filesystem ...`

At 23:08:18, the kernel reported the same UUID mounted read/write and `recovery
complete`. That automatic journal recovery is not proof that the underlying
storage path is reliable. The cable-change timestamp is unavailable, so these
events cannot be classified as definitely before or after that change.

The user supplied passive SMART output for the same SSD: overall health
`PASSED`; reallocated, pending, uncorrectable, and end-to-end error counts were
zero; UDMA CRC count was 717; SATA PHY counters included 3 ICRC errors, 3 data
FIS R_ERR responses, and 41 COMRESETs. These counters support an interface or
transport concern but do not establish whether the SSD media, bridge, cable,
port, or power caused the events. No SMART self-test or scan was run.

No additional matching UAS, USB reset, block I/O, or ext4 journal messages
appeared in the bounded journal query after 23:08:11 through the current
observation. The short interval is not a stability test.

## AaaS activity and cleanup

After the 23:08 ext4 recovery, two bounded audio diagnostic sessions ran before
the journal sequence was inspected:

- `m1b84_session_e74t474f`: audio samples reached the default host output;
  session stopped normally.
- `m1b84_session_5alc1utr`: AudioTrack PCM reached the controlled PipeWire
  null sink; session stopped normally and its bridge exited.

Their logs and state records remain on the workspace. At incident-record time,
the UUID was quarantined and no further Android or workspace-backed AaaS
sessions were permitted. These sessions are disclosed here and are not
represented as a storage-health test.

## Recovery requirements recorded at incident time

Do not write to this workspace or launch Android until the storage path and
filesystem have been assessed. Preserve the journal evidence and existing
userdata. Establish that the USB/SATA path is stable, obtain fresh passive
device-health evidence, inspect the ext4 filesystem offline using the normal
Linux recovery process only after data-preservation decisions, and then verify
the workspace and userdata manifests. Any repair or full copy must be planned
separately; do not run an online repair or treat the automatic replay as a
clean result. Clear the UUID quarantine only through a documented,
evidence-backed recovery transition.

The prior NTFS3 incident remains preserved in
[`ntfs3-health-assessment-2026-11-07.md`](ntfs3-health-assessment-2026-11-07.md).

## Recurrent I/O failure after the 2026-11-10 checkpoint

After a clean offline `e2fsck -fn` and passive SMART query, a bounded AaaS
service start was attempted on 2026-11-10. At 01:14:16 IST the kernel reported
write I/O errors to ext4 inodes, failed unwritten-extent conversion, block I/O
errors, and a JBD2 journal-superblock write failure. `logcat` then received an
aborted-journal error. The kernel unmounted the volume at 01:14:38 and mounted
it read-write after journal recovery at 01:14:50. The workspace guard recorded
31 post-check device-correlated errors and quarantined the volume again. The
AaaS user service was stopped; no further runtime start is authorized by the
guard. KWin remained alive. The clean e2fsck result predates this recurrence
and does not supersede it. Do not use the workspace until a new offline check
and transport/device recovery assessment are completed.

## Post-check recovery transition

On 2026-11-08 the user ran `e2fsck -fn` while the filesystem was unmounted;
all five passes completed without reported inconsistencies. The ext4 volume was
then mounted at its verified UUID, and the workspace and userdata manifests
were readable and matched. The bounded journal query after the recovery
checkpoint found no new matching events. Passive SMART evidence supplied by
the user reports a passing overall result and zero media-error counters, with
historical nonzero interface counters; the report predates the incident and is
not treated as a guarantee of transport health.

The incident remains preserved as `DEVICE_FAILURE_SUSPECTED` in the policy
history. Its effective state is now `HEALTHY_FOR_CONTROLLED_TESTING` through the
validated recovery attestation in `workspace-health.json`. New device-correlated
errors after that checkpoint reactivate quarantine. See
[`ext4-controlled-recovery-2026-11-08.md`](ext4-controlled-recovery-2026-11-08.md).
