#!/usr/bin/env python3
"""Pure-Python reader for Android dynamic partition (LP) metadata.

Reads the Logical Partition (LP) geometry and partition table from an Android
super.img (or a GPT disk image containing a super partition, like system.img)
without requiring any native tools or root privileges.
Outputs a JSON report of partitions, their extents, sizes, and groups.

Reference: system/core/fs_mgr/liblp/include/liblp/metadata_format.h (AOSP)

Usage:
    python3 scripts/read_lp_metadata.py \
        --image /path/to/super.img \
        --results results/m1b0/lp-metadata.json
"""

import argparse
import json
import struct
import sys
from pathlib import Path

# LP metadata magic and version constants
LP_METADATA_MAGIC = 0x414C5030           # 'ALP0' / b'0PLA'
LP_METADATA_GEOMETRY_MAGIC = 0x616C4467      # 'aldg' / b'gDla'
LP_PARTITION_RESERVED_BYTES = 4096
LP_METADATA_GEOMETRY_SIZE = 4096

# Struct formats (all little-endian)
# LpMetadataGeometry:
#   uint32_t magic, struct_size, checksum[32], metadata_max_size,
#   metadata_slot_count, logical_block_size
GEOMETRY_FMT = '<II32sIII'
GEOMETRY_SIZE = struct.calcsize(GEOMETRY_FMT)

# LpMetadataTableDescriptor:
#   uint32_t offset, num_entries, entry_size
TABLE_DESC_FMT_BARE = 'III'

# LpMetadataHeader (little-endian):
#   uint32_t magic; uint16_t major_version, minor_version; uint32_t header_size
#   uint8_t  header_checksum[32]
#   uint32_t tables_size
#   uint8_t  tables_checksum[32]
#   LpMetadataTableDescriptor partitions, extents, groups, block_devices
HEADER_FMT = '<IHHI32sI32s' + TABLE_DESC_FMT_BARE * 4
HEADER_SIZE = struct.calcsize(HEADER_FMT)

# LpMetadataPartition:
#   char name[36], uint32_t attributes, uint32_t first_extent_index,
#   uint32_t num_extents, uint32_t group_index
PARTITION_FMT = '<36sIIII'
PARTITION_SIZE = struct.calcsize(PARTITION_FMT)

# LpMetadataExtent:
#   uint64_t num_sectors, uint32_t target_type, uint64_t target_data,
#   uint32_t target_source
EXTENT_FMT = '<QIQI'
EXTENT_SIZE = struct.calcsize(EXTENT_FMT)

# LpMetadataPartitionGroup:
#   char name[36], uint32_t flags, uint64_t max_size
GROUP_FMT = '<36sIQ'
GROUP_SIZE = struct.calcsize(GROUP_FMT)

# LpMetadataBlockDevice:
#   uint64_t first_logical_sector, uint32_t alignment, uint32_t alignment_offset,
#   uint64_t block_device_size, char partition_name[36], uint32_t flags
BLOCK_DEV_FMT = '<QIIQ36sI'
BLOCK_DEV_SIZE = struct.calcsize(BLOCK_DEV_FMT)


class LpError(Exception):
    pass


def find_super_offset(f) -> int:
    """Find byte offset where super partition starts in file.

    Returns:
        0 if super starts at offset 0 (raw super.img)
        offset > 0 if embedded inside a GPT partition (e.g. system.img)
    """
    f.seek(0)
    mbr = f.read(512)
    # Check for GPT partition table
    if len(mbr) == 512 and mbr[510:512] == b'\x55\xaa':
        gpt_hdr_raw = f.read(512)
        if gpt_hdr_raw[:8] == b'EFI PART':
            # Read partition entries
            part_lba, num_parts, part_size = struct.unpack('<QII', gpt_hdr_raw[72:88])
            f.seek(part_lba * 512)
            for _ in range(num_parts):
                entry = f.read(part_size)
                if len(entry) < part_size or entry[:16] == b'\x00' * 16:
                    continue
                start_lba, end_lba, _flags = struct.unpack('<QQQ', entry[32:56])
                name = entry[56:128].decode('utf-16le', errors='replace').rstrip('\x00')
                if name.lower() == 'super':
                    return start_lba * 512

    # Check direct LP geometry at LP_PARTITION_RESERVED_BYTES
    f.seek(LP_PARTITION_RESERVED_BYTES)
    magic = f.read(4)
    if magic == struct.pack('<I', LP_METADATA_GEOMETRY_MAGIC):
        return 0

    return 0


def read_geometry(f, base_offset: int) -> dict:
    """Read the LP geometry from LP_PARTITION_RESERVED_BYTES."""
    geom_offset = base_offset + LP_PARTITION_RESERVED_BYTES
    f.seek(geom_offset)
    raw = f.read(GEOMETRY_SIZE)
    if len(raw) < GEOMETRY_SIZE:
        raise LpError('image too small to contain LP geometry')

    magic, struct_size, checksum, metadata_max_size, \
        metadata_slot_count, logical_block_size = struct.unpack_from(GEOMETRY_FMT, raw)

    if magic != LP_METADATA_GEOMETRY_MAGIC:
        raise LpError(f'LP geometry magic mismatch: 0x{magic:08X} != 0x{LP_METADATA_GEOMETRY_MAGIC:08X}')

    # Metadata slots start after reserved bytes + 2 geometry slots
    first_metadata_offset = base_offset + LP_PARTITION_RESERVED_BYTES + (LP_METADATA_GEOMETRY_SIZE * 2)

    return {
        'magic': f'0x{magic:08X}',
        'struct_size': struct_size,
        'metadata_max_size': metadata_max_size,
        'metadata_slot_count': metadata_slot_count,
        'logical_block_size': logical_block_size,
        'first_metadata_offset': first_metadata_offset,
    }


def read_header(f, offset: int) -> tuple:
    """Read LP metadata header at the given offset."""
    f.seek(offset)
    raw = f.read(HEADER_SIZE)
    if len(raw) < HEADER_SIZE:
        raise LpError(f'cannot read LP header at offset {offset}')

    fields = struct.unpack_from(HEADER_FMT, raw)
    magic = fields[0]
    major = fields[1]
    minor = fields[2]
    header_size = fields[3]
    tables_size = fields[5]

    if magic != LP_METADATA_MAGIC:
        raise LpError(f'LP header magic mismatch: 0x{magic:08X} != 0x{LP_METADATA_MAGIC:08X}')

    # Parse four table descriptors
    base = 7  # index into fields after fixed header
    def parse_td(i):
        off = base + i * 3
        return {'offset': fields[off], 'num_entries': fields[off+1], 'entry_size': fields[off+2]}

    tables = {
        'partitions': parse_td(0),
        'extents': parse_td(1),
        'groups': parse_td(2),
        'block_devices': parse_td(3),
    }
    return {
        'magic': f'0x{magic:08X}',
        'major_version': major,
        'minor_version': minor,
        'header_size': header_size,
        'tables_size': tables_size,
        'tables': tables,
    }, offset + header_size


def read_table(f, base_offset: int, descriptor: dict, entry_fmt: str, entry_size: int) -> list:
    """Read a table of fixed-size entries."""
    offset = base_offset + descriptor['offset']
    n = descriptor['num_entries']
    declared_size = descriptor['entry_size']
    f.seek(offset)
    rows = []
    for _ in range(n):
        raw = f.read(declared_size)
        if len(raw) < entry_size:
            break
        rows.append(struct.unpack_from(entry_fmt, raw))
    return rows


def parse_metadata_tables(f, header: dict, tables_base: int) -> tuple:
    partition_rows = read_table(f, tables_base, header['tables']['partitions'],
                                PARTITION_FMT, PARTITION_SIZE)
    extent_rows = read_table(f, tables_base, header['tables']['extents'],
                             EXTENT_FMT, EXTENT_SIZE)
    group_rows = read_table(f, tables_base, header['tables']['groups'],
                            GROUP_FMT, GROUP_SIZE)
    block_dev_rows = read_table(f, tables_base, header['tables']['block_devices'],
                                BLOCK_DEV_FMT, BLOCK_DEV_SIZE)

    block_devs = []
    for row in block_dev_rows:
        first_logical_sector, alignment, alignment_offset, block_device_size, \
            partition_name, flags = row
        block_devs.append({
            'name': partition_name.rstrip(b'\x00').decode('utf-8', errors='replace'),
            'block_device_size': block_device_size,
            'block_device_size_mib': round(block_device_size / 1024 / 1024, 1),
            'first_logical_sector': first_logical_sector,
            'alignment': alignment,
            'flags': flags,
        })

    groups = []
    for row in group_rows:
        name_raw, flags, max_size = row
        groups.append({
            'name': name_raw.rstrip(b'\x00').decode('utf-8', errors='replace'),
            'flags': flags,
            'max_size_bytes': max_size,
            'max_size_mib': round(max_size / 1024 / 1024, 1),
        })

    partitions = []
    for row in partition_rows:
        name_raw, attributes, first_extent_index, num_extents, group_index = row
        name = name_raw.rstrip(b'\x00').decode('utf-8', errors='replace')
        extents = []
        for i in range(first_extent_index, first_extent_index + num_extents):
            if i >= len(extent_rows):
                break
            num_sectors, target_type, target_data, target_source = extent_rows[i]
            extents.append({
                'num_sectors': num_sectors,
                'size_bytes': num_sectors * 512,
                'size_mib': round(num_sectors * 512 / 1024 / 1024, 1),
                'target_type': target_type,  # 0=linear, 1=zero
                'target_data_sector': target_data,  # sector offset on source device
                'offset_bytes': target_data * 512,
                'offset_mib': round(target_data * 512 / 1024 / 1024, 1),
                'target_source': target_source,
            })
        group_name = groups[group_index]['name'] if group_index < len(groups) else f'group_{group_index}'
        partitions.append({
            'name': name,
            'attributes': attributes,
            'group_name': group_name,
            'group_index': group_index,
            'extents': extents,
            'total_size_bytes': sum(e['size_bytes'] for e in extents),
            'total_size_mib': round(sum(e['size_bytes'] for e in extents) / 1024 / 1024, 1),
        })

    return partitions, groups, block_devs


def probe_partition_filesystems(f, base_offset: int, partitions: list) -> dict:
    """Probe the filesystem superblock of each partition."""
    fs_types = {}
    for p in partitions:
        name = p['name']
        if not p['extents'] or p['extents'][0]['target_type'] != 0:
            fs_types[name] = 'empty'
            continue
        first_ext = p['extents'][0]
        ext_byte_offset = base_offset + first_ext['offset_bytes']
        f.seek(ext_byte_offset)
        buf = f.read(2048)
        if len(buf) < 2048:
            fs_types[name] = 'unknown'
            continue
        # Check ext4 magic at offset 1080 (0x438) -> 0xEF53 (little endian: b'\x53\xef')
        if buf[1080:1082] == b'\x53\xef':
            fs_types[name] = 'ext4'
        elif buf[:4] == b'\xe2\xe1\xf5\xe0':
            fs_types[name] = 'erofs'
        elif buf[1024:1028] == b'\x10\x20\xf5\xf2':
            fs_types[name] = 'f2fs'
        else:
            fs_types[name] = 'raw/unknown'
    return fs_types


def read_lp_metadata(image_path: Path) -> dict:
    with open(image_path, 'rb') as f:
        base_offset = find_super_offset(f)
        try:
            geometry = read_geometry(f, base_offset)
        except LpError as e:
            return {'error': str(e), 'is_super': False}

        metadata_offset = geometry['first_metadata_offset']
        try:
            header, tables_base = read_header(f, metadata_offset)
        except LpError as e:
            return {'geometry': geometry, 'error': str(e)}

        partitions, groups, block_devs = parse_metadata_tables(f, header, tables_base)
        fs_types = probe_partition_filesystems(f, base_offset, partitions)
        for p in partitions:
            p['fs_type'] = fs_types.get(p['name'], 'unknown')

    return {
        'is_super': True,
        'base_offset': base_offset,
        'geometry': geometry,
        'header': header,
        'block_devices': block_devs,
        'groups': groups,
        'partitions': partitions,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image', required=True, help='path to super.img or system.img')
    ap.add_argument('--results', default='results/m1b0/lp-metadata.json')
    args = ap.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        print(f'error: image not found: {image_path}', file=sys.stderr)
        return 2

    print(f'reading LP metadata from: {image_path}')
    result = read_lp_metadata(image_path)

    if result.get('error') and not result.get('is_super', True):
        print(f'not an LP super image: {result["error"]}')
    elif result.get('error'):
        print(f'LP parse error: {result["error"]}')
    else:
        print(f'LP super image detected (base_offset: {result["base_offset"]} bytes)')
        print(f'  metadata_slot_count: {result["geometry"]["metadata_slot_count"]}')
        print(f'  logical_block_size:  {result["geometry"]["logical_block_size"]}')
        print(f'  block devices: {len(result["block_devices"])}')
        print(f'  groups: {len(result["groups"])}')
        print(f'  partitions: {len(result["partitions"])}')
        for p in result['partitions']:
            print(f'    {p["name"]:20s}  {p["fs_type"]:8s}  {p["total_size_mib"]:8.1f} MiB  (group: {p["group_name"]})')

    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2) + '\n')
    print(f'report: {results_path}')
    return 0 if not result.get('error') else 1


if __name__ == '__main__':
    sys.exit(main())
