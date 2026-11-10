#!/usr/bin/env python3
"""Build the opt-in, session clipboard IME companion APK."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from experiments.m4.shared_storage_probe.deterministic_apk import normalize_zip_timestamps
PACKAGE = 'org.aaas.clipboard'
ZIPALIGN_SHA256 = '915f3f9d6f726ba7c0b48475b79c8cf9b7caaeb20f2d7de002ccdc616b2c43c3'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_hash() -> str:
    digest = hashlib.sha256()
    base = Path(__file__).resolve().parent
    for path in sorted(base.rglob('*')):
        if not path.is_file() or 'build' in path.parts or '__pycache__' in path.parts:
            continue
        if path.suffix in ('.pyc', '.class', '.dex', '.apk'):
            continue
        digest.update(path.relative_to(base).as_posix().encode())
        digest.update(path.read_bytes())
    digest.update((ROOT / 'experiments/m4/shared_storage_probe/deterministic_apk.py').read_bytes())
    return digest.hexdigest()


def manifest() -> str:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{PACKAGE}" android:versionCode="1" android:versionName="1.0">
    <uses-sdk android:minSdkVersion="28" android:targetSdkVersion="35" />
    <application android:label="AaaS Clipboard" android:allowBackup="false"
        android:hasCode="true" android:supportsRtl="true">
        <service android:name=".ClipboardImeService"
            android:label="AaaS Clipboard"
            android:permission="android.permission.BIND_INPUT_METHOD"
            android:exported="true">
            <intent-filter>
                <action android:name="android.view.InputMethod" />
            </intent-filter>
            <meta-data android:name="android.view.im" android:resource="@xml/input_method" />
        </service>
        <receiver android:name=".HostClipboardReceiver"
            android:permission="android.permission.DUMP" android:exported="true">
            <intent-filter>
                <action android:name="org.aaas.clipboard.SET" />
            </intent-filter>
        </receiver>
        <activity android:name=".ClipboardProbeActivity"
            android:permission="android.permission.DUMP" android:exported="true" />
    </application>
</manifest>
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apktool', type=Path, required=True)
    parser.add_argument('--framework-res', type=Path, required=True)
    parser.add_argument('--apksig', type=Path, required=True)
    parser.add_argument('--dx', type=Path, required=True)
    parser.add_argument('--zipalign', type=Path, required=True)
    parser.add_argument('--keystore', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for item in (args.apktool, args.framework_res, args.apksig, args.dx,
                 args.zipalign, args.keystore):
        if not item.is_file():
            parser.error(f'missing pinned build input: {item}')
    if sha256(args.zipalign) != ZIPALIGN_SHA256:
        parser.error('zipalign does not match the pinned Android build-tools binary')
    source = Path(__file__).resolve().parent
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = Path(str(args.output) + '.json')
    inputs = {
        'package': PACKAGE,
        'source_sha256': source_hash(),
        'apktool_sha256': sha256(args.apktool),
        'apksig_sha256': sha256(args.apksig),
        'dx_sha256': sha256(args.dx),
        'zipalign_sha256': sha256(args.zipalign),
        'keystore_sha256': sha256(args.keystore),
    }
    if args.output.is_file() and receipt.is_file():
        try:
            previous = json.loads(receipt.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            previous = None
        if previous and all(previous.get(k) == v for k, v in inputs.items()) and \
                previous.get('apk_sha256') == sha256(args.output):
            print(json.dumps(previous, sort_keys=True))
            return 0

    stub_sources = {
        'android/content/BroadcastReceiver.java': '''package android.content; public abstract class BroadcastReceiver { public abstract void onReceive(Context c,Intent i); }''',
        'android/content/Context.java': '''package android.content; public class Context { public static final String CLIPBOARD_SERVICE="clipboard"; public Object getSystemService(String n){return null;} }''',
        'android/system/Os.java': '''package android.system; import java.io.FileDescriptor; public class Os { public static FileDescriptor open(String p,int f,int m){return null;} }''',
        # Linux/Android open(2) flag values are compile-time constants here.
        # Keep them identical to bionic so javac's inlined values are correct.
        'android/system/OsConstants.java': '''package android.system; public class OsConstants { public static final int O_WRONLY=1,O_CREAT=64,O_EXCL=128; }''',
        'android/content/Intent.java': '''package android.content; public class Intent { public String getAction(){return null;} public String getStringExtra(String n){return null;} }''',
        'android/content/ClipDescription.java': '''package android.content; public class ClipDescription { public CharSequence getLabel(){return null;} }''',
        'android/content/ClipData.java': '''package android.content; public class ClipData { public static ClipData newPlainText(CharSequence l,CharSequence t){return null;} public ClipDescription getDescription(){return null;} public int getItemCount(){return 0;} public Item getItemAt(int i){return null;} public static class Item { public CharSequence getText(){return null;} } }''',
        'android/content/ClipboardManager.java': '''package android.content; public class ClipboardManager { public interface OnPrimaryClipChangedListener {void onPrimaryClipChanged();} public void addPrimaryClipChangedListener(OnPrimaryClipChangedListener l){} public void removePrimaryClipChangedListener(OnPrimaryClipChangedListener l){} public ClipData getPrimaryClip(){return null;} public void setPrimaryClip(ClipData c){} public void clearPrimaryClip(){} }''',
        'android/inputmethodservice/InputMethodService.java': '''package android.inputmethodservice; import android.content.Context; import android.view.inputmethod.EditorInfo; public class InputMethodService extends Context { public void onCreate(){} public void onDestroy(){} public void onStartInput(EditorInfo i,boolean r){} }''',
        'android/view/inputmethod/EditorInfo.java': '''package android.view.inputmethod; public class EditorInfo {}''',
        'android/os/Bundle.java': '''package android.os; public class Bundle {}''',
        'android/os/Looper.java': '''package android.os; public class Looper { public static Looper getMainLooper(){return null;} }''',
        'android/os/Handler.java': '''package android.os; public class Handler { public Handler(Looper l){} public boolean postDelayed(Runnable r,long d){return true;} }''',
        'android/text/Editable.java': '''package android.text; public interface Editable extends CharSequence {}''',
        'android/app/Activity.java': '''package android.app; import android.content.Context; import android.content.Intent; import android.os.Bundle; import android.view.View; public class Activity extends Context { protected void onCreate(Bundle b){} protected void onResume(){} protected void onNewIntent(Intent i){} protected void onDestroy(){} public Intent getIntent(){return null;} public void setIntent(Intent i){} public void setContentView(View v){} }''',
        'android/util/Log.java': '''package android.util; public class Log { public static int i(String t,String m){return 0;} }''',
        'android/view/View.java': '''package android.view; public class View { public View(android.content.Context c){} public boolean requestFocus(){return true;} public boolean onTextContextMenuItem(int id){return true;} }''',
        'android/widget/EditText.java': '''package android.widget; import android.content.Context; import android.view.View; import android.text.Editable; public class EditText extends View { public EditText(Context c){super(c);} public void setSingleLine(boolean v){} public void setText(CharSequence v){} public int length(){return 0;} public void setSelection(int i){} public void selectAll(){} public Editable getText(){return null;} }''',
        'android/R.java': '''package android; public final class R { public static final class id { public static final int paste=16908322; public static final int copy=16908321; } }''',
    }
    with tempfile.TemporaryDirectory(prefix='aaas-clipboard-ime-') as temporary:
        work = Path(temporary)
        sources = work / 'stubs'
        for relative, text in stub_sources.items():
            path = sources / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        stub_classes = work / 'stub-classes'
        stub_classes.mkdir()
        java = sorted(sources.rglob('*.java'))
        subprocess.run(['javac', '--release', '8', '-d', str(stub_classes),
                        *map(str, java)], check=True)
        classes = work / 'classes'
        classes.mkdir()
        java = sorted((source / 'src').rglob('*.java'))
        subprocess.run(['javac', '--release', '8', '-cp', str(stub_classes),
                        '-d', str(classes), *map(str, java)], check=True)
        dex = work / 'classes.dex'
        subprocess.run([str(args.dx), '--dex', f'--output={dex}', str(classes)],
                       check=True)
        decoded = work / 'decoded'
        framework_cache = work / 'framework-cache'
        framework_cache.mkdir()
        subprocess.run(['java', '-jar', str(args.apktool), 'if',
                        str(args.framework_res), '-p', str(framework_cache)], check=True)
        (decoded / 'res/xml').mkdir(parents=True)
        (decoded / 'AndroidManifest.xml').write_text(manifest())
        shutil.copy2(source / 'res/xml/input_method.xml', decoded / 'res/xml/input_method.xml')
        (decoded / 'apktool.yml').write_text(
            'version: 3.0.3\napkFileName: AaasClipboard.apk\n'
            'usesFramework:\n  ids:\n  - 1\n'
            'sdkInfo:\n  minSdkVersion: 28\n  targetSdkVersion: 35\n'
            'versionInfo:\n  versionCode: 1\n  versionName: 1.0\n')
        apktool_unsigned = work / 'apktool-unsigned.apk'
        subprocess.run(['java', '-jar', str(args.apktool), 'b',
                        '-p', str(framework_cache), '-o', str(apktool_unsigned),
                        str(decoded)], check=True)
        unsigned = work / 'unsigned.apk'
        with zipfile.ZipFile(apktool_unsigned) as source_apk, \
                zipfile.ZipFile(unsigned, 'w') as apk:
            for item in source_apk.infolist():
                if item.filename.startswith('META-INF/') or item.filename == 'classes.dex':
                    continue
                info = zipfile.ZipInfo(item.filename, item.date_time)
                info.external_attr = item.external_attr
                info.compress_type = (
                    zipfile.ZIP_STORED if item.filename == 'resources.arsc'
                    else item.compress_type)
                apk.writestr(info, source_apk.read(item.filename))
            apk.write(dex, 'classes.dex')
        normalized = work / 'normalized.apk'
        normalize_zip_timestamps(unsigned, normalized)
        aligned = work / 'aligned.apk'
        subprocess.run([str(args.zipalign), '-f', '4', str(normalized), str(aligned)],
                       check=True)
        subprocess.run([str(args.zipalign), '-c', '4', str(aligned)], check=True)
        signer_source = ROOT / 'experiments/m4/shared_storage_probe/ApkSign.java'
        if not signer_source.is_file():
            raise FileNotFoundError(f'missing APK signer source: {signer_source}')
        subprocess.run(['javac', '-cp', str(args.apksig), '-d', str(work),
                        str(signer_source)], check=True)
        signed = work / 'signed.apk'
        subprocess.run(['java', '-cp', f'{work}:{args.apksig}', 'ApkSign',
                        str(args.keystore), 'android', 'storage-probe',
                        str(aligned), str(signed)], check=True)
        temp = args.output.with_suffix('.apk.tmp')
        shutil.copy2(signed, temp)
        temp.replace(args.output)
    result = {**inputs, 'apk_sha256': sha256(args.output)}
    temporary_receipt = receipt.with_suffix('.json.tmp')
    temporary_receipt.write_text(json.dumps(result, indent=2) + '\n')
    temporary_receipt.replace(receipt)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
