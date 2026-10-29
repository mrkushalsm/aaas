import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/patch_m1e_display_content_mode.py"
SPEC = importlib.util.spec_from_file_location("m1e_display_patch", SCRIPT)
PATCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHER)


class DisplayContentModePatchTests(unittest.TestCase):
    def test_only_pinned_method_gains_explicit_opt_in(self):
        source = '''.method public isDisplayContentModeManagementEnabled()Z
    .locals 0
    iget-object p0, p0, Lcom/android/server/display/feature/DisplayManagerFlags;->mEnableDisplayContentModeManagementFlagState:Lcom/android/server/display/feature/DisplayManagerFlags$FlagState;
    invoke-static {p0}, Lcom/android/server/display/feature/DisplayManagerFlags$FlagState;->-$$Nest$misEnabled(Lcom/android/server/display/feature/DisplayManagerFlags$FlagState;)Z
    move-result p0
    return p0
.end method'''
        patched = PATCHER.patch_smali(source)
        self.assertIn('"debug.aaas.display_content_mode_management"', patched)
        self.assertIn("mEnableDisplayContentModeManagementFlagState", patched)
        self.assertIn("if-nez v0, :aaas_display_content_mode_enabled", patched)

    def test_patch_rejects_unexpected_or_already_patched_method(self):
        with self.assertRaisesRegex(RuntimeError, "signature mismatch"):
            PATCHER.patch_smali(".method public other()Z\n.end method")
        with self.assertRaisesRegex(RuntimeError, "already applied"):
            PATCHER.patch_smali(PATCHER.BODY)


if __name__ == "__main__":
    unittest.main()
