# AaaS workspace capacity policy

The active workspace guard is filesystem-availability based. It no longer
enforces the former fixed 80 GiB workspace allocation ceiling. Workspace
directory allocation (`st_blocks`), filesystem used blocks, filesystem blocks
available to the user (`f_bavail`), and sparse-file logical sizes are reported
separately. Admission checks use actual `f_bavail` on the enrolled filesystem;
they do not infer free space by subtracting workspace usage from filesystem
capacity. This also accounts correctly for other data sharing the partition
and for ext4 blocks reserved from unprivileged users.

New workspace enrollment uses a **2 GiB free-space reserve** on the enrolled
workspace filesystem. This is a small fixed reserve for filesystem metadata,
logs, orderly shutdown, and recovery. The value can be selected during initial
enrollment with `--free-reserve-gib` (allowed range: 1–32 GiB) and is recorded
in the workspace marker. Existing markers without the new field migrate
conservatively to 2 GiB; legacy 80 GiB ceiling and 20 GiB workspace reserve
fields are ignored. The marker never overrides filesystem identity or health
checks.

The host root filesystem separately retains a **20 GiB minimum available-space
reserve**. When a predicted write targets the same filesystem as `/`, that
growth is charged against the root reserve too. For writes to a separate
dedicated partition, it is not incorrectly charged to host root capacity.
Bundle installation preflight uses unprivileged available blocks for both
filesystems.

The current enrolled partition is `$AAAS_WORKSPACE_DEVICE`, ext4 UUID
`$AAAS_WORKSPACE_UUID`, mounted at `$AAAS_MOUNT`.
The current read-only capacity snapshot reports 128,414,248,960 total bytes,
85,787,475,968 filesystem-used bytes, and 36,056,395,776 bytes available to the
user. The workspace itself accounts 82,114,392,064 allocated bytes. These
figures are observations, not capacity promises. Health remains
`HEALTHY_FOR_CONTROLLED_TESTING` under the existing evidence-backed recovery
policy; the historical USB/UAS and ext4 incident remains recorded.

The guard continues to reject a missing or changed UUID, wrong mount target,
read-only or `noexec` mount, unhealthy device state, and loss of the host root
reserve. It does not repair or remount filesystems. See
[`android-runtime-integrity.md`](../android-runtime-integrity.md) for the
workspace health and incident policy.
