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

import sys

def try_raise_and_capture(log_name="m1b7_live18_presenter.log"):
    log_path = f"/run/media/mrkus/Aaas/aaas-workspace/tmp/{log_name}"
    captured = False
    for attempt in range(60):
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
            
            if os.path.exists(log_path):
                with open(log_path, "r") as lf:
                    content = lf.read()
                    count = content.count("frame_committed")
                    if count >= 3 or (count >= 1 and attempt >= 14):
                        time.sleep(2.0)
                        # Capture active window
                        subprocess.run(["spectacle", "-a", "-b", "-n", "-o", ARTIFACT_PATH], check=True)
                        print("CAPTURED_ACTIVE_WINDOW")
                        # Also capture full desktop as backup
                        subprocess.run(["spectacle", "-b", "-n", "-o", "/home/mrkus/Work/personal/projects/aaas/artifacts/m1b7_desktop_frame.png"], check=True)
                        print("CAPTURED_DESKTOP")
                        captured = True
                        return True
        except Exception as e:
            pass
    return False

if __name__ == "__main__":
    log_arg = sys.argv[1] if len(sys.argv) > 1 else "m1b7_live18_presenter.log"
    if try_raise_and_capture(log_arg):
        print("SUCCESS")
    else:
        print("TIMEOUT")
