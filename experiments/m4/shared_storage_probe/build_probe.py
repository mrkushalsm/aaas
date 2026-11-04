#!/usr/bin/env python3
"""Build a small ordinary APK for SAF shared-storage read/write checks."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from experiments.perf.input_latency_probe.build_probe import binary_manifest

PACKAGE = 'org.aaas.storagetest'
PERMISSIONS = ('android.permission.READ_MEDIA_IMAGES',)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apktool', type=Path, required=True)
    parser.add_argument('--keystore', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--operation', choices=('create', 'open'), default='create')
    parser.add_argument('--target-sdk', type=int, default=28,
                        help='Android target SDK (default: 28 for historical baseline)')
    parser.add_argument('--apksig', type=Path,
                        help='apksig JAR; required for target SDK 30 or newer')
    parser.add_argument('--userdata-diagnostics', action='store_true',
                        help='include the opt-in Android private-data/SQLite probe')
    parser.add_argument('--version-code', type=int, default=1)
    parser.add_argument('--version-name', default='1.0')
    parser.add_argument('--dx', type=Path,
                        help='dx.jar required with --userdata-diagnostics')
    args = parser.parse_args()
    if args.target_sdk >= 30 and args.apksig is None:
        parser.error('--apksig is required for target SDK 30 or newer')
    if args.version_code < 1:
        parser.error('--version-code must be positive')
    if args.userdata_diagnostics and args.dx is None:
        parser.error('--dx is required with --userdata-diagnostics')
    source = Path(__file__).resolve().parent
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aaas-storage-apk-') as temp:
        work = Path(temp)
        smali_source = source / ('smali-open' if args.operation == 'open' else 'smali')
        shutil.copytree(smali_source, work / 'smali')
        for smali_file in (work / 'smali').rglob('*.smali'):
            text = smali_file.read_text()
            text = text.replace('org.aaas.latencyprobe', PACKAGE)
            text = text.replace('org/aaas/latencyprobe', PACKAGE.replace('.', '/'))
            if (args.userdata_diagnostics
                    and '.class public Lorg/aaas/storagetest/ProbeActivity;' in text):
                anchor = '    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V\n'
                if anchor not in text:
                    raise RuntimeError('could not find ProbeActivity onCreate injection point')
                text = text.replace(anchor, anchor +
                    '    invoke-static {p0}, Lorg/aaas/storagetest/UserdataProbe;->run(Landroid/content/Context;)V\n', 1)
            smali_file.write_text(text)
        manifest = binary_manifest(
            PACKAGE, target_sdk=args.target_sdk, requested_permissions=PERMISSIONS,
            version_code=args.version_code, version_name=args.version_name)
        (work / 'AndroidManifest.xml').write_bytes(manifest)
        (work / 'apktool.yml').write_text(
            'version: 3.0.3\napkFileName: AaasStorageProbe.apk\n'
            f'sdkInfo:\n  minSdkVersion: {min(args.target_sdk, 28)}\n'
            f'  targetSdkVersion: {args.target_sdk}\n'
            f'versionInfo:\n  versionCode: {args.version_code}\n'
            f'  versionName: {args.version_name}\n')
        run(['java', '-jar', str(args.apktool), 'b', '--no-apk', str(work)])
        dex = work / 'build/apk/classes.dex'
        if not dex.is_file():
            raise RuntimeError('apktool did not emit classes.dex')
        extra_dex = None
        if args.userdata_diagnostics:
            helper_source = source / 'java/org/aaas/storagetest/UserdataProbe.java'
            stubs = work / 'android-stubs'
            stub_sources = {
                # Compile-only signatures; APK bytecode resolves against Android's runtime.
                'android/content/Context.java': '''package android.content; import java.io.File; import android.content.pm.PackageManager; import android.database.sqlite.SQLiteDatabase; public class Context { public static final int MODE_PRIVATE=0; public PackageManager getPackageManager(){return null;} public String getPackageName(){return null;} public File getDataDir(){return null;} public File getFilesDir(){return null;} public File getCacheDir(){return null;} public File getDatabasePath(String n){return null;} public File getExternalFilesDir(String t){return null;} public Context createDeviceProtectedStorageContext(){return null;} public SQLiteDatabase openOrCreateDatabase(String n,int m,SQLiteDatabase.CursorFactory f){return null;} }''',
                'android/content/pm/PackageManager.java': '''package android.content.pm; public class PackageManager { public PackageInfo getPackageInfo(String n,int f){return null;} }''',
                'android/content/pm/PackageInfo.java': '''package android.content.pm; public class PackageInfo { public int versionCode; }''',
                'android/database/Cursor.java': '''package android.database; public interface Cursor extends AutoCloseable { boolean moveToNext(); boolean moveToFirst(); int getInt(int c); String getString(int c); void close(); }''',
                'android/database/sqlite/SQLiteDatabase.java': '''package android.database.sqlite; import android.database.Cursor; public class SQLiteDatabase { public interface CursorFactory {} public boolean enableWriteAheadLogging(){return false;} public void execSQL(String s){} public int getVersion(){return 0;} public void setVersion(int v){} public void beginTransaction(){} public void setTransactionSuccessful(){} public void endTransaction(){} public Cursor rawQuery(String s,String[] a){return null;} public String getPath(){return null;} public boolean isWriteAheadLoggingEnabled(){return false;} public void close(){} }''',
                'android/os/Process.java': '''package android.os; public class Process { public static int myUid(){return 0;} }''',
                'android/system/StructStat.java': '''package android.system; public class StructStat { public long st_dev,st_ino; public int st_uid,st_gid,st_mode; }''',
                'android/system/Os.java': '''package android.system; public class Os { public static StructStat stat(String p){return null;} }''',
                'android/util/Base64.java': '''package android.util; public class Base64 { public static final int NO_WRAP=2; public static String encodeToString(byte[] b,int f){return null;} }''',
                'android/util/Log.java': '''package android.util; public class Log { public static int i(String t,String m){return 0;} public static int e(String t,String m,Throwable x){return 0;} }''',
            }
            for relative, content in stub_sources.items():
                destination = stubs / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content)
            stub_classes = work / 'stub-classes'
            class_dir = work / 'userdata-classes'
            stub_classes.mkdir()
            class_dir.mkdir()
            run(['javac', '-source', '8', '-target', '8', '-d', str(stub_classes),
                 *map(str, stubs.rglob('*.java'))])
            run(['javac', '-source', '8', '-target', '8', '-cp', str(stub_classes),
                 '-d', str(class_dir), str(helper_source)])
            extra_dex = work / 'classes2.dex'
            run(['java', '-cp', str(args.dx.resolve(strict=True)), 'com.android.dx.command.Main',
                 '--dex', f'--output={extra_dex}', str(class_dir)])
        unsigned = work / 'unsigned.apk'
        with zipfile.ZipFile(unsigned, 'w') as apk:
            apk.write(work / 'AndroidManifest.xml', 'AndroidManifest.xml')
            apk.write(dex, 'classes.dex')
            if extra_dex is not None:
                apk.write(extra_dex, 'classes2.dex')
        if args.apksig is None:
            run(['jarsigner', '-keystore', str(args.keystore), '-storepass', 'android',
                 '-keypass', 'android', '-sigalg', 'SHA256withRSA', '-digestalg',
                 'SHA-256', str(unsigned), 'storage-probe'])
            shutil.copy2(unsigned, args.output)
        else:
            apksig = args.apksig.resolve(strict=True)
            signer_source = source / 'ApkSign.java'
            run(['javac', '-cp', str(apksig), '-d', str(work), str(signer_source)])
            run(['java', '-cp', f'{work}:{apksig}', 'ApkSign',
                 str(args.keystore.resolve(strict=True)), 'android',
                 'storage-probe', str(unsigned), str(args.output.resolve())])
    print(f'APK SHA-256: {hashlib.sha256(args.output.read_bytes()).hexdigest()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
