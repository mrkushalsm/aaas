#!/usr/bin/env python3
"""Build an isolated Android 16 framework overlay that defers focused keys
while a secondary-display ViewRoot is paused for an Activity transition.

The modified framework JAR is never replaced in place. Input events remain in
their original ViewRoot and are delivered once transition pause clears; if that
ViewRoot detaches first, its pending event is finished as unhandled.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from patch_m1d_desktop_ime import patch_smali_method


PINNED_FRAMEWORK_SHA256 = "9430cd45f370bc95b5cdab0274bb8e885ae163660ba9dd7cd7ed4847b635fed0"
PINNED_APKTOOL_SHA256 = "dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423"
REVISION = "99b01a65cc4c104933788b3143285ab6bae65827"
VRI_PATH = Path("smali_classes4/android/view/ViewRootImpl.smali")
STAGE_PATH = Path("smali_classes4/android/view/ViewRootImpl$InputStage.smali")
IME_PATH = Path("smali_classes2/android/inputmethodservice/InputMethodService.smali")
FIELD = ".field mAaasPendingTransitionKey:Landroid/view/ViewRootImpl$QueuedInputEvent;\n\n"
HELPER = """\n.method blacklist finishAaasTransitionKey(Z)V
    .locals 4
    .param p1, \"deliver\"    # Z

    iget-object v0, p0, Landroid/view/ViewRootImpl;->mAaasPendingTransitionKey:Landroid/view/ViewRootImpl$QueuedInputEvent;
    if-eqz v0, :return
    const/4 v1, 0x0
    iput-object v1, p0, Landroid/view/ViewRootImpl;->mAaasPendingTransitionKey:Landroid/view/ViewRootImpl$QueuedInputEvent;
    if-eqz p1, :finish
    iget-boolean v1, p0, Landroid/view/ViewRootImpl;->mAdded:Z
    if-eqz v1, :finish
    iget-object v1, p0, Landroid/view/ViewRootImpl;->mAttachInfo:Landroid/view/View$AttachInfo;
    if-eqz v1, :finish
    iget-boolean v1, v1, Landroid/view/View$AttachInfo;->mHasWindowFocus:Z
    if-eqz v1, :finish
    iget-boolean v1, p0, Landroid/view/ViewRootImpl;->mStopped:Z
    if-nez v1, :finish
    const-string v1, "AAASInputTransition"
    const-string v2, "resuming retained key in original ViewRoot"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    iget-object v1, p0, Landroid/view/ViewRootImpl;->mFirstInputStage:Landroid/view/ViewRootImpl$InputStage;
    if-eqz v1, :finish
    invoke-virtual {v1, v0}, Landroid/view/ViewRootImpl$InputStage;->deliver(Landroid/view/ViewRootImpl$QueuedInputEvent;)V
    goto :return
    :finish
    const-string v1, "AAASInputTransition"
    const-string v2, "finishing retained key without redelivery"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    invoke-direct {p0, v0}, Landroid/view/ViewRootImpl;->finishInputEvent(Landroid/view/ViewRootImpl$QueuedInputEvent;)V
    :return
    return-void
.end method
"""
TIMEOUT_HELPER = """.class final Landroid/view/ViewRootImpl$AaasTransitionKeyTimeout;
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;

.field private final mRoot:Landroid/view/ViewRootImpl;

.method constructor <init>(Landroid/view/ViewRootImpl;)V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Landroid/view/ViewRootImpl$AaasTransitionKeyTimeout;->mRoot:Landroid/view/ViewRootImpl;
    return-void
.end method

.method public run()V
    .locals 2
    iget-object v0, p0, Landroid/view/ViewRootImpl$AaasTransitionKeyTimeout;->mRoot:Landroid/view/ViewRootImpl;
    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Landroid/view/ViewRootImpl;->finishAaasTransitionKey(Z)V
    return-void
.end method
"""


def replace_once(source, old, new, label):
    if source.count(old) != 1:
        raise RuntimeError(f"pinned framework smali mismatch: {label}")
    return source.replace(old, new, 1)


def patch_view_root(source):
    if "mAaasPendingTransitionKey" in source:
        raise RuntimeError("transition input patch already applied")
    marker = ".field greylist-max-o mPausedForTransition:Z\n"
    source = replace_once(source, marker, marker + FIELD, "VRI field")
    setter = """.method public greylist-max-o setPausedForTransition(Z)V
    .locals 0
    .param p1, \"paused\"    # Z

    .line 2928
    iput-boolean p1, p0, Landroid/view/ViewRootImpl;->mPausedForTransition:Z

    .line 2929
    return-void
.end method"""
    setter_new = """.method public greylist-max-o setPausedForTransition(Z)V
    .locals 1
    .param p1, \"paused\"    # Z

    .line 2928
    iput-boolean p1, p0, Landroid/view/ViewRootImpl;->mPausedForTransition:Z
    if-nez p1, :return
    const/4 v0, 0x1
    invoke-virtual {p0, v0}, Landroid/view/ViewRootImpl;->finishAaasTransitionKey(Z)V
    .line 2929
    :return
    return-void
.end method"""
    source = replace_once(source, setter, setter_new, "transition pause setter")
    detach = ".method greylist-max-o dispatchDetachedFromWindow()V\n    .locals 3\n\n    .line 6582"
    detach_new = ".method greylist-max-o dispatchDetachedFromWindow()V\n    .locals 3\n\n    const/4 v0, 0x0\n    invoke-virtual {p0, v0}, Landroid/view/ViewRootImpl;->finishAaasTransitionKey(Z)V\n    .line 6582"
    source = replace_once(source, detach, detach_new, "detach cleanup")
    return source + HELPER


def patch_input_stage(source):
    if "mAaasPendingTransitionKey" in source:
        raise RuntimeError("transition input patch already applied")
    method = ".method public final greylist-max-o deliver(Landroid/view/ViewRootImpl$QueuedInputEvent;)V"
    if source.count(method) != 1:
        raise RuntimeError("pinned framework smali mismatch: InputStage.deliver")
    start = source.index(method)
    end = source.index(".end method", start) + len(".end method")
    body = source[start:end]
    body = replace_once(body, "    .locals 3\n", "    .locals 5\n", "input stage local count")
    old = """    :cond_0
    invoke-virtual {p0, p1}, Landroid/view/ViewRootImpl$InputStage;->shouldDropInputEvent(Landroid/view/ViewRootImpl$QueuedInputEvent;)Z
"""
    defer = """    :cond_0
    # Defer one focused key on a secondary display while this ViewRoot is
    # paused for a framework Activity transition. InputDispatcher serializes
    # key delivery until this QueuedInputEvent is finished.
    iget-object v0, p0, Landroid/view/ViewRootImpl$InputStage;->this$0:Landroid/view/ViewRootImpl;
    iget-boolean v1, v0, Landroid/view/ViewRootImpl;->mPausedForTransition:Z
    if-eqz v1, :aaas_check_drop
    iget-object v1, p1, Landroid/view/ViewRootImpl$QueuedInputEvent;->mEvent:Landroid/view/InputEvent;
    instance-of v1, v1, Landroid/view/KeyEvent;
    if-eqz v1, :aaas_check_drop
    iget-object v1, v0, Landroid/view/ViewRootImpl;->mDisplay:Landroid/view/Display;
    if-eqz v1, :aaas_check_drop
    invoke-virtual {v1}, Landroid/view/Display;->getDisplayId()I
    move-result v1
    if-lez v1, :aaas_check_drop
    iget-object v1, v0, Landroid/view/ViewRootImpl;->mView:Landroid/view/View;
    if-eqz v1, :aaas_check_drop
    iget-boolean v1, v0, Landroid/view/ViewRootImpl;->mAdded:Z
    if-eqz v1, :aaas_check_drop
    iget-object v1, v0, Landroid/view/ViewRootImpl;->mAttachInfo:Landroid/view/View$AttachInfo;
    iget-boolean v1, v1, Landroid/view/View$AttachInfo;->mHasWindowFocus:Z
    if-eqz v1, :aaas_check_drop
    iget-boolean v1, v0, Landroid/view/ViewRootImpl;->mStopped:Z
    if-nez v1, :aaas_check_drop
    iget-boolean v1, v0, Landroid/view/ViewRootImpl;->mIsAmbientMode:Z
    if-nez v1, :aaas_check_drop
    iget-object v1, v0, Landroid/view/ViewRootImpl;->mAaasPendingTransitionKey:Landroid/view/ViewRootImpl$QueuedInputEvent;
    if-nez v1, :aaas_check_drop
    const-string v1, "AAASInputTransition"
    const-string v2, "retaining focused secondary-display key during transition"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    iput-object p1, v0, Landroid/view/ViewRootImpl;->mAaasPendingTransitionKey:Landroid/view/ViewRootImpl$QueuedInputEvent;
    new-instance v1, Landroid/view/ViewRootImpl$AaasTransitionKeyTimeout;
    invoke-direct {v1, v0}, Landroid/view/ViewRootImpl$AaasTransitionKeyTimeout;-><init>(Landroid/view/ViewRootImpl;)V
    iget-object v2, v0, Landroid/view/ViewRootImpl;->mHandler:Landroid/view/ViewRootImpl$ViewRootHandler;
    const-wide/16 v3, 0x3e8
    invoke-virtual {v2, v1, v3, v4}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z
    move-result v1
    return-void
    :aaas_check_drop
    invoke-virtual {p0, p1}, Landroid/view/ViewRootImpl$InputStage;->shouldDropInputEvent(Landroid/view/ViewRootImpl$QueuedInputEvent;)Z
"""
    body = replace_once(body, old, defer, "focused transition-key deferral")
    return source[:start] + body + source[end:]


def patch_sources(decoded):
    vri = decoded / VRI_PATH
    stage = decoded / STAGE_PATH
    ime = decoded / IME_PATH
    if not all(path.is_file() for path in (vri, stage, ime)):
        raise RuntimeError("pinned framework dex classes are missing")
    vri.write_text(patch_view_root(vri.read_text()))
    stage.write_text(patch_input_stage(stage.read_text()))
    ime.write_text(patch_smali_method(ime.read_text()))
    timeout = decoded / Path("smali_classes4/android/view/ViewRootImpl$AaasTransitionKeyTimeout.smali")
    timeout.write_text(TIMEOUT_HELPER)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build(original, apktool, output, work_parent):
    original, apktool, output = map(lambda p: Path(p).resolve(), (original, apktool, output))
    if original == output or sha256(original) != PINNED_FRAMEWORK_SHA256:
        raise ValueError("framework input must be the immutable pinned Android 16 JAR")
    if sha256(apktool) != PINNED_APKTOOL_SHA256:
        raise ValueError("apktool hash does not match pinned version")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aaas-m1e-transition-", dir=work_parent) as temp:
        temp = Path(temp)
        decoded, rebuilt = temp / "decoded", temp / "rebuilt.apk"
        subprocess.run(["java", "-jar", str(apktool), "d", "-f", "-r",
                        str(original), "-o", str(decoded)], check=True)
        patch_sources(decoded)
        subprocess.run(["java", "-jar", str(apktool), "b", str(decoded),
                        "-o", str(rebuilt)], check=True)
        with zipfile.ZipFile(rebuilt) as package:
            replacements = {name: package.read(name) for name in
                            ("classes2.dex", "classes4.dex")}
        staged = output.with_suffix(output.suffix + ".tmp")
        with zipfile.ZipFile(original) as source, zipfile.ZipFile(staged, "w") as target:
            for info in source.infolist():
                target.writestr(info, replacements.get(info.filename, source.read(info.filename)))
        os.replace(staged, output)
    return {"revision": REVISION, "input": str(original),
            "input_sha256": sha256(original), "apktool_sha256": sha256(apktool),
            "builder": str(Path(__file__).resolve()),
            "builder_sha256": sha256(__file__),
            "overlay": str(output), "overlay_sha256": sha256(output),
            "changed_entries": ["classes2.dex", "classes4.dex"],
            "behavior": "retain at most one focused KeyEvent in its original non-primary ViewRoot during Activity transition pause; resume only while attached and focused, otherwise finish unhandled; expire after 1000ms"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--apktool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-parent", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = build(args.original, args.apktool, args.output, args.work_parent)
    rendered = json.dumps(receipt, indent=2) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
