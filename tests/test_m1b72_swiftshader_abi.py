"""Regression for the Android SwiftShader shared_ptr double destruction."""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / "experiments/m1b/swiftshader/bionic_stubs.cpp"


class SwiftShaderBionicAbiTest(unittest.TestCase):
    def test_single_threaded_hint_is_zero_in_compiled_shim(self):
        if not shutil.which("g++") or not shutil.which("objdump"):
            self.skipTest("C++ compiler and objdump required")
        with tempfile.TemporaryDirectory() as directory:
            obj = Path(directory) / "bionic_stubs.o"
            subprocess.run(["g++", "-fPIC", "-O2", "-c", str(SHIM), "-o", str(obj)], check=True)
            symbols = subprocess.check_output(["objdump", "-t", str(obj)], text=True)
            match = re.search(r"^.*\s\.bss\s+0000000000000001\s+__libc_single_threaded$", symbols, re.M)
            self.assertIsNotNone(match, "the threading hint must be zero initialized")


if __name__ == "__main__":
    unittest.main()
