#!/usr/bin/env python3
"""Build the user-authorized AaaS Android notification-listener APK."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = 'org.aaas.notifications'
ZIPALIGN_SHA256 = '915f3f9d6f726ba7c0b48475b79c8cf9b7caaeb20f2d7de002ccdc616b2c43c3'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_hash():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).resolve().parent.rglob('*')):
        if path.is_file() and 'build' not in path.parts and path.suffix not in ('.pyc', '.class', '.dex', '.apk'):
            digest.update(path.relative_to(Path(__file__).resolve().parent).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('apktool', 'framework-res', 'apksig', 'dx', 'zipalign', 'keystore', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for path in vars(args).values():
        if isinstance(path, Path) and path.name != args.output.name and not path.is_file():
            parser.error(f'missing build input: {path}')
    if sha(args.zipalign) != ZIPALIGN_SHA256:
        parser.error('zipalign differs from pinned Android build-tools binary')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = Path(str(args.output) + '.json')
    inputs = {'package': PACKAGE, 'source_sha256': source_hash(),
              **{key.replace('-', '_') + '_sha256': sha(getattr(args, key.replace('-', '_')))
                 for key in ('apktool', 'framework-res', 'apksig', 'dx', 'zipalign', 'keystore')}}
    if args.output.is_file() and receipt.is_file():
        try:
            previous = json.loads(receipt.read_text())
            if all(previous.get(key) == value for key, value in inputs.items()) and previous.get('apk_sha256') == sha(args.output):
                print(json.dumps(previous, sort_keys=True))
                return 0
        except (OSError, ValueError):
            pass

    stubs = {
        'android/app/Notification.java': '''package android.app; public class Notification { public static final int VISIBILITY_SECRET=-1; public int visibility; public android.os.Bundle extras; public static final String EXTRA_TITLE="android.title",EXTRA_TEXT="android.text"; }''',
        'android/content/pm/ApplicationInfo.java': '''package android.content.pm; public class ApplicationInfo {}''',
        'android/content/pm/PackageManager.java': '''package android.content.pm; public class PackageManager { public ApplicationInfo getApplicationInfo(String p,int f){return null;} public CharSequence getApplicationLabel(ApplicationInfo i){return null;} }''',
        'android/os/Bundle.java': '''package android.os; public class Bundle { public CharSequence getCharSequence(String n){return null;} }''',
        'android/os/UserHandle.java': '''package android.os; public class UserHandle { public int getIdentifier(){return 0;} }''',
        'android/content/Context.java': '''package android.content; public class Context { public android.content.pm.PackageManager getPackageManager(){return null;} }''',
        'android/service/notification/StatusBarNotification.java': '''package android.service.notification; public class StatusBarNotification { public android.app.Notification getNotification(){return null;} public String getPackageName(){return null;} public String getKey(){return null;} public android.os.UserHandle getUser(){return null;} }''',
        'android/service/notification/NotificationListenerService.java': '''package android.service.notification; public class NotificationListenerService extends android.content.Context { public void onNotificationPosted(StatusBarNotification s){} public void onNotificationRemoved(StatusBarNotification s){} }''',
        'android/util/Base64.java': '''package android.util; public class Base64 { public static final int URL_SAFE=8,NO_WRAP=2,NO_PADDING=1; public static String encodeToString(byte[] b,int f){return null;} }''',
        'android/util/Log.java': '''package android.util; public class Log { public static int w(String t,String m){return 0;} }''',
        'android/system/ErrnoException.java': '''package android.system; public class ErrnoException extends Exception { public final int errno; public ErrnoException(String f,int e){super(f);errno=e;} }''',
        'android/system/Os.java': '''package android.system; import java.io.FileDescriptor; public class Os { public static FileDescriptor open(String p,int f,int m) throws ErrnoException {return null;} }''',
        'android/system/OsConstants.java': '''package android.system; public class OsConstants { public static final int O_WRONLY=1,O_CREAT=64,O_EXCL=128; }''',
    }
    with tempfile.TemporaryDirectory(prefix='aaas-notification-apk-') as temp:
        work = Path(temp); stub_root = work / 'stubs'; stub_root.mkdir()
        for relative, source in stubs.items():
            path = stub_root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(source)
        stub_classes = work / 'stub-classes'; stub_classes.mkdir()
        subprocess.run(['javac', '--release', '8', '-d', str(stub_classes), *map(str, stub_root.rglob('*.java'))], check=True)
        classes = work / 'classes'; classes.mkdir()
        source_root = Path(__file__).resolve().parent / 'src'
        subprocess.run(['javac', '--release', '8', '-cp', str(stub_classes), '-d', str(classes), *map(str, source_root.rglob('*.java'))], check=True)
        dex = work / 'classes.dex'
        subprocess.run([str(args.dx), '--dex', f'--output={dex}', str(classes)], check=True)
        manifest = work / 'AndroidManifest.xml'
        manifest.write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{PACKAGE}" android:versionCode="1" android:versionName="1.0">
<uses-sdk android:minSdkVersion="28" android:targetSdkVersion="35" />
<application android:label="AaaS Notifications" android:allowBackup="false" android:hasCode="true">
<service android:name=".ForwardingListener" android:label="AaaS notification forwarding" android:permission="android.permission.BIND_NOTIFICATION_LISTENER_SERVICE" android:exported="true"><intent-filter><action android:name="android.service.notification.NotificationListenerService" /></intent-filter></service>
</application></manifest>''')
        decoded = work / 'decoded'; (decoded / 'res').mkdir(parents=True); shutil.copy2(manifest, decoded / 'AndroidManifest.xml')
        (decoded / 'apktool.yml').write_text('version: 3.0.3\napkFileName: AaasNotifications.apk\nusesFramework:\n  ids:\n  - 1\nsdkInfo:\n  minSdkVersion: 28\n  targetSdkVersion: 35\nversionInfo:\n  versionCode: 1\n  versionName: 1.0\n')
        cache = work / 'framework-cache'; cache.mkdir()
        subprocess.run(['java','-jar',str(args.apktool),'if',str(args.framework_res),'-p',str(cache)],check=True)
        apktool_unsigned=work/'apktool.apk'; subprocess.run(['java','-jar',str(args.apktool),'b','-p',str(cache),'-o',str(apktool_unsigned),str(decoded)],check=True)
        unsigned=work/'unsigned.apk'
        with zipfile.ZipFile(apktool_unsigned) as src, zipfile.ZipFile(unsigned,'w') as out:
            for item in src.infolist():
                if item.filename.startswith('META-INF/') or item.filename=='classes.dex': continue
                info=zipfile.ZipInfo(item.filename,item.date_time); info.external_attr=item.external_attr
                info.compress_type=zipfile.ZIP_STORED if item.filename=='resources.arsc' else item.compress_type
                out.writestr(info,src.read(item.filename))
            out.write(dex,'classes.dex')
        aligned=work/'aligned.apk'; subprocess.run([str(args.zipalign),'-f','4',str(unsigned),str(aligned)],check=True); subprocess.run([str(args.zipalign),'-c','4',str(aligned)],check=True)
        signer=ROOT/'experiments/m4/shared_storage_probe/ApkSign.java'; subprocess.run(['javac','-cp',str(args.apksig),'-d',str(work),str(signer)],check=True)
        signed=work/'signed.apk'; subprocess.run(['java','-cp',f'{work}:{args.apksig}','ApkSign',str(args.keystore),'android','storage-probe',str(aligned),str(signed)],check=True)
        temporary=Path(str(args.output)+'.tmp'); shutil.copy2(signed,temporary); temporary.replace(args.output)
    result={**inputs,'apk_sha256':sha(args.output)}; tmp=Path(str(receipt)+'.tmp'); tmp.write_text(json.dumps(result,indent=2)+'\n'); tmp.replace(receipt)
    print(json.dumps(result,sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
