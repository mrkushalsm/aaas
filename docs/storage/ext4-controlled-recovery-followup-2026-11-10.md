# ext4 controlled recovery follow-up — 2026-11-10

## Evidence and scope

This checkpoint follows the 01:14 IST device-offline/write-error event. It preserves
that incident and allows only guarded controlled testing. It does not certify the
USB/SATA transport or SSD as fault-free. The user supplied the following fresh,
offline `e2fsck -fn` result after unmounting the volume; exit status was 0:

```text
e2fsck 1.47.4 (6-Mar-2025)
Pass 1: Checking inodes, blocks, and sizes
Inode 4198685 extent tree (at level 2) could be narrower. Optimize? no
Pass 2: Checking directory structure
Pass 3: Checking directory connectivity
Pass 4: Checking reference counts
Pass 5: Checking group summary information
Aaas: 576274/8003584 files (0.4% non-contiguous), 22405899/32000000 blocks
```

No inconsistency was reported. The extent-tree message is an optimization suggestion.
The command was run while unmounted; `-n` made no repairs.

The user's fresh passive `smartctl -x -n standby /dev/sda` output reports overall
health `PASSED`, zero reallocated/pending/offline-uncorrectable/reported-uncorrectable/
end-to-end errors, UDMA CRC count 727 (unchanged from the earlier checkpoint), zero
current SATA PHY ICRC/R_ERR counters, and one COMRESET. This is consistent with a
transport interruption but does not identify its physical cause or guarantee future
reliability. No SMART test or scan was run.

## Re-mount and metadata checks

At evidence capture `2026-11-10T01:33:57+05:30`, `/dev/sda3` was mounted read-write at
`/run/media/mrkus/Aaas` as ext4 UUID `094120c3-e1f8-4a61-a95a-c347ecb711d1` (mount ID `246`), with
`errors=remount-ro`. Parent device serial: `CT500BX500SSD1_2421E8B20AE0`; current boot ID: `019bfef2-ef76-45a4-971b-9612ccf7a155`.
The workspace marker matches the UUID and mount target. The runtime rootfs exists.
The private userdata manifest matches workspace `/run/media/mrkus/Aaas/aaas-workspace` and backing `data`;
its data directory is on the same filesystem and the userdata control directory
remains owned by the user with mode 0700. No userdata was reset or modified.
Available space at observation: workspace filesystem 32727060480 bytes; host root
22131548160 bytes.

The kernel recorded the prior device-offline error, ext4 write failures, journal
abort, unmount, and subsequent ext4 journal recovery at 01:14 IST. The user then
ran the clean offline check above. The device was mounted again at 01:31:01 IST.
The bounded kernel-journal query from 01:32:34 IST through this post-check found
no later matching storage errors. Any new device-correlated error reactivates the
workspace quarantine and must stop AaaS immediately.

## Result

The filesystem check, identity and userdata metadata checks pass. The prior event
is retained as a real device-offline incident; the evidence supports controlled,
workspace-guarded testing only, not an assertion that the transport is repaired.
