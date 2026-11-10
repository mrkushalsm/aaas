#!/usr/bin/env python3
"""Build the ordinary, short-lived Android service used for MediaStore scans."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from experiments.perf.input_latency_probe.build_probe import binary_manifest
from experiments.m4.shared_storage_probe.deterministic_apk import normalize_zip_timestamps

PACKAGE = 'org.aaas.storagescan'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            digest.update(path.relative_to(Path(__file__).parent).as_posix().encode())
            digest.update(path.read_bytes())
    digest.update(Path(ROOT / 'experiments/perf/input_latency_probe/build_probe.py').read_bytes())
    digest.update(Path(ROOT / 'experiments/m4/shared_storage_probe/deterministic_apk.py').read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apktool', type=Path, required=True)
    parser.add_argument('--apksig', type=Path, required=True)
    parser.add_argument('--dx', type=Path, required=True,
                        help='pinned AOSP dx tool used to build a secondary DEX')
    parser.add_argument('--keystore', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for item in (args.apktool, args.apksig, args.dx, args.keystore):
        if not item.is_file():
            parser.error(f'missing pinned build input: {item}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = Path(str(args.output) + '.json')
    expected = {
        'package': PACKAGE,
        'source_sha256': source_hash(),
        'apktool_sha256': sha256(args.apktool),
        'apksig_sha256': sha256(args.apksig),
        'dx_sha256': sha256(args.dx),
        'keystore_sha256': sha256(args.keystore),
    }
    if args.output.is_file() and receipt.is_file():
        try:
            prior = json.loads(receipt.read_text())
        except (OSError, json.JSONDecodeError):
            prior = None
        if prior and all(prior.get(k) == v for k, v in expected.items()) and \
                prior.get('apk_sha256') == sha256(args.output):
            print(json.dumps(prior, sort_keys=True))
            return 0

    source = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='aaas-storage-scan-apk-') as temp:
        work = Path(temp)
        shutil.copytree(source / 'smali', work / 'smali')
        stubs = work / 'android-stubs'
        stub_sources = {
            'android/content/BroadcastReceiver.java': '''package android.content; public abstract class BroadcastReceiver { public abstract void onReceive(Context c,Intent i); }''',
            'android/content/Context.java': '''package android.content; import android.content.pm.PackageManager; public class Context { public PackageManager getPackageManager(){return null;} }''',
            'android/content/Intent.java': '''package android.content; public class Intent { public static final String ACTION_MAIN="android.intent.action.MAIN"; public static final String CATEGORY_LAUNCHER="android.intent.category.LAUNCHER"; public Intent(String a){} public Intent addCategory(String c){return this;} public String getStringExtra(String k){return null;} }''',
            'android/content/pm/ActivityInfo.java': '''package android.content.pm; public class ActivityInfo { public String packageName,name; public boolean enabled; public ApplicationInfo applicationInfo; public CharSequence loadLabel(PackageManager p){return null;} }''',
            'android/content/pm/ApplicationInfo.java': '''package android.content.pm; public class ApplicationInfo { public boolean enabled; public CharSequence loadLabel(PackageManager p){return null;} }''',
            'android/content/pm/PackageInfo.java': '''package android.content.pm; public class PackageInfo { public int versionCode; public String versionName; }''',
            'android/content/pm/PackageManager.java': '''package android.content.pm; import java.util.List; public class PackageManager { public List<ResolveInfo> queryIntentActivities(android.content.Intent i,int f){return null;} public PackageInfo getPackageInfo(String p,int f){return null;} }''',
            'android/content/pm/ResolveInfo.java': '''package android.content.pm; import android.graphics.drawable.Drawable; public class ResolveInfo { public ActivityInfo activityInfo; public CharSequence loadLabel(PackageManager p){return null;} public Drawable loadIcon(PackageManager p){return null;} }''',
            'android/graphics/Bitmap.java': '''package android.graphics; import java.io.OutputStream; public class Bitmap { public enum Config { ARGB_8888 } public enum CompressFormat { PNG } public static Bitmap createBitmap(int w,int h,Config c){return null;} public boolean compress(CompressFormat f,int q,OutputStream o){return false;} public void recycle(){} }''',
            'android/graphics/Canvas.java': '''package android.graphics; public class Canvas { public Canvas(Bitmap b){} }''',
            'android/graphics/drawable/Drawable.java': '''package android.graphics.drawable; import android.graphics.Canvas; public class Drawable { public void setBounds(int l,int t,int r,int b){} public void draw(Canvas c){} }''',
            'android/util/Base64.java': '''package android.util; public class Base64 { public static final int NO_WRAP=2; public static String encodeToString(byte[] b,int f){return null;} }''',
            'android/util/Log.java': '''package android.util; public class Log { public static int e(String t,String m){return 0;} public static int e(String t,String m,Throwable x){return 0;} public static int i(String t,String m){return 0;} }''',
        }
        for relative, content in stub_sources.items():
            destination = stubs / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content)
        stub_classes = work / 'stub-classes'
        stub_classes.mkdir()
        subprocess.run(['javac', '--release', '8', '-d', str(stub_classes),
                        *map(str, stubs.rglob('*.java'))], check=True)
        classes = work / 'catalog-classes'
        classes.mkdir()
        subprocess.run([
            'javac', '--release', '8', '-cp', str(stub_classes), '-d', str(classes),
            str(source / 'src/org/aaas/storagescan/CatalogReceiver.java'),
        ], check=True)
        catalog_dex = work / 'classes2.dex'
        subprocess.run([
            str(args.dx), '--dex', f'--output={catalog_dex}', str(classes),
        ], check=True)
        (work / 'AndroidManifest.xml').write_bytes(binary_manifest(
            PACKAGE, target_sdk=35,
            receivers=(('.ScanReceiver', 'android.permission.DUMP'),
                       ('.CatalogReceiver', 'android.permission.DUMP')),
            include_launcher=False, query_launcher_apps=True,
        ))
        (work / 'apktool.yml').write_text(
            'version: 3.0.3\napkFileName: AaasStorageScan.apk\n'
            'sdkInfo:\n  minSdkVersion: 28\n  targetSdkVersion: 35\n'
            'versionInfo:\n  versionCode: 1\n  versionName: 1.0\n')
        subprocess.run(['java', '-jar', str(args.apktool), 'b', '--no-apk', str(work)],
                       check=True)
        dex = work / 'build/apk/classes.dex'
        if not dex.is_file():
            raise RuntimeError('apktool did not emit classes.dex')
        unsigned = work / 'unsigned.apk'
        with zipfile.ZipFile(unsigned, 'w') as apk:
            apk.write(work / 'AndroidManifest.xml', 'AndroidManifest.xml')
            apk.write(dex, 'classes.dex')
            apk.write(catalog_dex, 'classes2.dex')
        normalized = work / 'normalized.apk'
        normalize_zip_timestamps(unsigned, normalized)
        signer = source.parent / 'shared_storage_probe' / 'ApkSign.java'
        subprocess.run(['javac', '-cp', str(args.apksig), '-d', str(work), str(signer)],
                       check=True)
        built = work / 'signed.apk'
        subprocess.run(['java', '-cp', f'{work}:{args.apksig}', 'ApkSign',
                        str(args.keystore), 'android', 'storage-probe',
                        str(normalized), str(built)], check=True)
        temporary_output = args.output.with_suffix('.apk.tmp')
        shutil.copy2(built, temporary_output)
        temporary_output.replace(args.output)
    result = {**expected, 'apk_sha256': sha256(args.output)}
    temporary_receipt = receipt.with_suffix('.json.tmp')
    temporary_receipt.write_text(json.dumps(result, indent=2) + '\n')
    temporary_receipt.replace(receipt)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
