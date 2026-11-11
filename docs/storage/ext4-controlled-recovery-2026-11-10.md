# ext4 workspace recovery checkpoint — 2026-11-10

## Scope

This checkpoint follows a later USB-storage interruption on the enrolled AaaS
workspace UUID `$AAAS_WORKSPACE_UUID`. The earlier incident
record remains preserved. This enables only guarded controlled testing; it does
not certify the SSD, USB bridge, cable, port, or power path as fault-free.

## Offline filesystem check

After `$AAAS_WORKSPACE_DEVICE` was unmounted, the user ran:

```text
sudo e2fsck -fn /dev/disk/by-uuid/$AAAS_WORKSPACE_UUID
e2fsck 1.47.4 (6-Mar-2025)
Pass 1: Checking inodes, blocks, and sizes
Inode 4198685 extent tree (at level 2) could be narrower. Optimize? no
Pass 2: Checking directory structure
Pass 3: Checking directory connectivity
Pass 4: Checking reference counts
Pass 5: Checking group summary information
Aaas: 575918/8003584 files (0.4% non-contiguous), 22403153/32000000 blocks
```

All five passes completed without a filesystem inconsistency report. `-n`
made no changes. The extent-tree message is an optimization suggestion, not a
reported inconsistency. The command ran after the successful unmount and before
the subsequent mount at 01:03:53 IST; the exact command completion timestamp
was not printed, so the evidence record uses the later capture time.

## Device health evidence

At 01:05:16 IST the user ran the passive command
`sudo smartctl -x -n standby /dev/sda`. SMART overall health was `PASSED`;
reallocated sectors, pending sectors, offline uncorrectable sectors, reported
uncorrectable errors, and end-to-end errors were zero. Temperature was 37 C.
The cumulative UDMA CRC count was 727, up from the earlier recorded 717. The
current SATA PHY report listed zero ICRC and R_ERR counts and one COMRESET.
These counters are transport history and do not establish when the increments
occurred or identify the failing component. No self-test, scan, or write test
was run. Hardware/transport reliability remains uncertified.

## Post-check observation

At checkpoint time 01:07:42 IST, the volume was mounted read-write from
`$AAAS_WORKSPACE_DEVICE`, ext4 UUID `$AAAS_WORKSPACE_UUID`, mount ID `246`,
with `errors=remount-ro`. The parent device identity was
`$WORKSPACE_DEVICE_SERIAL`. The workspace marker matched the mount target,
filesystem, and UUID. The userdata manifest matched the workspace and `data`
backing; the data directory existed on the workspace filesystem. The current
filesystem had about 30.5 GiB available; host root had about 20.6 GiB available,
above the configured reserves at observation.

The bounded kernel-journal query from the 01:03:53 mount through this checkpoint
showed the mount event and no new matching ext4, JBD2, USB/UAS, or block-I/O
errors. The previous 21 device-correlated errors remain visible as the cause of
this recovery checkpoint; they are not erased. Guarded AaaS testing must stop
and quarantine the workspace if any new device-correlated error appears.

## Result

The offline check is clean and fresh passive SMART evidence shows no reported
media-error counters, but the increase in cumulative CRC errors and prior USB
I/O failures leave transport reliability unresolved. The UUID-scoped policy
permits controlled testing only with the existing live journal guard. No
userdata was reset or migrated as part of this check.
