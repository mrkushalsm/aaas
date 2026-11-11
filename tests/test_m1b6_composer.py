"""Unit tests for AaaS Milestone 1B.6 native Composer3 virtual hardware composer."""

import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT
WORKSPACE = Path(os.environ.get("AAAS_WORKSPACE", Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "aaas/workspace"))
EXTERNAL_ROOTFS = WORKSPACE / "rootfs_m1b1"
EXTERNAL_TMP = WORKSPACE / "tmp"


class M1B6ComposerTest(unittest.TestCase):
    """Verifies AIDL Composer3 service, display lifecycle, EDID, and SurfaceFlinger integration."""

    def test_composer3_vintf_manifest(self):
        """Verify VINTF manifest declarations for AIDL Composer3 V4."""
        vintf_manifest_dir = EXTERNAL_ROOTFS / "vendor" / "etc" / "vintf" / "manifest"
        if not vintf_manifest_dir.exists():
            self.skipTest(f"VINTF manifest directory not found at {vintf_manifest_dir}")

        hwc3_xml = vintf_manifest_dir / "hwc3.xml"
        self.assertTrue(hwc3_xml.exists(), "HWC3 VINTF manifest missing")
        content = hwc3_xml.read_text(encoding="utf-8")
        self.assertIn("android.hardware.graphics.composer3", content)
        self.assertIn("IComposer/default", content)
        self.assertIn("<version>4</version>", content)

    def test_composer3_source_structure(self):
        """Verify composer_service.cpp implements BnComposer and full display lifecycle."""
        src_file = WORKSPACE_ROOT / "experiments" / "m1b" / "composer_aaas" / "composer_service.cpp"
        self.assertTrue(src_file.exists(), "composer_service.cpp source file not found")
        content = src_file.read_text(encoding="utf-8")

        # BnComposer and AIDL client contracts
        self.assertIn("class AaasComposer : public BnComposer", content)
        self.assertIn("class AaasComposerClient : public IComposerClientDefault", content)
        self.assertIn("createClient", content)
        self.assertIn("registerCallback", content)
        self.assertIn("getDisplayConfigurations", content)
        self.assertIn("getDisplayConnectionType", content)
        self.assertIn("getDisplayIdentificationData", content)
        self.assertIn("setVsyncEnabled", content)
        self.assertIn("executeCommands", content)
        self.assertIn("PresentOrValidate", content)

        # Freestanding Bionic initialization
        self.assertIn("__libc_init", content)
        self.assertIn("_start", content)
        self.assertIn("__errno_location", content)

    def test_composer3_binary_symbols(self):
        """Verify dynamic dependencies and symbols in compiled composer3 binary."""
        bin_file = EXTERNAL_TMP / "android.hardware.graphics.composer3-service.aaas"
        if not bin_file.exists():
            self.skipTest(f"AaaS Composer3 binary not present at {bin_file}")

        cmd = ["readelf", "-d", str(bin_file)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        dynamic_section = res.stdout

        self.assertIn("libbinder_ndk.so", dynamic_section)
        self.assertIn("android.hardware.graphics.composer3-V4-ndk.so", dynamic_section)
        self.assertIn("libc.so", dynamic_section)
        self.assertIn("libc++.so", dynamic_section)

    def test_composer3_edid_checksum(self):
        """Verify 128-byte EDID data structure and modulo-256 checksum."""
        src_file = WORKSPACE_ROOT / "experiments" / "m1b" / "composer_aaas" / "composer_service.cpp"
        self.assertTrue(src_file.exists())
        content = src_file.read_text(encoding="utf-8")

        # Extract kAaasEdid array from source
        match = re.search(r"kAaasEdid\s*=\s*\{([^}]+)\};", content)
        self.assertIsNotNone(match, "kAaasEdid array definition not found")
        raw_bytes_str = match.group(1)
        byte_tokens = [int(b.strip(), 16) for b in raw_bytes_str.split(",") if b.strip()]

        self.assertEqual(len(byte_tokens), 128, "EDID blob must be exactly 128 bytes")

        # Standard EDID v1 header: 00 FF FF FF FF FF FF 00
        self.assertEqual(byte_tokens[:8], [0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])

        # Modulo 256 checksum must equal 0
        checksum_sum = sum(byte_tokens) % 256
        self.assertEqual(checksum_sum, 0, f"EDID checksum validation failed (sum % 256 = {checksum_sum})")

    def test_display_lifecycle_contracts(self):
        """Verify display resolution and timing parameters."""
        src_file = WORKSPACE_ROOT / "experiments" / "m1b" / "composer_aaas" / "composer_service.cpp"
        self.assertTrue(src_file.exists())
        content = src_file.read_text(encoding="utf-8")

        self.assertIn("#define AAAS_DISPLAY_WIDTH 1280", content)
        self.assertIn("#define AAAS_DISPLAY_HEIGHT 720", content)
        self.assertIn("int32_t width = AAAS_DISPLAY_WIDTH", content)
        self.assertIn("int32_t height = AAAS_DISPLAY_HEIGHT", content)
        self.assertIn("width = virtual_state->width", content)
        self.assertIn("height = virtual_state->height", content)
        self.assertIn("cfg.width = width", content)
        self.assertIn("cfg.height = height", content)
        self.assertIn("cfg.vsyncPeriod = 16666666", content)
        self.assertIn("DisplayConnectionType::INTERNAL", content)

    def test_surfaceflinger_aidl_publication(self):
        """Verify logcat evidence of display connection and SurfaceFlingerAIDL publication."""
        logcat_file = EXTERNAL_TMP / "m1b6_hotplug_full_logcat.log"
        if not logcat_file.exists():
            self.skipTest(f"Logcat verification file not found at {logcat_file}")

        content = logcat_file.read_text(encoding="utf-8", errors="ignore")

        # SurfaceFlinger display connection
        self.assertIn("Connecting display", content)
        self.assertIn("HWComposer: Switching to generalized multi-display mode", content)

        # Service publication
        self.assertIn("SurfaceFlingerAIDL", content)

        # Framework advancement
        self.assertIn("Starting com.android.server.display.DisplayManagerService", content)
        self.assertIn("StartPackageManagerService", content)

    def test_zygote_startup_composer_overlay(self):
        """Verify test_zygote_startup.py supports AaaS Composer3 overlay bind."""
        script_path = WORKSPACE_ROOT / "scripts" / "test_zygote_startup.py"
        self.assertTrue(script_path.exists())
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("AAAS_USE_AAAS_COMPOSER", content)
        self.assertIn("android.hardware.graphics.composer3-service.aaas", content)
        self.assertIn("/vendor/bin/hw/android.hardware.graphics.composer3-service.ranchu", content)


if __name__ == "__main__":
    unittest.main()
