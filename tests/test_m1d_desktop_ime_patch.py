"""Focused tests for the source-guarded Android desktop IME DEX patch."""

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/patch_m1d_desktop_ime.py'
SPEC = importlib.util.spec_from_file_location('patch_m1d_desktop_ime', SCRIPT)
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)


class DesktopImePatchTests(unittest.TestCase):
    def test_desktop_policy_returns_false_before_android_default(self):
        source = '''.method public whitelist onEvaluateInputViewShown()Z
    .locals 5

    const/4 v0, 0x0
    return v0
.end method
'''
        result = PATCH.patch_smali_method(source)
        self.assertIn('Settings$Secure;->getInt(', result)
        self.assertIn('"aaas_desktop_mode"', result)
        self.assertIn('if-eqz v0, :aaas_desktop_mode_disabled', result)
        self.assertIn(':aaas_desktop_mode_disabled', result)
        branch = result.index('if-eqz v0, :aaas_desktop_mode_disabled')
        disabled_label = result.index('\n    :aaas_desktop_mode_disabled')
        self.assertLess(branch, disabled_label)
        self.assertLess(branch, result.index('return v0', branch))
        self.assertLess(result.index('return v0', branch), disabled_label)

    def test_unexpected_method_shape_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'register layout mismatch'):
            PATCH.patch_smali_method(
                '.method public whitelist onEvaluateInputViewShown()Z\n'
                '    .locals 4\n.end method\n')

    def test_reproducible_source_patch_targets_aosp_visibility_hook(self):
        patch = PATCH.SOURCE_PATCH.read_text()
        self.assertIn('public boolean onEvaluateInputViewShown()', patch)
        self.assertIn('Settings.Secure.getInt(getContentResolver(), "aaas_desktop_mode", 0)', patch)
        self.assertIn('return false;', patch)
        self.assertEqual(PATCH.AOSP_SOURCE_REVISION,
                         '99b01a65cc4c104933788b3143285ab6bae65827')

    def test_source_patch_hunk_counts_are_well_formed(self):
        import re
        patch = PATCH.SOURCE_PATCH.read_text().splitlines()
        header = next(line for line in patch if line.startswith('@@ '))
        match = re.fullmatch(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', header)
        self.assertIsNotNone(match)
        old_count = new_count = 0
        for line in patch[patch.index(header) + 1:]:
            if line.startswith('--- ') or line.startswith('+++ '):
                continue
            if line.startswith(' '):
                old_count += 1
                new_count += 1
            elif line.startswith('-'):
                old_count += 1
            elif line.startswith('+'):
                new_count += 1
        self.assertEqual(old_count, int(match.group(2)))
        self.assertEqual(new_count, int(match.group(4)))

    def test_duplicate_application_is_rejected(self):
        source = '''.method public whitelist onEvaluateInputViewShown()Z
    .locals 5
    const-string v0, "aaas_desktop_mode"
.end method
'''
        with self.assertRaisesRegex(RuntimeError, 'already present'):
            PATCH.patch_smali_method(source)


if __name__ == '__main__':
    unittest.main()
