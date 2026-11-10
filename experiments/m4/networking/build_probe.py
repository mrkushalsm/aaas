#!/usr/bin/env python3
"""Build the Android ConnectivityManager, DNS, and HTTPS acceptance probe."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('apktool', 'framework-res', 'apksig', 'dx', 'zipalign',
                 'keystore', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('apktool', 'framework_res', 'apksig', 'dx', 'zipalign', 'keystore'):
        path = getattr(args, name).resolve(strict=True)
        setattr(args, name, path)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    stubs = {
        'android/app/Activity.java': '''package android.app;
          public class Activity extends android.content.Context {
          protected void onCreate(android.os.Bundle b){} public void setContentView(android.view.View v){}
          public void runOnUiThread(Runnable r){r.run();} }''',
        'android/content/Context.java': '''package android.content;
          public class Context { public Object getSystemService(String n){return null;} }''',
        'android/os/Bundle.java': 'package android.os; public class Bundle {}',
        'android/util/Log.java': '''package android.util; public class Log {
          public static int i(String t,String m){return 0;}
          public static int e(String t,String m,Throwable x){return 0;} }''',
        'android/view/View.java': 'package android.view; public class View {}',
        'android/widget/TextView.java': '''package android.widget; public class TextView extends android.view.View {
          public TextView(android.content.Context c){} public void setText(CharSequence s){} }''',
    }
    with tempfile.TemporaryDirectory(prefix='aaas-network-probe-') as temporary:
        work = Path(temporary)
        stubroot = work / 'stubs'
        for relative, content in stubs.items():
            target = stubroot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        stubclasses = work / 'stubclasses'; stubclasses.mkdir()
        subprocess.run(['javac', '--release', '8', '-d', str(stubclasses),
                        *map(str, stubroot.rglob('*.java'))], check=True)
        classes = work / 'classes'; classes.mkdir()
        source = Path(__file__).resolve().parent / 'src/org/aaas/netprobe/MainActivity.java'
        subprocess.run(['javac', '--release', '8', '-cp', str(stubclasses), '-d',
                        str(classes), str(source)], check=True)
        dex = work / 'classes.dex'
        subprocess.run([str(args.dx), '--dex', f'--output={dex}', str(classes)], check=True)
        decoded = work / 'decoded'; (decoded / 'res').mkdir(parents=True)
        (decoded / 'AndroidManifest.xml').write_text('''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.aaas.netprobe" android:versionCode="1" android:versionName="1.0">
<uses-sdk android:minSdkVersion="24" android:targetSdkVersion="24"/>
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>
<application android:label="AaaS Network Probe" android:allowBackup="false" android:hasCode="true">
<activity android:name=".MainActivity" android:exported="true"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity>
</application></manifest>''')
        (decoded / 'apktool.yml').write_text('''version: 3.0.3
apkFileName: AaasNetworkProbe.apk
usesFramework:
  ids:
  - 1
sdkInfo:
  minSdkVersion: 24
  targetSdkVersion: 24
versionInfo:
  versionCode: 1
  versionName: 1.0
''')
        cache = work / 'framework-cache'; cache.mkdir()
        subprocess.run(['java', '-jar', str(args.apktool), 'if',
                        str(args.framework_res), '-p', str(cache)], check=True)
        built = work / 'built.apk'
        subprocess.run(['java', '-jar', str(args.apktool), 'b', '-p', str(cache),
                        '-o', str(built), str(decoded)], check=True)
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
        signer = Path(__file__).resolve().parents[1] / 'shared_storage_probe/ApkSign.java'
        subprocess.run(['javac', '-cp', str(args.apksig), '-d', str(work), str(signer)], check=True)
        signed = work / 'signed.apk'
        subprocess.run(['java', '-cp', f'{work}:{args.apksig}', 'ApkSign',
                        str(args.keystore), 'android', 'storage-probe',
                        str(aligned), str(signed)], check=True)
        temporary_output = Path(str(args.output) + '.tmp')
        shutil.copy2(signed, temporary_output)
        temporary_output.replace(args.output)
    print(f'Built signed AaaS Network Probe: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
