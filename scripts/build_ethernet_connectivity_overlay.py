#!/usr/bin/env python3
"""Build session-local Android virtual-Ethernet compatibility overlays.

The Android image contains the connectivity-resources package in both
system_ext and the tethering APEX. Its DeviceConfigUtils filters resolved
activities to the APEX path, while PackageManager resolves the system_ext
copy. This builder patches that selector to use the system package it actually
resolved, and assembles the matching Ethernet capability resource overlay.
All outputs are bind-mounted for one Android session; the image and userdata
remain untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SIGNER_SOURCE = ROOT / 'experiments/m4/shared_storage_probe/ApkSign.java'
EXPECTED = re.compile(r'<item>eth0;11,12,14;;</item>')
REPLACEMENT = '<item>eth0;11,12,13,14,15,28,37;;</item>'
METHOD = re.compile(
    r'(?ms)^\.method public static getConnectivityResourcesPackageName\(Landroid/content/Context;\)Ljava/lang/String;\n'
    r'.*?^\.end method\s*$'
)
TCP_BLOCK_QUERY = re.compile(
    r'(?m)^(?P<indent>\s*)invoke-virtual \{v12, v13, v5\}, '
    r'Landroid/net/ConnectivityManager;->isUidNetworkingBlocked\(IZ\)Z\n'
    r'(?P=indent)move-result v5$'
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run(args: list[str]) -> None:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f'command failed ({result.returncode}): {args!r}: {detail[-4000:]}')


def replace_method(smali: Path, descriptor: str) -> None:
    text = smali.read_text(encoding='utf-8')
    replacement = f'''\
.method public static getConnectivityResourcesPackageName(Landroid/content/Context;)Ljava/lang/String;
    .locals 2

    new-instance v0, Landroid/content/Intent;
    const-string v1, "com.android.server.connectivity.intent.action.SERVICE_CONNECTIVITY_RESOURCES_APK"
    invoke-direct {{v0, v1}}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V

    invoke-virtual {{p0}}, Landroid/content/Context;->getPackageManager()Landroid/content/pm/PackageManager;
    move-result-object v1
    const/high16 p0, 0x100000
    invoke-virtual {{v1, v0, p0}}, Landroid/content/pm/PackageManager;->queryIntentActivities(Landroid/content/Intent;I)Ljava/util/List;
    move-result-object v0
    invoke-interface {{v0}}, Ljava/util/List;->isEmpty()Z
    move-result p0
    if-nez p0, :no_resources

    const/4 p0, 0x0
    invoke-interface {{v0, p0}}, Ljava/util/List;->get(I)Ljava/lang/Object;
    move-result-object p0
    check-cast p0, Landroid/content/pm/ResolveInfo;
    iget-object p0, p0, Landroid/content/pm/ResolveInfo;->activityInfo:Landroid/content/pm/ActivityInfo;
    iget-object p0, p0, Landroid/content/pm/ActivityInfo;->applicationInfo:Landroid/content/pm/ApplicationInfo;
    iget-object p0, p0, Landroid/content/pm/ApplicationInfo;->packageName:Ljava/lang/String;
    return-object p0

:no_resources
    new-instance p0, Ljava/lang/IllegalStateException;
    const-string v0, "No connectivity resource package found"
    invoke-direct {{p0, v0}}, Ljava/lang/IllegalStateException;-><init>(Ljava/lang/String;)V
    throw p0
.end method'''
    patched, count = METHOD.subn(replacement, text)
    if count != 1:
        raise RuntimeError(f'expected exactly one connectivity resource selector in {smali}, found {count}')
    if descriptor not in patched:
        raise RuntimeError(f'patched method lost expected class descriptor {descriptor}')
    smali.write_text(patched, encoding='utf-8')


def patch_tcp_socket_tracker(smali: Path) -> None:
    """Keep connectivity validation alive when Android's optional BPF map is absent.

    TcpSocketTracker uses this query only to ignore sockets Android already
    knows are blocked when estimating connectivity. Rootless runtimes have no
    kernel UID firewall BPF maps, and the framework API dereferences a missing
    map entry on Android 16. Leave sockets in the validation sample instead of
    allowing NetworkMonitor to crash. This does not change firewall rules or
    grant applications network access; the runtime's namespace remains the
    network boundary.
    """
    text = smali.read_text(encoding='utf-8')
    patched, count = TCP_BLOCK_QUERY.subn(
        lambda match: f'{match.group("indent")}const/4 v5, 0x0', text)
    if count != 1:
        raise RuntimeError(
            f'expected one TcpSocketTracker BPF query in {smali}, found {count}')
    smali.write_text(patched, encoding='utf-8')


def build(workspace: Path, rootfs: Path, output_dir: Path) -> dict:
    tmp = workspace / 'tmp'
    apktool = tmp / 'apktool_3.0.3.jar'
    apksig = tmp / 'apksig-8.9.1.jar'
    framework = rootfs / 'system/framework/framework-res.apk'
    original_overlay = rootfs / 'vendor/overlay/goldfish_overlay_connectivity_gsi.apk'
    original_service_jar = rootfs / 'apex/com.android.tethering/javalib/service-connectivity.jar'
    original_network_stack = rootfs / 'system/priv-app/NetworkStack/NetworkStack.apk'
    zipalign = workspace / 'sources/prebuilts-build-tools-qpr2/linux-x86/bin/zipalign'
    key_dir = workspace / 'sources/build-make-qpr2/target/product/security'
    overlay_key = key_dir / 'testkey.pk8'
    overlay_cert = key_dir / 'testkey.x509.pem'
    network_key = key_dir / 'networkstack.pk8'
    network_cert = key_dir / 'networkstack.x509.pem'
    required = (apktool, apksig, framework, original_overlay, original_service_jar,
                original_network_stack, zipalign, overlay_key, overlay_cert,
                network_key, network_cert, SIGNER_SOURCE)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError('missing Android Ethernet build input(s): ' + ', '.join(missing))
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        'connectivity_overlay': output_dir / 'aaas_ethernet_connectivity_overlay.apk',
        'service_connectivity_jar': output_dir / 'aaas_service-connectivity.jar',
        'network_stack_apk': output_dir / 'aaas_NetworkStack.apk',
    }
    receipt_path = output_dir / 'aaas_ethernet_connectivity_overlay.json'
    inputs = {str(path.relative_to(workspace)) if path.is_relative_to(workspace) else str(path): sha256(path)
              for path in required}
    inputs.update({
        'rootfs/service-connectivity.jar': sha256(original_service_jar),
        'rootfs/NetworkStack.apk': sha256(original_network_stack),
        'capabilities': 'eth0;11,12,13,14,15,28,37;;',
        'resource_selector_patch': 'return first MATCH_SYSTEM_ONLY resolution; do not reject system_ext path',
        'network_monitor_patch': 'skip optional UID-blocked socket filter if rootless BPF map is absent',
    })
    if receipt_path.is_file():
        try:
            old = json.loads(receipt_path.read_text())
            if old.get('inputs') == inputs and all(
                    p.is_file() and old['outputs'][key] == sha256(p)
                    for key, p in outputs.items()):
                return old
        except (OSError, ValueError, KeyError):
            pass

    with tempfile.TemporaryDirectory(prefix='aaas-ethernet-compat-', dir=tmp) as temp:
        work = Path(temp)
        framework_cache = work / 'framework'
        run(['java', '-jar', str(apktool), 'if', str(framework), '-p', str(framework_cache)])

        # Capability RRO: advertise accurate Ethernet, not fake Wi-Fi.
        decoded_overlay = work / 'decoded-overlay'
        run(['java', '-jar', str(apktool), 'd', '-f', '--no-src', '-p', str(framework_cache),
             '-o', str(decoded_overlay), str(original_overlay)])
        arrays = decoded_overlay / 'res/values/arrays.xml'
        xml = arrays.read_text(encoding='utf-8')
        if len(EXPECTED.findall(xml)) != 1:
            raise RuntimeError('unexpected Ethernet capability resource; refusing patch')
        arrays.write_text(EXPECTED.sub(REPLACEMENT, xml), encoding='utf-8')
        built_overlay = work / 'overlay-built.apk'
        run(['java', '-jar', str(apktool), 'b', '-p', str(framework_cache), '-o',
             str(built_overlay), str(decoded_overlay)])
        sign_apk(work, workspace, built_overlay, outputs['connectivity_overlay'],
                 overlay_key, overlay_cert, 'aaas-connectivity')

        # Patch the duplicated selector in both Android consumers.
        patched_dex: dict[str, Path] = {}
        for label, source_apk, target_class in (
                ('service', original_service_jar,
                 'smali/android/net/connectivity/com/android/net/module/util/DeviceConfigUtils.smali'),
                ('networkstack', original_network_stack,
                 'smali/com/android/networkstack/com/android/net/module/util/DeviceConfigUtils.smali')):
            if label == 'service':
                # Apktool only baksmalis DEX in an APK. Wrap the APEX jar's DEX
                # with the image NetworkStack APK container for decoding.
                source_apk = work / 'service-connectivity-wrapper.apk'
                with zipfile.ZipFile(original_service_jar) as source_jar, \
                        zipfile.ZipFile(original_network_stack) as network_apk, \
                        zipfile.ZipFile(source_apk, 'w', zipfile.ZIP_DEFLATED) as wrapper:
                    for info in network_apk.infolist():
                        if info.filename == 'classes.dex':
                            wrapper.writestr(info, source_jar.read('classes.dex'))
                        elif not info.filename.startswith('META-INF/'):
                            wrapper.writestr(info, network_apk.read(info.filename))
            decoded = work / f'decoded-{label}'
            run(['java', '-jar', str(apktool), 'd', '-f', '-p', str(framework_cache),
                 '-o', str(decoded), str(source_apk)])
            smali = decoded / target_class
            if not smali.is_file():
                raise RuntimeError(f'Apktool did not decode expected selector: {smali}')
            replace_method(smali, 'DeviceConfigUtils')
            if label == 'networkstack':
                tracker = decoded / 'smali/com/android/networkstack/netlink/TcpSocketTracker.smali'
                if not tracker.is_file():
                    raise RuntimeError(f'Apktool did not decode NetworkMonitor tracker: {tracker}')
                patch_tcp_socket_tracker(tracker)
            rebuilt = work / f'{label}-rebuilt.apk'
            run(['java', '-jar', str(apktool), 'b', '-p', str(framework_cache), '-o',
                 str(rebuilt), str(decoded)])
            dex = work / f'{label}-classes.dex'
            with zipfile.ZipFile(rebuilt) as archive:
                if 'classes.dex' not in archive.namelist():
                    raise RuntimeError(f'patched {label} output lacks classes.dex')
                dex.write_bytes(archive.read('classes.dex'))
            patched_dex[label] = dex

        service_tmp = work / 'service-connectivity.jar'
        replace_zip_entry(original_service_jar, service_tmp, 'classes.dex', patched_dex['service'])
        atomic_copy(service_tmp, outputs['service_connectivity_jar'])

        network_unaligned = work / 'networkstack-rebuilt.apk'
        replace_zip_entry(original_network_stack, network_unaligned, 'classes.dex',
                          patched_dex['networkstack'])
        rebuilt_network = work / 'NetworkStack-rebuilt.apk'
        # The NetworkStack APK must retain its package signing identity.
        run([str(zipalign), '-f', '4', str(network_unaligned),
             str(work / 'networkstack-aligned.apk')])
        sign_apk(work, workspace, work / 'networkstack-aligned.apk',
                 outputs['network_stack_apk'], network_key, network_cert, 'com.android.networkstack')
        verify_certificate(outputs['network_stack_apk'], network_cert)

    receipt = {
        'schema_version': 3,
        'inputs': inputs,
        'outputs': {key: sha256(path) for key, path in outputs.items()},
        'network_capabilities': [11, 12, 13, 14, 15, 28, 37],
        'patched_components': ['service-connectivity.jar', 'NetworkStack.apk',
                               'NetworkStack.TcpSocketTracker'],
        'network_stack_signer_sha256': certificate_sha256(network_cert),
    }
    temporary = receipt_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    temporary.replace(receipt_path)
    return receipt


def atomic_copy(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    temporary.write_bytes(source.read_bytes())
    temporary.replace(destination)


def replace_zip_entry(source: Path, destination: Path, name: str, entry: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    with zipfile.ZipFile(source, 'r') as src, zipfile.ZipFile(temporary, 'w') as dst:
        for info in src.infolist():
            if info.filename == name:
                dst.writestr(info, entry.read_bytes())
            else:
                dst.writestr(info, src.read(info.filename))
    temporary.replace(destination)


def certificate_sha256(certificate: Path) -> str:
    result = subprocess.run(['openssl', 'x509', '-in', str(certificate), '-noout', '-fingerprint', '-sha256'],
                            check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
    return result.split('=', 1)[1].replace(':', '').lower()


def verify_certificate(apk: Path, certificate: Path) -> None:
    # Android's standard keytool reads APK JAR signatures and rejects a signer mismatch.
    result = subprocess.run(['keytool', '-printcert', '-jarfile', str(apk)], check=True,
                            stdout=subprocess.PIPE, text=True).stdout
    expected = certificate_sha256(certificate).upper()
    match = re.search(r'SHA256:\s*([0-9A-F:]+)', result)
    if not match or match.group(1).replace(':', '').upper() != expected:
        raise RuntimeError('NetworkStack APK signer does not match the image networkstack key')


def sign_apk(work: Path, workspace: Path, input_apk: Path, output_apk: Path,
             private_key: Path, certificate: Path, alias: str) -> None:
    apksig = workspace / 'tmp/apksig-8.9.1.jar'
    pem = work / f'{alias}.pem'
    p12 = work / f'{alias}.p12'
    run(['openssl', 'pkcs8', '-inform', 'DER', '-in', str(private_key), '-out', str(pem), '-nocrypt'])
    run(['openssl', 'pkcs12', '-export', '-out', str(p12), '-inkey', str(pem), '-in',
         str(certificate), '-name', alias, '-passout', 'pass:android'])
    run(['javac', '-cp', str(apksig), '-d', str(work), str(SIGNER_SOURCE)])
    run(['java', '-cp', f'{work}:{apksig}', 'ApkSign', str(p12), 'android', alias,
         str(input_apk), str(output_apk)])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.workspace.resolve(), args.rootfs.resolve(), args.output_dir.resolve())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
