#!/usr/bin/env python3
"""Inspect Android image artifacts against the explicitly supported profile."""

import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PROFILE_MANIFEST = ROOT / 'manifests/android-profiles.json'
TRUST_CLASSIFICATIONS = {
    'DIAGNOSTIC_LEGACY', 'RECONSTRUCTED_EXPERIMENTAL',
    'SECURITY_VALIDATED', 'DISTRIBUTABLE',
}
IMAGE_MANIFEST = ROOT / 'manifests/android-images.json'
TRANSFORMATION_MANIFEST = ROOT / 'manifests/android16-reconstruction-transformations.json'


class ProfileError(ValueError):
    pass


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def profiles():
    value = json.loads(PROFILE_MANIFEST.read_text(encoding='utf-8'))
    if value.get('schema') != 1 or not isinstance(value.get('profiles'), list):
        raise ProfileError('Android profile manifest has an unsupported schema')
    result = {item['id']: item for item in value['profiles']}
    for profile in result.values():
        classification = profile.get('trust_classification')
        if classification not in TRUST_CLASSIFICATIONS:
            raise ProfileError(
                f"profile {profile.get('id', '<unknown>')} has invalid trust classification")
    return result


def _properties(path):
    values = {}
    if not path.is_file() or path.is_symlink():
        return values
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def _selinux_security(root, profile):
    """Report static SELinux bypass indicators without claiming enforcement.

    SELinux is a kernel LSM property, so a filesystem image alone cannot prove
    that policy is loaded or enforcing.  This check only finds known dangerous
    compatibility artifacts and preload references; absence is not a pass.
    """
    security_profile = profile.get('security', {})
    known_shims = security_profile.get('forbidden_artifacts', [])
    bypasses = []
    for relative in known_shims:
        candidate = root / relative
        if candidate.exists() or candidate.is_symlink():
            bypasses.append({'path': relative, 'kind': 'known_selinux_compatibility_shim'})

    preload_references = []
    for relative in ('system/etc/init', 'system_ext/etc/init', 'vendor/etc/init'):
        directory = root / relative
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            init_files = directory.rglob('*.rc')
            for path in init_files:
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    content = path.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    continue
                if 'libselinux_shim.so' in content:
                    preload_references.append(str(path.relative_to(root)))
        except OSError:
            continue
    if preload_references:
        bypasses.append({'paths': sorted(preload_references),
                         'kind': 'init_preload_reference'})

    return {
        'status': 'BYPASS_DETECTED' if bypasses else 'UNVERIFIED',
        'enforcement': 'UNVERIFIED',
        'bypass_indicators': bypasses,
        'limitation': ('A static rootfs inspection cannot establish kernel SELinux policy load or '
                       'enforcement; that requires a live runtime check against a SELinux-capable '
                       'and correctly integrated kernel.'),
    }


def inspect_rootfs(rootfs, profile_id='android16-ranchu-x86_64'):
    profile = profiles().get(profile_id)
    if profile is None:
        raise ProfileError(f'unsupported profile: {profile_id}')
    raw_root = Path(rootfs).expanduser()
    if raw_root.is_symlink():
        raise ProfileError('image root must not be a symlink')
    root = raw_root.resolve(strict=True)
    if not root.is_dir():
        raise ProfileError('image root must be a real directory')
    missing = []
    for relative in profile['required_files']:
        candidate = root / relative
        current = root
        escaped = False
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink():
                escaped = True
                break
        if escaped or not candidate.is_file():
            missing.append(relative)
    system = _properties(root / 'system/build.prop')
    vendor = _properties(root / 'vendor/build.prop')
    actual = {
        'release': system.get('ro.build.version.release'),
        'api_level': system.get('ro.build.version.sdk'),
        'abi': system.get('ro.product.cpu.abi'),
        'build_id': system.get('ro.build.id'),
        'vendor_build_id': vendor.get('ro.vendor.build.id'),
        'vendor_hardware': vendor.get('ro.hardware.power'),
    }
    expected = {
        'release': profile['android_release'],
        'api_level': str(profile['api_level']),
        'abi': profile['abi'],
        'build_id': profile['build_id'],
        'vendor_build_id': profile['build_id'],
        'vendor_hardware': profile['vendor_hardware'],
    }
    mismatches = {key: {'expected': expected[key], 'actual': actual[key]}
                  for key in expected if actual[key] != expected[key]}
    security = _selinux_security(root, profile)
    assembly_manifest = None
    assembly_record_validation = 'NOT_PRESENT'
    manifest_path = root.parent / 'manifest.json'
    if manifest_path.is_file() and not manifest_path.is_symlink():
        try:
            candidate_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            source = candidate_manifest.get('source_archive', {})
            inventory = candidate_manifest.get('file_inventory', {})
            inventory_name = Path(inventory.get('path', ''))
            inventory_path = manifest_path.parent / inventory_name
            transform_record = candidate_manifest.get('historical_transformations', {})
            transformation = json.loads(TRANSFORMATION_MANIFEST.read_text(encoding='utf-8'))
            valid_record = (
                candidate_manifest.get('schema') == 1
                and candidate_manifest.get('profile') == profile_id
                and candidate_manifest.get('build_id', profile.get('build_id')) == profile['build_id']
                and candidate_manifest.get('trust_classification') == 'RECONSTRUCTED_EXPERIMENTAL'
                and candidate_manifest.get('candidate_rootfs_relative') == 'rootfs'
                and candidate_manifest.get('status') == 'ASSEMBLED_INCOMPLETE'
                and candidate_manifest.get('runtime_ready') is False
                and candidate_manifest.get('distribution_approved') is False
                and source.get('size_bytes') == profile['source_image']['size_bytes']
                and source.get('sha1') == profile['source_image']['sha1']
                and source.get('sha256') == profile['source_image']['sha256']
                and inventory_name.name == str(inventory_name)
                and len(inventory_name.parts) == 1
                and inventory_path.is_file() and not inventory_path.is_symlink()
                and _sha256_file(inventory_path) == inventory.get('sha256')
                and transform_record.get('map') == 'manifests/android16-reconstruction-transformations.json'
                and transform_record.get('map_sha256') == hashlib.sha256(
                    TRANSFORMATION_MANIFEST.read_bytes()).hexdigest()
                and transformation.get('base_image', {}).get('sha256') == source.get('sha256')
                and candidate_manifest.get('critical_base_file_verification', {}).get(
                    'mismatch_count') == 0
                and candidate_manifest.get('critical_base_file_verification', {}).get(
                    'missing_count') == 0
                and candidate_manifest.get('security', {}).get(
                    'authorization_bypass_artifacts', {}).get('status') == 'PASS'
            )
            if valid_record:
                assembly_manifest = candidate_manifest
                assembly_record_validation = 'PASS'
            else:
                assembly_record_validation = 'FAIL'
        except (OSError, json.JSONDecodeError, TypeError, ValueError, AttributeError):
            candidate_manifest = None
    provisioning_blockers = []
    if not profile['provisioning']['automatically_installable']:
        provisioning_blockers.append(profile['provisioning']['reason'])
    if security['status'] == 'BYPASS_DETECTED':
        provisioning_blockers.append('known SELinux authorization-bypass artifact is present')
    if security['enforcement'] != 'VERIFIED':
        provisioning_blockers.append('SELinux enforcement has not been verified in a live runtime')
    return {
        'profile': profile_id,
        'trust_classification': (assembly_manifest.get('trust_classification')
                                 if assembly_manifest else profile['trust_classification']),
        'assembly_status': (assembly_manifest.get('status') if assembly_manifest else None),
        'runtime_ready': bool(assembly_manifest and assembly_manifest.get('runtime_ready'))
                         if assembly_manifest else None,
        'rootfs': str(root),
        'compatibility': 'MATCH' if not missing and not mismatches else 'UNSUPPORTED',
        'provenance': ('ASSEMBLY_RECORD_VALID' if assembly_manifest else 'UNVERIFIED'),
        'assembly_record_validation': assembly_record_validation,
        'provisionable': (profile['provisioning']['automatically_installable']
                          and not provisioning_blockers),
        'security': security,
        'provisioning_blockers': provisioning_blockers,
        'actual': actual,
        'missing_files': missing,
        'property_mismatches': mismatches,
        'provisioning_note': profile['provisioning']['reason'],
    }


def inspect_archive(path):
    raw_path = Path(path).expanduser()
    if raw_path.is_symlink():
        raise ProfileError('image archive must not be a symlink')
    path = raw_path.resolve(strict=True)
    if not path.is_file():
        raise ProfileError('image archive must be a regular file')
    declared = json.loads(IMAGE_MANIFEST.read_text(encoding='utf-8'))
    entry = next((item for item in declared.get('images', [])
                  if Path(item['url']).name == path.name), None)
    result = {'archive': str(path), 'size_bytes': path.stat().st_size,
              'sha1': None, 'sha256': None, 'declared_match': False, 'layout': [],
              'compatibility': 'UNVERIFIED'}
    digest = hashlib.sha1()
    strong_digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            strong_digest.update(chunk)
    result['sha1'] = digest.hexdigest()
    result['sha256'] = strong_digest.hexdigest()
    if entry:
        result['declared_match'] = (
            result['size_bytes'] == entry['size_bytes']
            and result['sha1'] == entry['sha1']
            and (entry.get('sha256') is None
                 or result['sha256'] == entry['sha256']))
        result['package'] = entry['sdk_path']
        result['revision'] = entry['revision']
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile) as error:
        raise ProfileError(f'invalid Android image archive: {error}') from error
    result['layout'] = sorted(name for name in names if name.rsplit('/', 1)[-1] in {
        'system.img', 'vendor.img', 'product.img', 'ramdisk.img', 'kernel-ranchu',
        'userdata.img', 'source.properties', 'build.prop'})
    result['archive_type'] = 'Android SDK emulator package'
    result['runtime_compatibility'] = 'UNVERIFIED; archive metadata alone is insufficient'
    return result
