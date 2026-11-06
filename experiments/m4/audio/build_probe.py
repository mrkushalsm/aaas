#!/usr/bin/env python3
"""Build a normal Android app that plays one deterministic AudioTrack tone."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('apktool', 'framework-res', 'apksig', 'dx', 'zipalign', 'keystore', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('apktool', 'framework-res', 'apksig', 'dx', 'zipalign', 'keystore'):
        value = getattr(args, name.replace('-', '_')).resolve(strict=True)
        setattr(args, name.replace('-', '_'), value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aaas-audio-probe-') as temp:
        work = Path(temp)
        stubs = {
            'android/app/Activity.java': '''package android.app; public class Activity extends android.content.Context { protected void onCreate(android.os.Bundle b){} public void setContentView(android.view.View v){} }''',
            'android/content/Context.java': '''package android.content; public class Context { public static final String AUDIO_SERVICE="audio"; public Object getSystemService(String n){return null;} }''',
            'android/os/Bundle.java': '''package android.os; public class Bundle {}''',
            'android/util/Log.java': '''package android.util; public class Log { public static int i(String t,String m){return 0;} public static int e(String t,String m,Throwable x){return 0;} }''',
            'android/view/View.java': '''package android.view; public class View {}''',
            'android/widget/TextView.java': '''package android.widget; public class TextView extends android.view.View { public TextView(android.content.Context c){} public void setText(CharSequence s){} }''',
            'android/media/AudioManager.java': '''package android.media; public class AudioManager { public static final int STREAM_MUSIC=3; }''',
            'android/media/AudioFormat.java': '''package android.media; public class AudioFormat { public static final int CHANNEL_OUT_STEREO=12, ENCODING_PCM_16BIT=2; }''',
            'android/media/AudioTrack.java': '''package android.media; public class AudioTrack { public static final int MODE_STREAM=1; public AudioTrack(int s,int r,int c,int f,int b,int m){} public static int getMinBufferSize(int r,int c,int f){return 4096;} public void play(){} public int write(short[] a,int o,int n){return n;} public void stop(){} public void release(){} }''',
        }
        stubroot = work / 'stubs'
        for relative, text in stubs.items():
            path = stubroot / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        stubclasses = work / 'stubclasses'; stubclasses.mkdir()
        subprocess.run(['javac', '--release', '8', '-d', str(stubclasses),
                        *map(str, stubroot.rglob('*.java'))], check=True)
        classes = work / 'classes'; classes.mkdir()
        source = Path(__file__).resolve().parent / 'src-probe/org/aaas/audioprobe/MainActivity.java'
        subprocess.run(['javac', '--release', '8', '-cp', str(stubclasses),
                        '-d', str(classes), str(source)], check=True)
        dex = work / 'classes.dex'
        subprocess.run([str(args.dx), '--dex', f'--output={dex}', str(classes)], check=True)
        decoded = work / 'decoded'; (decoded / 'res').mkdir(parents=True)
        (decoded / 'AndroidManifest.xml').write_text('''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.aaas.audioprobe" android:versionCode="1" android:versionName="1.0">
<uses-sdk android:minSdkVersion="28" android:targetSdkVersion="35"/>
<application android:label="AaaS Audio Probe" android:allowBackup="false" android:hasCode="true"><activity android:name=".MainActivity" android:exported="true"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>''')
        (decoded / 'apktool.yml').write_text('''version: 3.0.3
apkFileName: AaasAudioProbe.apk
usesFramework:
  ids:
  - 1
sdkInfo:
  minSdkVersion: 28
  targetSdkVersion: 35
versionInfo:
  versionCode: 1
  versionName: 1.0
''')
        cache = work / 'framework-cache'; cache.mkdir()
        subprocess.run(['java', '-jar', str(args.apktool), 'if', str(args.framework_res), '-p', str(cache)], check=True)
        built = work / 'built.apk'
        subprocess.run(['java', '-jar', str(args.apktool), 'b', '-p', str(cache), '-o', str(built), str(decoded)], check=True)
        unsigned = work / 'unsigned.apk'
        with zipfile.ZipFile(built) as src, zipfile.ZipFile(unsigned, 'w') as dst:
            for item in src.infolist():
                if item.filename.startswith('META-INF/') or item.filename == 'classes.dex':
                    continue
                info = zipfile.ZipInfo(item.filename, item.date_time)
                info.external_attr = item.external_attr
                info.compress_type = zipfile.ZIP_STORED if item.filename == 'resources.arsc' else item.compress_type
                dst.writestr(info, src.read(item.filename))
            dst.write(dex, 'classes.dex')
        aligned = work / 'aligned.apk'
        subprocess.run([str(args.zipalign), '-f', '4', str(unsigned), str(aligned)], check=True)
        subprocess.run([str(args.zipalign), '-c', '4', str(aligned)], check=True)
        signer = ROOT / 'experiments/m4/shared_storage_probe/ApkSign.java'
        subprocess.run(['javac', '-cp', str(args.apksig), '-d', str(work), str(signer)], check=True)
        signed = work / 'signed.apk'
        subprocess.run(['java', '-cp', f'{work}:{args.apksig}', 'ApkSign', str(args.keystore),
                        'android', 'storage-probe', str(aligned), str(signed)], check=True)
        temporary = Path(str(args.output) + '.tmp')
        shutil.copy2(signed, temporary); temporary.replace(args.output)
    print(f'APK SHA-256: {digest(args.output)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
