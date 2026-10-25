# M1B graphics blocker: Ranchu mapper requires Goldfish

## Retained observation

The diagnostic rootfs trace at
`$AAAS_WORKSPACE/tmp/sf_strace.log` shows SurfaceFlinger loading
`/vendor/lib64/hw/mapper.ranchu.so`. Its thread then attempted
`/dev/goldfish_pipe_dprctd` and `/dev/goldfish_address_space`; both opens
returned `ENOENT`. The mapper logged
`GoldfishAddressSpaceHostMemoryAllocator failed to open` and raised `SIGABRT`.
The matching logcat is `$AAAS_WORKSPACE/tmp/full_logcat.log`. This establishes
the crash in that modified diagnostic run; it does not establish a clean
container boot, successful buffer allocation, or frame presentation.

## Native replacement boundary

Goldfish devices implement emulator protocols, not generic Linux memory
allocation. Redirecting their `open` calls to memfd or returning success from
their `ioctl` calls would not implement buffer allocation, metadata,
cross-process ownership, or fences. Do not extend `shim_selinux.c` to emulate
them. Do not install a fake device node or patch the Ranchu binary.

The pinned upstream `external/minigbm` source at
`b7c93249f685222a524c51403719493cc114ff5d` contains both
`mapper.minigbm` (native mapper 5.0 VINTF fragment) and
`android.hardware.graphics.allocator-service.minigbm` (AIDL Allocator 2).
Its source and VINTF declarations are a candidate replacement pair for the
Ranchu mapper and allocator. The host has Intel and NVIDIA render nodes; the
minigbm build and actual allocation/import behavior on either node are not
yet verified. The image is an older Android 16 SDK build than the pinned QPR2
source, so its ABI cannot be assumed compatible.

The Ranchu Composer3 service also refers to Goldfish/QEMU devices. Replacing
only the mapper cannot prove a working display. The intended final group is
stock SurfaceFlinger plus a matched native allocator/mapper and independent
Composer3 implementation, connected to the host Wayland presenter. This is
part of the minimal Android product; emulator services are omitted from its
product configuration rather than hidden behind emulation hooks.

## Next bounded experiment

1. Identify an Android source snapshot matching the SDK image, or build a
   coherent minimal product entirely from one pinned source graph. Record
   mapper stable-C version, allocator AIDL version, VINTF, and linked library
   ABI before installing any candidate into an experimental rootfs.
2. Build the upstream minigbm pair without source edits. The bounded QPR2
   Soong probe first stopped before compilation at
   `external/golang-protobuf/proto`. The pinned superproject
   `cc66c82349f536b77341e13862a548c01b048963` identifies that project
   as `fcb969a6e0df55f1460721e1b9c4f2c4d2b5a47f`, which was fetched
   unchanged. The next probe still stopped before compilation, now at missing
   `external/pogreb`. Its retained log is
   `$AAAS_WORKSPACE/logs/graphics-build-probe-after-golang-protobuf.log`.
   Future probe runs write unique timestamped logs. Resolve source closure
   under the external-workspace budget rather than copying libraries from a
   different Android build.
3. In a disposable image overlay, test allocator registration, mapper load,
   DMA-BUF allocation, cross-process import, metadata, and release fences.
   A build alone is insufficient. Keep the pristine SDK partitions unchanged.
4. Only after that pair passes, repeat SurfaceFlinger startup with a compatible
   Composer3 service. Record each next failure separately. Do not claim a
   presented frame until the host Wayland trace confirms one.

Stop if the matching source graph cannot be obtained within the storage
budget, if the pair fails ABI/VINTF checks, or if render-node access requires
weakening host security. Preserve the logs and exact command for that stop.
