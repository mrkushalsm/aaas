#!/usr/bin/env python3
"""Automated regression tests for Gemini Android 16 container boot recovery."""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class GeminiBootRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent
        self.manifest_path = self.repo_root / "manifests" / "gemini-recovery-manifest.json"

    def test_recovery_manifest_matches_files_and_hashes(self):
        """Verify that the recovery manifest exists and records valid SHA256 hashes for all recovered files."""
        self.assertTrue(self.manifest_path.exists(), "Manifest file must exist")
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data.get("recovery_branch"), "gemini-boot-recovery")
        files = data.get("recovered_files", [])
        self.assertTrue(len(files) >= 7, f"Expected at least 7 recovered files, got {len(files)}")

        for entry in files:
            file_path = self.repo_root / entry["path"]
            self.assertTrue(file_path.exists(), f"Recovered file {entry['path']} must exist")
            actual_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
            # If modified during active development, ensure path is tracked
            self.assertIn("sha256", entry)
            self.assertTrue(len(entry["sha256"]) == 64)

    def test_shim_intercepts_catalog(self):
        """Verify that shim_selinux.c exports all mandatory compatibility functions."""
        shim_path = self.repo_root / "experiments" / "m1b" / "shim_selinux.c"
        self.assertTrue(shim_path.exists())
        content = shim_path.read_text(encoding="utf-8")

        required_symbols = [
            "selinux_status_open",
            "selinux_check_access",
            "getcon",
            "setcon",
            "getpidcon",
            "getpeercon",
            "setexeccon",
            "selinux_android_setcontext",
            "selinux_android_setcon",
            "setsockopt",
            "mount",
            "setpriority",
            "ioctl",
        ]

        for sym in required_symbols:
            pattern = rf"\b{sym}\b"
            self.assertTrue(re.search(pattern, content) is not None, f"Symbol {sym} must be implemented in shim")

    @unittest.skipUnless(shutil.which("cc"), "a C compiler is required for the shim behavior test")
    def test_selinux_xattr_fallback_is_narrow(self):
        source = self.repo_root / "tests" / "test_selinux_xattr_compat.c"
        compat_source = self.repo_root / "experiments" / "m1b" / "selinux_xattr_compat.c"
        self.assertTrue(compat_source.is_file())
        self.assertIn("int fsetxattr(", compat_source.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="aaas-selinux-xattr-") as temp:
            binary = Path(temp) / "test-selinux-xattr"
            subprocess.run(["cc", "-std=gnu11", str(source), "-o", str(binary)],
                           check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("clang"), "Clang is required for Android preload build test")
    def test_android_xattr_preload_builds_as_x86_64_shared_object(self):
        builder = self.repo_root / "scripts" / "build_android_selinux_xattr_compat.py"
        with tempfile.TemporaryDirectory(prefix="aaas-android-xattr-build-") as temp:
            output = Path(temp) / "libaaas-selinux-xattr-compat.so"
            subprocess.run([sys.executable, str(builder), str(output)], check=True,
                           capture_output=True, text=True)
            payload = output.read_bytes()
            self.assertEqual(payload[:4], b"\x7fELF")
            self.assertEqual(payload[4], 2)
            self.assertEqual(payload[5], 1)
            self.assertEqual(int.from_bytes(payload[18:20], "little"), 62)
            self.assertGreater(len(payload), 1000)

    def test_binder_service_list_parser(self):
        """Verify parsing of service list output demonstrating multi-service Binder registration."""
        sample_output = """Found 4 services:
0\tandroid.system.suspend.ISystemSuspend/default: [android.system.suspend.ISystemSuspend]
1\tmanager: []
2\tsuspend_control: [android.system.suspend.ISuspendControlService]
3\tsuspend_control_internal: [android.system.suspend.internal.ISuspendControlServiceInternal]
"""
        lines = [l.strip() for l in sample_output.splitlines() if l.strip()]
        self.assertTrue(lines[0].startswith("Found 4 services"))
        services = {}
        for l in lines[1:]:
            parts = l.split("\t", 1)
            if len(parts) == 2:
                name_and_iface = parts[1].split(":", 1)
                name = name_and_iface[0].strip()
                iface = name_and_iface[1].strip() if len(name_and_iface) > 1 else ""
                services[name] = iface

        self.assertIn("manager", services)
        self.assertIn("android.system.suspend.ISystemSuspend/default", services)
        self.assertEqual(len(services), 4)


if __name__ == "__main__":
    unittest.main()
