"""Unit tests for AaaS Milestone 1B.5 graphics unblocking and Mapper 5 verification."""

import os
import re
import subprocess
import unittest
from pathlib import Path

WORKSPACE_ROOT = Path("/home/mrkus/Work/personal/projects/aaas")
EXTERNAL_ROOTFS = Path("/run/media/mrkus/Aaas/aaas-workspace/rootfs_m1b1")
EXTERNAL_TMP = Path("/run/media/mrkus/Aaas/aaas-workspace/tmp")


class M1B5GraphicsTest(unittest.TestCase):
    """Verifies Mapper 5 Stable-C source, exported symbols, VINTF, and compatibility."""

    def test_vintf_graphics_declarations(self):
        """Verify VINTF manifests for Gralloc 5 and HWComposer 3 declarations."""
        vintf_manifest_dir = EXTERNAL_ROOTFS / "vendor" / "etc" / "vintf" / "manifest"
        if not vintf_manifest_dir.exists():
            self.skipTest(f"VINTF manifest directory not found at {vintf_manifest_dir}")

        gralloc_xml = vintf_manifest_dir / "android.hardware.graphics.gralloc.ranchu.xml"
        self.assertTrue(gralloc_xml.exists(), "Gralloc VINTF manifest fragment missing")
        content = gralloc_xml.read_text(encoding="utf-8")
        self.assertIn("android.hardware.graphics.allocator", content)
        self.assertIn("IAllocator/default", content)
        self.assertIn("<fqname>@5.0/ranchu</fqname>", content)

        hwc3_xml = vintf_manifest_dir / "hwc3.xml"
        self.assertTrue(hwc3_xml.exists(), "HWC3 VINTF manifest fragment missing")
        hwc_content = hwc3_xml.read_text(encoding="utf-8")
        self.assertIn("android.hardware.graphics.composer3", hwc_content)
        self.assertIn("IComposer/default", hwc_content)

    def test_mapper_drm_source_structure(self):
        """Verify mapper_drm.cpp implementation conforms to Stable-C Mapper 5 specification."""
        src_file = WORKSPACE_ROOT / "experiments" / "m1b" / "mapper_drm" / "mapper_drm.cpp"
        self.assertTrue(src_file.exists(), "mapper_drm.cpp source file not found")
        content = src_file.read_text(encoding="utf-8")

        # Stable-C API requirements
        self.assertIn("ANDROID_HAL_MAPPER_VERSION", content)
        self.assertIn("AIMapper_loadIMapper", content)
        self.assertIn("importBuffer", content)
        self.assertIn("freeBuffer", content)
        self.assertIn("lock", content)
        self.assertIn("unlock", content)
        self.assertIn("getMetadata", content)
        self.assertIn("getStandardMetadata", content)
        self.assertIn("setMetadata", content)
        self.assertIn("setStandardMetadata", content)
        self.assertIn("listSupportedMetadataTypes", content)
        self.assertIn("dumpBuffer", content)
        self.assertIn("dumpAllBuffers", content)
        self.assertIn("getReservedRegion", content)

        header_file = WORKSPACE_ROOT / "experiments" / "m1b" / "mapper_drm" / "include" / "cutils" / "native_handle.h"
        self.assertTrue(header_file.exists(), "native_handle.h header missing")
        header_content = header_file.read_text(encoding="utf-8")
        self.assertIn("native_handle_t", header_content)
        self.assertIn("numFds", header_content)
        self.assertIn("numInts", header_content)

    def test_mapper_drm_binary_symbols(self):
        """Verify exported dynamic symbols in compiled mapper.drm.so."""
        so_file = EXTERNAL_TMP / "mapper.drm.so"
        if not so_file.exists():
            self.skipTest(f"mapper.drm.so not present at {so_file}")

        cmd = ["readelf", "-W", "-s", str(so_file)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        symbols = res.stdout

        self.assertIn("AIMapper_loadIMapper", symbols)
        self.assertIn("ANDROID_HAL_MAPPER_VERSION", symbols)

        # Check export binding and visibility
        for line in symbols.splitlines():
            if "AIMapper_loadIMapper" in line:
                self.assertIn("GLOBAL", line)
                self.assertIn("DEFAULT", line)
            if "ANDROID_HAL_MAPPER_VERSION" in line:
                self.assertIn("GLOBAL", line)
                self.assertIn("DEFAULT", line)

    def test_mapper_compat_source(self):
        """Verify test_mapper_compat.cpp exercises DMA-BUF import, locking, and coherency."""
        compat_src = WORKSPACE_ROOT / "experiments" / "m1b" / "mapper_drm" / "test_mapper_compat.cpp"
        self.assertTrue(compat_src.exists(), "test_mapper_compat.cpp source file not found")
        content = compat_src.read_text(encoding="utf-8")

        self.assertIn("AIMapper_loadIMapper", content)
        self.assertIn("ANDROID_HAL_MAPPER_VERSION", content)
        self.assertIn("METADATA_BUFFER_ID", content)
        self.assertIn("METADATA_WIDTH", content)
        self.assertIn("METADATA_HEIGHT", content)
        self.assertIn("memfd_create", content)
        self.assertIn("importBuffer", content)
        self.assertIn("lock", content)
        self.assertIn("unlock", content)
        self.assertIn("freeBuffer", content)

    def test_zygote_startup_overlay_flags(self):
        """Verify test_zygote_startup.py supports isolated overlay binds and prefix logging."""
        script_path = WORKSPACE_ROOT / "scripts" / "test_zygote_startup.py"
        self.assertTrue(script_path.exists())
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("AAAS_LOG_PREFIX", content)
        self.assertIn("AAAS_USE_DRM_MAPPER", content)
        self.assertIn("mapper.drm.so", content)
        self.assertIn("/vendor/lib64/hw/mapper.ranchu.so", content)

    def test_historical_baseline_preserved(self):
        """Verify historical baseline logs remain intact and isolated in historical_baseline/."""
        baseline_dir = EXTERNAL_TMP / "historical_baseline"
        if not baseline_dir.exists():
            self.skipTest(f"Historical baseline directory not found at {baseline_dir}")

        baseline_logcat = baseline_dir / "full_logcat.log"
        self.assertTrue(baseline_logcat.exists(), "Historical baseline full_logcat.log missing")
        content = baseline_logcat.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("mapper.ranchu.so", content)
        self.assertIn("GoldfishAddressSpaceHostMemoryAllocator failed to open", content)


if __name__ == "__main__":
    unittest.main()
