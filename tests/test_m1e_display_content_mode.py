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

    def test_alarm_fallback_uses_listener_aware_delivery(self):
        source = '''    invoke-static {v0}, Lcom/android/server/alarm/AlarmManagerService;->-$$Nest$mupdateNextAlarmClockLocked(Lcom/android/server/alarm/AlarmManagerService;)V

    .line 4725
    monitor-exit v4
    :try_end_3
    .catchall {:try_start_3 .. :try_end_3} :catchall_3

    .line 4728
    :goto_4
    invoke-virtual {p1}, Ljava/util/ArrayList;->size()I
    move-result v0
    if-ge v2, v0, :cond_4
    invoke-virtual {v5, v6}, Landroid/app/PendingIntent;->isActivity()Z
    goto :goto_4

    :cond_4
    :goto_6
    return-void'''
        patched = PATCHER.patch_alarm_fallback(source)
        self.assertIn(
            "deliverAlarmsLocked(Ljava/util/ArrayList;J)V", patched)
        self.assertIn("rescheduleKernelAlarmsLocked()V", patched)
        self.assertNotIn("PendingIntent;->isActivity()Z", patched)
        self.assertNotIn(":goto_4", patched)
        self.assertIn(":cond_4", patched)
        self.assertIn(":goto_6", patched)

    def test_alarm_fallback_patch_rejects_unexpected_or_repeated_input(self):
        with self.assertRaisesRegex(RuntimeError, "synchronization block"):
            PATCHER.patch_alarm_fallback(".method public handleMessage()V\n.end method")
        with self.assertRaisesRegex(RuntimeError, "already applied"):
            PATCHER.patch_alarm_fallback(
                PATCHER.ALARM_TRIGGER + "\n" +
                PATCHER.ALARM_LOOP_START + "\n" +
                "deliverAlarmsLocked(Ljava/util/ArrayList;J)V\n" +
                PATCHER.ALARM_LOOP_END)


if __name__ == "__main__":
    unittest.main()
