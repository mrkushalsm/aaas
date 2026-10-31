import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "build_m1e_transition_input_overlay",
    ROOT / "scripts/build_m1e_transition_input_overlay.py",
)
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)
sys.path.insert(0, str(ROOT / "scripts"))
import run_aaas as RUNNER


class TransitionInputPatchTests(unittest.TestCase):
    def test_view_root_holds_one_transition_key_and_finishes_on_detach(self):
        source = """.field greylist-max-o mPausedForTransition:Z
.method public greylist-max-o setPausedForTransition(Z)V
    .locals 0
    .param p1, \"paused\"    # Z

    .line 2928
    iput-boolean p1, p0, Landroid/view/ViewRootImpl;->mPausedForTransition:Z

    .line 2929
    return-void
.end method
.method greylist-max-o dispatchDetachedFromWindow()V
    .locals 3

    .line 6582
    iget-object v0, p0, Landroid/view/ViewRootImpl;->mInsetsController:Landroid/view/InsetsController;
"""
        patched = PATCH.patch_view_root(source)
        self.assertIn("mAaasPendingTransitionKey", patched)
        self.assertIn("finishAaasTransitionKey(Z)", patched)
        self.assertIn("finishInputEvent(Landroid/view/ViewRootImpl$QueuedInputEvent;)", patched)
        self.assertIn("mAdded:Z", patched)
        self.assertIn("mHasWindowFocus:Z", patched)
        self.assertIn("mStopped:Z", patched)
        self.assertIn(".locals 4\n    .param p1, \"deliver\"", patched)
        self.assertEqual(patched.count("finishAaasTransitionKey(Z)"), 3)
        self.assertEqual(patched.count("invoke-virtual {p0, v0}, Landroid/view/ViewRootImpl;->finishAaasTransitionKey(Z)V"), 2)
        self.assertNotIn("invoke-direct {p0, v0}, Landroid/view/ViewRootImpl;->finishAaasTransitionKey(Z)V", patched)

    def test_input_stage_defers_only_focused_secondary_display_key(self):
        source = """.method public final greylist-max-o deliver(Landroid/view/ViewRootImpl$QueuedInputEvent;)V
    .locals 3
    .param p1, \"q\"    # Landroid/view/ViewRootImpl$QueuedInputEvent;

    iget v0, p1, Landroid/view/ViewRootImpl$QueuedInputEvent;->mFlags:I
    and-int/lit8 v0, v0, 0x4
    if-eqz v0, :cond_0
    invoke-virtual {p0, p1}, Landroid/view/ViewRootImpl$InputStage;->forward(Landroid/view/ViewRootImpl$QueuedInputEvent;)V
    goto :goto_0
    :cond_0
    invoke-virtual {p0, p1}, Landroid/view/ViewRootImpl$InputStage;->shouldDropInputEvent(Landroid/view/ViewRootImpl$QueuedInputEvent;)Z
    move-result v0
.end method
"""
        patched = PATCH.patch_input_stage(source)
        self.assertIn("instance-of v1, v1, Landroid/view/KeyEvent;", patched)
        self.assertIn("if-lez v1, :aaas_check_drop", patched)
        self.assertIn("mHasWindowFocus:Z", patched)
        self.assertIn("iput-object p1, v0, Landroid/view/ViewRootImpl;->mAaasPendingTransitionKey", patched)
        self.assertIn("ViewRootImpl$AaasTransitionKeyTimeout", patched)
        self.assertIn("const-wide/16 v3, 0x3e8", patched)
        self.assertLess(patched.index("iput-object p1, v0"),
                        patched.index("shouldDropInputEvent"))

    def test_patch_rejects_unrecognized_framework_source(self):
        with self.assertRaises(RuntimeError):
            PATCH.patch_input_stage(".method deliver()V\n.end method")

    def test_timeout_helper_has_valid_constructor_and_virtual_callback(self):
        helper = PATCH.TIMEOUT_HELPER
        super_call = "invoke-direct {p0}, Ljava/lang/Object;-><init>()V"
        field_write = "iput-object p1, p0, Landroid/view/ViewRootImpl$AaasTransitionKeyTimeout;->mRoot"
        self.assertLess(helper.index(super_call), helper.index(field_write))
        self.assertIn("invoke-virtual {v0, v1}, Landroid/view/ViewRootImpl;->finishAaasTransitionKey(Z)V", helper)

    def test_default_framework_overlay_receipt_rejects_stale_inputs(self):
        digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            source = workspace / "rootfs_m1b1/system/framework/framework.jar"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"framework")
            apktool = root / "apktool.jar"
            apktool.write_bytes(b"apktool")
            builder = root / "builder.py"
            builder.write_bytes(b"builder")
            overlay = root / "transition.jar"
            overlay.write_bytes(b"overlay")
            receipt_path = root / "transition.json"
            receipt_path.write_text(json.dumps({
                "revision": "99b01a65cc4c104933788b3143285ab6bae65827",
                "input": str(source.resolve()),
                "input_sha256": digest(source),
                "apktool_sha256": digest(apktool),
                "builder": str(builder.resolve()),
                "builder_sha256": digest(builder),
                "overlay": str(overlay.resolve()),
                "overlay_sha256": digest(overlay),
            }))
            with (patch.object(RUNNER, "WORKSPACE", workspace),
                  patch.object(RUNNER, "APKTOOL", apktool),
                  patch.object(RUNNER, "FRAMEWORK_TRANSITION_BUILDER", builder),
                  patch.object(RUNNER, "FRAMEWORK_TRANSITION_OVERLAY", overlay),
                  patch.object(RUNNER, "FRAMEWORK_TRANSITION_RECEIPT", receipt_path)):
                self.assertTrue(RUNNER.framework_transition_overlay_is_current())
                builder.write_bytes(b"changed builder")
                self.assertFalse(RUNNER.framework_transition_overlay_is_current())


if __name__ == "__main__":
    unittest.main()
