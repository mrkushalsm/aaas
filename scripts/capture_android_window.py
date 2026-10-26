#!/usr/bin/env python3
import time
import subprocess
import os

ARTIFACT_PATH = "/home/mrkus/Work/personal/projects/aaas/artifacts/m1b7_android_frame.png"
SCRIPT_JS = "/tmp/kwin_raise_aaas.js"

kwin_js = """
let wins = workspace.windowList();
let found = false;
for (let w of wins) {
    if (w.caption && (w.caption.indexOf('Android') !== -1 || w.caption.indexOf('AaaS') !== -1)) {
        w.keepAbove = true;
        workspace.activeWindow = w;
        found = true;
    }
}
found;
"""

with open(SCRIPT_JS, "w") as f:
    f.write(kwin_js)

def try_raise_and_capture():
    for _ in range(60):
        time.sleep(0.5)
        try:
            num = subprocess.check_output(
                ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript", SCRIPT_JS, "aaas_raise"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            
            subprocess.run(["qdbus6", "org.kde.KWin", f"/Scripting/Script{num}", "org.kde.kwin.Script.run"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", "aaas_raise"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Check presenter log to see if a frame was committed/presented
            log_path = "/run/media/mrkus/Homework/aaas-workspace/tmp/m1b7_live17_presenter.log"
            if os.path.exists(log_path):
                with open(log_path, "r") as lf:
                    content = lf.read()
                    if "frame_presented" in content or "frame_committed" in content:
                        time.sleep(0.2)
                        # Capture active window
                        subprocess.run(["spectacle", "-a", "-b", "-n", "-o", ARTIFACT_PATH], check=True)
                        print("CAPTURED_ACTIVE_WINDOW")
                        # Also capture full desktop as backup
                        subprocess.run(["spectacle", "-b", "-n", "-o", "/home/mrkus/Work/personal/projects/aaas/artifacts/m1b7_desktop_frame.png"], check=True)
                        print("CAPTURED_DESKTOP")
                        return True
        except Exception as e:
            pass
    return False

if __name__ == "__main__":
    if try_raise_and_capture():
        print("SUCCESS")
    else:
        print("TIMEOUT")
