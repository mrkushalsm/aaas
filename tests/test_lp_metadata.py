"""Unit tests for read_lp_metadata.py."""

import struct
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
import read_lp_metadata as lp


class LpMetadataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_dir = Path(self.tmp.name)

    def _create_synthetic_super(self, base_offset: int = 0) -> Path:
        """Create a minimal synthetic super image."""
        img_path = self.tmp_dir / 'test_super.img'
        total_size = base_offset + 64 * 1024
        buf = bytearray(total_size)

        # 1. If base_offset > 0, write a minimal GPT header pointing to super
        if base_offset > 0:
            # MBR signature
            buf[510:512] = b'\x55\xaa'
            # GPT header at sector 1 (512)
            gpt_hdr = bytearray(512)
            gpt_hdr[0:8] = b'EFI PART'
            gpt_hdr[12:16] = struct.pack('<I', 92)  # size
            gpt_hdr[72:80] = struct.pack('<Q', 2)   # part_lba = 2
            gpt_hdr[80:84] = struct.pack('<I', 1)   # num_parts = 1
            gpt_hdr[84:88] = struct.pack('<I', 128) # part_size = 128
            buf[512:1024] = gpt_hdr
            # Partition entry at sector 2 (1024)
            part_entry = bytearray(128)
            part_entry[0:16] = b'\x01' * 16  # type guid
            part_entry[16:32] = b'\x02' * 16 # part guid
            start_lba = base_offset // 512
            part_entry[32:40] = struct.pack('<Q', start_lba)
            part_entry[40:48] = struct.pack('<Q', start_lba + 100)
            name_bytes = 'super'.encode('utf-16le')
            part_entry[56:56+len(name_bytes)] = name_bytes
            buf[1024:1152] = part_entry

        # 2. Geometry at base_offset + LP_PARTITION_RESERVED_BYTES (4096)
        geom_off = base_offset + lp.LP_PARTITION_RESERVED_BYTES
        geom_raw = struct.pack(
            lp.GEOMETRY_FMT,
            lp.LP_METADATA_GEOMETRY_MAGIC,
            lp.GEOMETRY_SIZE,
            b'\x00' * 32,
            65536,  # metadata_max_size
            2,      # metadata_slot_count
            4096    # logical_block_size
        )
        buf[geom_off:geom_off + len(geom_raw)] = geom_raw

        # 3. Header at first_metadata_offset = base_offset + 4096 + 8192 = 12288
        hdr_off = base_offset + 12288
        table_base = hdr_off + lp.HEADER_SIZE

        # Build tables
        # Partitions: 1 entry (52 bytes)
        part_name = b'system\x00'.ljust(36, b'\x00')
        part_raw = struct.pack(lp.PARTITION_FMT, part_name, 1, 0, 1, 0)

        # Extents: 1 entry (24 bytes)
        # target_data sector 80 = offset 80 * 512 = 40960 bytes in base
        ext_raw = struct.pack(lp.EXTENT_FMT, 1024, 0, 80, 0)

        # Groups: 1 entry (48 bytes)
        grp_name = b'default\x00'.ljust(36, b'\x00')
        grp_raw = struct.pack(lp.GROUP_FMT, grp_name, 0, 1024 * 1024 * 100)

        # Block devices: 1 entry (64 bytes)
        blk_name = b'super\x00'.ljust(36, b'\x00')
        blk_raw = struct.pack(lp.BLOCK_DEV_FMT, 2048, 4096, 0, 1024 * 1024 * 500, blk_name, 0)

        tables_data = part_raw + ext_raw + grp_raw + blk_raw

        # Offsets relative to tables_base:
        part_off = 0
        ext_off = len(part_raw)
        grp_off = ext_off + len(ext_raw)
        blk_off = grp_off + len(grp_raw)

        hdr_raw = struct.pack(
            lp.HEADER_FMT,
            lp.LP_METADATA_MAGIC,
            10, 0, lp.HEADER_SIZE,
            b'\x00' * 32,
            len(tables_data),
            b'\x00' * 32,
            part_off, 1, lp.PARTITION_SIZE,
            ext_off, 1, lp.EXTENT_SIZE,
            grp_off, 1, lp.GROUP_SIZE,
            blk_off, 1, lp.BLOCK_DEV_SIZE
        )
        buf[hdr_off:hdr_off + len(hdr_raw)] = hdr_raw
        buf[table_base:table_base + len(tables_data)] = tables_data

        # 4. In the extent target area (sector 80 -> offset base_offset + 40960), write ext4 magic
        fs_offset = base_offset + (80 * 512)
        if fs_offset + 1082 <= len(buf):
            buf[fs_offset + 1080:fs_offset + 1082] = b'\x53\xef'

        img_path.write_bytes(buf)
        return img_path

    def test_read_raw_super_metadata(self):
        img_path = self._create_synthetic_super(base_offset=0)
        result = lp.read_lp_metadata(img_path)
        self.assertTrue(result['is_super'])
        self.assertEqual(result['base_offset'], 0)
        self.assertEqual(result['geometry']['metadata_slot_count'], 2)
        self.assertEqual(len(result['partitions']), 1)
        p = result['partitions'][0]
        self.assertEqual(p['name'], 'system')
        self.assertEqual(p['fs_type'], 'ext4')
        self.assertEqual(p['total_size_bytes'], 1024 * 512)

    def test_read_gpt_embedded_super_metadata(self):
        img_path = self._create_synthetic_super(base_offset=4096 * 512)
        result = lp.read_lp_metadata(img_path)
        self.assertTrue(result['is_super'])
        self.assertEqual(result['base_offset'], 4096 * 512)
        self.assertEqual(len(result['partitions']), 1)
        p = result['partitions'][0]
        self.assertEqual(p['name'], 'system')
        self.assertEqual(p['fs_type'], 'ext4')

    def test_non_super_returns_not_super(self):
        non_super = self.tmp_dir / 'empty.img'
        non_super.write_bytes(b'\x00' * 8192)
        result = lp.read_lp_metadata(non_super)
        self.assertFalse(result['is_super'])
        self.assertIn('magic mismatch', result['error'])


if __name__ == '__main__':
    unittest.main()
