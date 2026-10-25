"""Tests for M1B.1 Android 16 runtime boot prerequisites and Composer3 boundary."""

import ctypes
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
import extract_all_apexes as apex_tool
import extract_super_partitions as super_tool


class BinderControlIoctlTest(unittest.TestCase):
    def test_binder_ctl_add_ioctl_number(self):
        """Verify the ioctl number for BINDER_CTL_ADD matches Linux kernel ABI."""
        # _IOWR('b', 1, struct binderctl_num)
        # struct binderctl_num { char name[256]; __u32 major; __u32 minor; }; sizeof = 264
        # IOC_DIR = _IOC_READ | _IOC_WRITE = 3 (bits 30..31)
        # IOC_SIZE = 264 (bits 16..29)
        # IOC_TYPE = 'b' = 0x62 (bits 8..15)
        # IOC_NR = 1 (bits 0..7)
        expected_ioctl = (3 << 30) | (264 << 16) | (ord('b') << 8) | 1
        self.assertEqual(expected_ioctl, 0xc1086201)

    def test_binderctl_num_struct_layout(self):
        class BinderctlNum(ctypes.Structure):
            _fields_ = [
                ("name", ctypes.c_char * 256),
                ("major", ctypes.c_uint32),
                ("minor", ctypes.c_uint32)
            ]
        self.assertEqual(ctypes.sizeof(BinderctlNum), 264)


class ApexExtractorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.apex_dir = Path(self.tmp.name) / 'apex_src'
        self.target_dir = Path(self.tmp.name) / 'apex_dst'
        self.apex_dir.mkdir()
        self.target_dir.mkdir()

    def test_capex_inner_extraction_routing(self):
        """Verify that .capex files unpack inner original_apex to find payload."""
        # Build fake inner apex
        inner_bio = io.BytesIO()
        with zipfile.ZipFile(inner_bio, 'w') as izf:
            izf.writestr('apex_payload.img', b'FAKE_EXT4_DATA')
            izf.writestr('apex_manifest.pb', b'\x08\x01')
        inner_bytes = inner_bio.getvalue()

        # Build outer capex
        capex_path = self.apex_dir / 'com.android.art.capex'
        with zipfile.ZipFile(capex_path, 'w') as ozf:
            ozf.writestr('original_apex', inner_bytes)
            ozf.writestr('AndroidManifest.xml', b'<manifest/>')

        # Mock subprocess.run to intercept 7z invocation
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            apex_tool.extract_single_apex(capex_path, self.target_dir)

            self.assertTrue(mock_run.called)
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], '7z')
            self.assertEqual(args[1], 'x')
            self.assertIn(f'-o{self.target_dir / "com.android.art"}', args[3])


class SuperPartitionExtractorLogicTest(unittest.TestCase):
    @patch('extract_super_partitions.read_lp_metadata')
    def test_extract_partition_linear_slice(self, mock_read_lp):
        mock_read_lp.return_value = {
            'is_super': True,
            'base_offset': 0,
            'partitions': [
                {
                    'name': 'vendor',
                    'total_size_bytes': 1024,
                    'total_size_mib': 0.001,
                    'fs_type': 'ext4',
                    'extents': [{
                        'target_type': 0,
                        'size_bytes': 1024,
                        'offset_bytes': 4096,
                    }]
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            img_file = tmp / 'fake_super.img'
            # Write 8 KiB file with distinctive pattern at 4096..5120
            payload = b'\xAA' * 4096 + b'\xBB' * 1024 + b'\xCC' * 3072
            img_file.write_bytes(payload)

            out_dir = tmp / 'out'
            results = super_tool.extract_partitions(img_file, out_dir, ['vendor'])

            self.assertIn('vendor', results)
            vendor_out = Path(results['vendor']['path'])
            self.assertTrue(vendor_out.exists())
            self.assertEqual(vendor_out.read_bytes(), b'\xBB' * 1024)


if __name__ == '__main__':
    unittest.main()
