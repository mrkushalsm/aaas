#!/usr/bin/env python3
"""Build an ordinary target-SDK 35 app that exercises NotificationManager."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]
PACKAGE_RX = __import__('re').compile(r'org\.aaas\.notificationprobe(?:2)?\Z')
ZIPALIGN_SHA256 = '915f3f9d6f726ba7c0b48475b79c8cf9b7caaeb20f2d7de002ccdc616b2c43c3'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True)
    for name in ('apktool', 'framework-res', 'apksig', 'dx', 'zipalign', 'keystore', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if not PACKAGE_RX.fullmatch(args.package): parser.error('package must be a controlled probe identity')
    for name in ('apktool', 'framework-res', 'apksig', 'dx', 'zipalign', 'keystore'):
        path=getattr(args,name.replace('-','_'))
        if not path.is_file(): parser.error(f'missing build input: {path}')
    if sha(args.zipalign) != ZIPALIGN_SHA256: parser.error('zipalign differs from pinned binary')
    source=Path(__file__).resolve().parent; args.output.parent.mkdir(parents=True,exist_ok=True)
    source_digest=hashlib.sha256((source/'src-probe/org/aaas/notificationprobe/MainActivity.java').read_bytes()).hexdigest()
    inputs={'package':args.package,'source_sha256':source_digest,
            **{name.replace('-','_')+'_sha256':sha(getattr(args,name.replace('-','_')))
               for name in ('apktool','framework-res','apksig','dx','zipalign','keystore')}}
    receipt=Path(str(args.output)+'.json')
    if args.output.is_file() and receipt.is_file():
        try:
            old=json.loads(receipt.read_text())
            if all(old.get(k)==v for k,v in inputs.items()) and old.get('apk_sha256')==sha(args.output):
                print(json.dumps(old,sort_keys=True)); return 0
        except (OSError,ValueError): pass
    stubs={
      'android/Manifest.java':'package android; public final class Manifest { public static final class permission { public static final String POST_NOTIFICATIONS="android.permission.POST_NOTIFICATIONS"; } }',
      'android/R.java':'package android; public final class R { public static final class drawable { public static final int ic_dialog_info=17301642; } }',
      'android/os/Bundle.java':'package android.os; public class Bundle {}',
      'android/content/Intent.java':'package android.content; public class Intent { public String getStringExtra(String k){return null;} }',
      'android/content/Context.java':'package android.content; public class Context { public static final String NOTIFICATION_SERVICE="notification"; public Object getSystemService(String s){return null;} public String getPackageName(){return null;} public int checkSelfPermission(String p){return 0;} }',
      'android/content/pm/PackageManager.java':'package android.content.pm; public class PackageManager { public static final int PERMISSION_GRANTED=0; }',
      'android/app/Notification.java':'package android.app; public class Notification { public static class Builder { public Builder(android.content.Context c,String s){} public Builder setSmallIcon(int i){return this;} public Builder setContentTitle(CharSequence s){return this;} public Builder setContentText(CharSequence s){return this;} public Builder setAutoCancel(boolean b){return this;} public Notification build(){return null;} } }',
      'android/app/NotificationChannel.java':'package android.app; public class NotificationChannel { public NotificationChannel(String i,CharSequence n,int x){} }',
      'android/app/NotificationManager.java':'package android.app; public class NotificationManager { public static final int IMPORTANCE_DEFAULT=3; public void createNotificationChannel(NotificationChannel c){} public void notify(String t,int i,Notification n){} public void cancel(int i){} public void cancel(String t,int i){} }',
      'android/app/Activity.java':'package android.app; public class Activity extends android.content.Context { protected void onCreate(android.os.Bundle b){} protected void onNewIntent(android.content.Intent i){} public void setIntent(android.content.Intent i){} public android.content.Intent getIntent(){return null;} public void setContentView(android.view.View v){} public void requestPermissions(String[] p,int r){} public void onRequestPermissionsResult(int r,String[] p,int[] g){} }',
      'android/view/View.java':'package android.view; public class View { public View(android.content.Context c){} public interface OnClickListener {void onClick(View v);} public void setOnClickListener(OnClickListener l){} }',
      'android/widget/LinearLayout.java':'package android.widget; public class LinearLayout extends android.view.View { public static final int VERTICAL=1; public LinearLayout(android.content.Context c){super(c);} public void setOrientation(int x){} public void addView(android.view.View v){} }',
      'android/widget/TextView.java':'package android.widget; public class TextView extends android.view.View { public TextView(android.content.Context c){super(c);} public void setText(CharSequence t){} }',
      'android/widget/Button.java':'package android.widget; public class Button extends TextView { public Button(android.content.Context c){super(c);} }',
    }
    with tempfile.TemporaryDirectory(prefix='aaas-notification-probe-') as tmp:
      work=Path(tmp); stubroot=work/'stubs'
      for rel,text in stubs.items():
        p=stubroot/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
      stubclasses=work/'stubclasses';stubclasses.mkdir()
      subprocess.run(['javac','--release','8','-d',str(stubclasses),*map(str,stubroot.rglob('*.java'))],check=True)
      src=work/'src/org/aaas/notificationprobe/MainActivity.java';src.parent.mkdir(parents=True);src.write_text((source/'src-probe/org/aaas/notificationprobe/MainActivity.java').read_text().replace('package org.aaas.notificationprobe;','package '+args.package+';'))
      classes=work/'classes';classes.mkdir();subprocess.run(['javac','--release','8','-cp',str(stubclasses),'-d',str(classes),str(src)],check=True)
      dex=work/'classes.dex';subprocess.run([str(args.dx),'--dex',f'--output={dex}',str(classes)],check=True)
      decoded=work/'decoded';(decoded/'res').mkdir(parents=True)
      (decoded/'AndroidManifest.xml').write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{args.package}" android:versionCode="1" android:versionName="1.0">
<uses-sdk android:minSdkVersion="28" android:targetSdkVersion="35"/><uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>
<application android:label="AaaS notification probe" android:allowBackup="false" android:hasCode="true"><activity android:name=".MainActivity" android:exported="true" android:launchMode="singleTop"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>''')
      (decoded/'apktool.yml').write_text('version: 3.0.3\napkFileName: AaasNotificationProbe.apk\nusesFramework:\n  ids:\n  - 1\nsdkInfo:\n  minSdkVersion: 28\n  targetSdkVersion: 35\nversionInfo:\n  versionCode: 1\n  versionName: 1.0\n')
      cache=work/'framework-cache';cache.mkdir();subprocess.run(['java','-jar',str(args.apktool),'if',str(args.framework_res),'-p',str(cache)],check=True)
      built=work/'apktool.apk';subprocess.run(['java','-jar',str(args.apktool),'b','-p',str(cache),'-o',str(built),str(decoded)],check=True)
      unsigned=work/'unsigned.apk'
      with zipfile.ZipFile(built) as inp,zipfile.ZipFile(unsigned,'w') as out:
        for item in inp.infolist():
          if item.filename.startswith('META-INF/') or item.filename=='classes.dex':continue
          info=zipfile.ZipInfo(item.filename,item.date_time);info.external_attr=item.external_attr;info.compress_type=zipfile.ZIP_STORED if item.filename=='resources.arsc' else item.compress_type;out.writestr(info,inp.read(item.filename))
        out.write(dex,'classes.dex')
      aligned=work/'aligned.apk';subprocess.run([str(args.zipalign),'-f','4',str(unsigned),str(aligned)],check=True);subprocess.run([str(args.zipalign),'-c','4',str(aligned)],check=True)
      signer=ROOT/'experiments/m4/shared_storage_probe/ApkSign.java';subprocess.run(['javac','-cp',str(args.apksig),'-d',str(work),str(signer)],check=True)
      signed=work/'signed.apk';subprocess.run(['java','-cp',f'{work}:{args.apksig}','ApkSign',str(args.keystore),'android','storage-probe',str(aligned),str(signed)],check=True)
      temp=Path(str(args.output)+'.tmp');temp.write_bytes(signed.read_bytes());temp.replace(args.output)
    result={**inputs,'apk_sha256':sha(args.output)};temp=Path(str(receipt)+'.tmp');temp.write_text(json.dumps(result,indent=2)+'\n');temp.replace(receipt);print(json.dumps(result,sort_keys=True));return 0


if __name__ == '__main__': raise SystemExit(main())
