#!/usr/bin/env python3
import os
import zipfile
import math
import shutil
from PIL import Image, ImageDraw

def generate_bootanimation(output_zip: str):
    tmp_dir = "/tmp/bootanim_gen"
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(f"{tmp_dir}/part0", exist_ok=True)

    w, h = 1280, 720
    num_frames = 60

    for i in range(num_frames):
        img = Image.new("RGB", (w, h), (11, 15, 25))
        draw = ImageDraw.Draw(img)

        cx, cy = w // 2, h // 2 - 40
        t = i / num_frames

        # Pulsing glow ring
        glow_r = int(140 + 20 * math.sin(2 * math.pi * t))
        for r in range(glow_r, glow_r - 40, -4):
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(61, 220, 132))

        # Orbiting dots
        for dot_idx in range(4):
            angle = 2 * math.pi * (t + dot_idx / 4.0)
            orbit_r = 170
            dx = int(cx + orbit_r * math.cos(angle))
            dy = int(cy + orbit_r * math.sin(angle))
            draw.ellipse([dx - 8, dy - 8, dx + 8, dy + 8], fill=(53, 218, 140))

        # Android Head (Dome)
        head_r = 90
        draw.pieslice([cx - head_r, cy - head_r, cx + head_r, cy + head_r], 180, 360, fill=(61, 220, 132))

        # Eyes
        eye_offset_x = 35
        eye_y = cy - 45
        eye_r = 8
        draw.ellipse([cx - eye_offset_x - eye_r, eye_y - eye_r, cx - eye_offset_x + eye_r, eye_y + eye_r], fill=(11, 15, 25))
        draw.ellipse([cx + eye_offset_x - eye_r, eye_y - eye_r, cx + eye_offset_x + eye_r, eye_y + eye_r], fill=(11, 15, 25))

        # Antennae
        draw.line([cx - 45, cy - 80, cx - 65, cy - 120], fill=(61, 220, 132), width=7)
        draw.line([cx + 45, cy - 80, cx + 65, cy - 120], fill=(61, 220, 132), width=7)

        # Labels
        text_y = cy + 120
        draw.text((cx - 70, text_y), "android 16", fill=(240, 246, 252))
        draw.text((cx - 110, text_y + 35), "Android-as-a-Service", fill=(61, 220, 132))

        img.save(f"{tmp_dir}/part0/{i:05d}.png")

    with open(f"{tmp_dir}/desc.txt", "w") as f:
        f.write("1280 720 30\np 0 0 part0\n")

    os.makedirs(os.path.dirname(os.path.abspath(output_zip)), exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.write(f"{tmp_dir}/desc.txt", "desc.txt")
        for f in sorted(os.listdir(f"{tmp_dir}/part0")):
            zf.write(f"{tmp_dir}/part0/{f}", f"part0/{f}")

    os.chmod(output_zip, 0o644)
    shutil.rmtree(tmp_dir)

if __name__ == "__main__":
    dst = "/run/media/mrkus/Homework/aaas-workspace/rootfs_m1b1/system/media/bootanimation.zip"
    generate_bootanimation(dst)
    print("Generated:", dst)
