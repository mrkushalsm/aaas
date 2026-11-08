#!/usr/bin/env python3
"""Assemble a fresh, metadata-preserving Android 16 SDK rootfs candidate.

The result is deliberately marked ASSEMBLED_INCOMPLETE: this command extracts
the original Android partitions and ramdisk, but does not install unresolved
diagnostic binary changes or claim runtime/security readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).parent))
import android_workspace as ws
from extract_super_partitions import extract_partitions
from read_lp_metadata import read_lp_metadata
import aaas_profiles


GIB = 1 << 30
PREDICTED_ASSEMBLY_BYTES = 4 * GIB
REQUIRED_PARTITIONS = ('system', 'system_ext', 'product', 'vendor', 'system_dlkm')
RAMDISK_MEMBER = 'x86_64/ramdisk.img'
SYSTEM_MEMBER = 'x86_64/system.img'
USERNS_UID_LIMIT = 65536
SPECIAL_ROOTFS_DIRS = (
    'apex', 'bootstrap-apex', 'cache', 'config', 'data', 'data_mirror',
    'debug', 'dev', 'mnt', 'metadata', 'odm', 'odm_dlkm', 'oem',
    'postinstall', 'proc', 'sdcard', 'storage', 'sys', 'tmp', 'vendor_dlkm',
)
TRANSFORMATION_MAP = (Path(__file__).resolve().parents[1] /
                      'manifests/android16-reconstruction-transformations.json')


class AssemblyError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _workspace_directory(workspace: Path, relative: str) -> Path:
    """Create/validate an owned directory chain without traversing symlinks."""
    workspace = Path(workspace).resolve(strict=True)
    current = workspace
    for part in PurePosixPath(relative).parts:
        if part in ('', '.', '..', '/'):
            raise AssemblyError(f'unsafe workspace-relative directory: {relative!r}')
        current = current / part
        try:
            current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            continue
        if current.is_symlink() or not current.is_dir():
            raise AssemblyError(f'workspace path component is not a real directory: {current}')
    return current


def _verify_archive(path: Path, image: dict) -> dict:
    raw = Path(path)
    if raw.is_symlink() or not raw.is_file():
        raise AssemblyError(f'Android image must be a regular file: {raw}')
    resolved = raw.resolve(strict=True)
    size = resolved.stat().st_size
    if size != image['size_bytes']:
        raise AssemblyError(f'Android image size mismatch: expected {image["size_bytes"]}, got {size}')
    sha1 = sha1_file(resolved)
    if sha1 != image['sha1']:
        raise AssemblyError(f'Android image SHA-1 mismatch: {sha1}')
    sha256 = sha256_file(resolved)
    if sha256 != image.get('sha256'):
        raise AssemblyError(f'Android image SHA-256 mismatch: {sha256}')
    return {'path': str(resolved), 'size_bytes': size,
            'sha1': sha1, 'sha256': sha256}


def _hash_zip_member(archive: zipfile.ZipFile, member: str) -> tuple[int, str]:
    info = archive.getinfo(member)
    digest = hashlib.sha256()
    size = 0
    with archive.open(info) as source:
        for chunk in iter(lambda: source.read(1 << 20), b''):
            digest.update(chunk)
            size += len(chunk)
    if size != info.file_size:
        raise AssemblyError(f'ZIP member size mismatch for {member}')
    return size, digest.hexdigest()


def _materialize_system_super(workspace: Path, archive_path: Path,
                               image_record: dict) -> tuple[Path, dict]:
    tmp_dir = _workspace_directory(workspace, 'tmp')
    cached = tmp_dir / 'system.img'
    with zipfile.ZipFile(archive_path) as archive:
        members = set(archive.namelist())
        if SYSTEM_MEMBER not in members or RAMDISK_MEMBER not in members:
            raise AssemblyError('verified SDK archive is missing system.img or ramdisk.img')
        expected_size, expected_digest = _hash_zip_member(archive, SYSTEM_MEMBER)
        candidates = [cached, workspace / 'cache' / 'android-images' /
                      image_record['archive'] / 'system.img']
        for candidate in candidates:
            if candidate.is_file() and not candidate.is_symlink():
                if (candidate.stat().st_size == expected_size
                        and sha256_file(candidate) == expected_digest):
                    return candidate.resolve(), {
                        'member': SYSTEM_MEMBER, 'size_bytes': expected_size,
                        'sha256': expected_digest, 'reused_path': str(candidate.resolve()),
                    }
        target_parent = _workspace_directory(
            workspace, f'cache/android-images/{image_record["archive"]}')
        target = target_parent / 'system.img'
        if target.exists() or target.is_symlink():
            raise AssemblyError(f'refusing to overwrite an unverified image cache: {target}')
        fd, temporary_name = tempfile.mkstemp(prefix='system.img.', suffix='.tmp',
                                              dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, 'wb') as output, archive.open(SYSTEM_MEMBER) as source:
                digest = hashlib.sha256()
                size = 0
                for chunk in iter(lambda: source.read(1 << 20), b''):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size != expected_size or digest.hexdigest() != expected_digest:
                raise AssemblyError('extracted system.img did not match its verified ZIP member')
            os.replace(temporary, target)
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
    return target, {'member': SYSTEM_MEMBER, 'size_bytes': expected_size,
                    'sha256': expected_digest, 'reused_path': None,
                    'extracted_path': str(target)}


def _partition_digest(super_image: Path, metadata: dict, partition: dict) -> str:
    digest = hashlib.sha256()
    zeroes = bytes(1 << 20)
    base_offset = metadata.get('base_offset', 0)
    with Path(super_image).open('rb') as source:
        for extent in partition['extents']:
            remaining = extent['size_bytes']
            if extent['target_type'] == 0:
                source.seek(base_offset + extent['offset_bytes'])
                while remaining:
                    chunk = source.read(min(remaining, 1 << 20))
                    if not chunk:
                        raise AssemblyError(f'unexpected EOF in {partition["name"]} extent')
                    digest.update(chunk)
                    remaining -= len(chunk)
            elif extent['target_type'] == 1:
                while remaining:
                    count = min(remaining, len(zeroes))
                    digest.update(zeroes[:count])
                    remaining -= count
            else:
                raise AssemblyError(f'unsupported extent type in {partition["name"]}')
    return digest.hexdigest()


def _partition_cache(workspace: Path, profile: dict) -> Path:
    build = profile['build_id'].replace('/', '_')
    relative = (f'cache/android-images/{profile["source_image"]["archive"]}/'
                f'partitions/{build}')
    return _workspace_directory(workspace, relative)


def _ensure_partitions(workspace: Path, super_image: Path, profile: dict,
                       lp_metadata: dict) -> dict:
    records = {partition['name']: partition for partition in lp_metadata['partitions']}
    missing = [name for name in REQUIRED_PARTITIONS if name not in records]
    if missing:
        raise AssemblyError(f'Android super image lacks required partitions: {missing}')
    cache = _partition_cache(workspace, profile)
    legacy_cache = _workspace_directory(workspace, 'tmp/partitions')
    result = {}
    extract_names = []
    for name in REQUIRED_PARTITIONS:
        partition = records[name]
        candidates = (legacy_cache / f'{name}.raw.img', cache / f'{name}.raw.img')
        source = None
        expected_digest = _partition_digest(super_image, lp_metadata, partition)
        for candidate in candidates:
            if candidate.is_file() and not candidate.is_symlink():
                if (candidate.stat().st_size == partition['total_size_bytes']
                        and sha256_file(candidate) == expected_digest):
                    source = candidate.resolve()
                    break
        if source is None:
            cached = cache / f'{name}.raw.img'
            if cached.exists() or cached.is_symlink():
                raise AssemblyError(f'cached partition failed verification; preserving it: {cached}')
            extract_names.append(name)
        else:
            result[name] = {'path': source, 'partition': partition,
                            'sha256': expected_digest, 'reused': True}
    if extract_names:
        extract_partitions(super_image, cache, extract_names)
        for name in extract_names:
            partition = records[name]
            raw = cache / f'{name}.raw.img'
            expected_digest = _partition_digest(super_image, lp_metadata, partition)
            actual = sha256_file(raw)
            if (raw.stat().st_size != partition['total_size_bytes']
                    or actual != expected_digest):
                raise AssemblyError(f'extracted {name} partition failed extent/hash verification')
            result[name] = {'path': raw, 'partition': partition,
                            'sha256': actual, 'reused': False}
    return result


def _guestfish_quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '') + '"'


def _partition_tar(raw_image: Path, tar_path: Path) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=tar_path.name + '.', suffix='.tmp',
                                          dir=tar_path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    script = '\n'.join((
        'run', 'list-filesystems', 'mount-ro /dev/sda /',
        f'tar-out / {_guestfish_quote(str(temporary))} compress:gzip '
        'numericowner:true xattrs:true selinux:true acls:true',
    )) + '\n'
    try:
        result = subprocess.run(['guestfish', '--ro', '-a', str(raw_image)],
                                input=script, capture_output=True, text=True,
                                timeout=1800)
        if result.returncode:
            raise AssemblyError(
                f'guestfish export failed for {raw_image.name}: '
                f'{(result.stderr or result.stdout).strip()[-2000:]}')
        with tarfile.open(temporary, 'r:gz') as archive:
            archive.getmembers()
        os.replace(temporary, tar_path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _safe_tar_member(name: str) -> str | None:
    path = PurePosixPath(name)
    if path.is_absolute() or any(part == '..' for part in path.parts):
        raise AssemblyError(f'unsafe partition archive path: {name!r}')
    clean = '/'.join(part for part in path.parts if part not in ('', '.', '/'))
    return clean or None


def _inventory_tar(tar_path: Path, partition: str) -> tuple[list[dict], dict]:
    items = []
    member_paths = []
    symlink_paths = set()
    stats = {'regular_files': 0, 'directories': 0, 'symlinks': 0,
             'hardlinks': 0, 'other': 0, 'logical_bytes': 0,
             'selinux_xattrs_retained_in_archive': 0,
             'selinux_preload_references': []}
    with tarfile.open(tar_path, 'r:gz') as archive:
        for member in archive:
            relative = _safe_tar_member(member.name)
            if relative is None:
                continue
            if member.uid > USERNS_UID_LIMIT or member.gid > USERNS_UID_LIMIT:
                raise AssemblyError(
                    f'{partition}/{relative} owner exceeds delegated UID/GID range '
                    f'({member.uid}:{member.gid})')
            kind = ('file' if member.isfile() else 'directory' if member.isdir()
                    else 'symlink' if member.issym() else 'hardlink' if member.islnk()
                    else 'other')
            member_paths.append((relative, kind))
            if kind == 'symlink':
                symlink_paths.add(relative)
            if kind == 'hardlink':
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or '..' in link.parts:
                    raise AssemblyError(f'unsafe hard-link target in {partition}: {relative}')
            digest = None
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise AssemblyError(f'cannot read {partition}/{relative} from source tar')
                value = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1 << 20), b''):
                    value.update(chunk)
                digest = value.hexdigest()
                stats['regular_files'] += 1
                stats['logical_bytes'] += member.size
                if relative.endswith('.rc'):
                    rc_stream = archive.extractfile(member)
                    if rc_stream and b'libselinux_shim.so' in rc_stream.read():
                        stats['selinux_preload_references'].append(relative)
            else:
                stats[{'directory': 'directories', 'symlink': 'symlinks',
                       'hardlink': 'hardlinks'}.get(kind, 'other')] += 1
            if any(key.startswith(('SCHILY.xattr.security.selinux',
                                   'LIBARCHIVE.xattr.security.selinux'))
                   for key in member.pax_headers):
                stats['selinux_xattrs_retained_in_archive'] += 1
            items.append({'partition': partition, 'path': relative,
                          'type': kind, 'mode': member.mode,
                          'uid': member.uid, 'gid': member.gid,
                          'size': member.size, 'linkname': member.linkname or None,
                          'sha256': digest})
    for relative, _kind in member_paths:
        parent = PurePosixPath(relative).parent
        while str(parent) not in ('', '.'):
            if parent.as_posix() in symlink_paths:
                raise AssemblyError(f'partition archive traverses a symlink: {partition}/{relative}')
            parent = parent.parent
    return items, stats


def _extract_tar(tar_path: Path, destination: Path) -> bool:
    if destination.is_symlink():
        raise AssemblyError(f'refusing to extract through a symlink: {destination}')
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or not destination.is_dir():
        raise AssemblyError(f'partition destination is not a real directory: {destination}')
    command = [
        'unshare', '--user', '--map-root-user', '--map-auto',
        'tar', '--extract', '--gzip', '--file', str(tar_path),
        '--directory', str(destination), '--numeric-owner', '--same-owner',
        '--same-permissions', '--xattrs', '--xattrs-include=*',
        '--xattrs-exclude=security.selinux', '--acls',
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    if result.returncode:
        raise AssemblyError(f'rootless partition extraction failed for {tar_path.name}: '
                            f'{(result.stderr or result.stdout).strip()[-2000:]}')
    return True


def _ramdisk_bytes(archive_path: Path, stage: Path) -> tuple[Path, dict]:
    path = stage / 'inputs' / 'ramdisk.img'
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        info = archive.getinfo(RAMDISK_MEMBER)
        data = archive.read(RAMDISK_MEMBER)
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != info.file_size:
        raise AssemblyError('ramdisk ZIP member size mismatch')
    if path.exists():
        if path.is_symlink() or path.stat().st_size != len(data) or sha256_file(path) != digest:
            raise AssemblyError(f'refusing to overwrite invalid staged ramdisk: {path}')
    else:
        path.write_bytes(data)
    return path, {'member': RAMDISK_MEMBER, 'size_bytes': len(data), 'sha256': digest}


def _extract_ramdisk(ramdisk_image: Path, rootfs: Path, stage: Path) -> dict:
    cpio_path = stage / 'inputs' / 'ramdisk.cpio'
    inventory_path = stage / 'ramdisk-inventory.json'
    if not cpio_path.exists():
        result = subprocess.run(['lz4', '-d', '-c', str(ramdisk_image)],
                                capture_output=True, timeout=60)
        if result.returncode:
            raise AssemblyError(f'cannot decompress Android ramdisk: {result.stderr.decode(errors="replace")[-1000:]}')
        cpio_path.write_bytes(result.stdout)
    command = ['unshare', '--user', '--map-root-user', '--map-auto',
               sys.executable, str(Path(__file__).with_name('android_newc.py')),
               '--archive', str(cpio_path), '--destination', str(rootfs),
               '--inventory', str(inventory_path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise AssemblyError(f'cannot extract Android ramdisk: '
                            f'{(result.stderr or result.stdout).strip()[-1500:]}')
    return json.loads(inventory_path.read_text(encoding='utf-8'))


def _verify_critical_files(items: list[dict]) -> dict:
    audit_path = Path(__file__).resolve().parents[1] / 'manifests/android16-diagnostic-rootfs-audit.json'
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    item_hashes = {(item['partition'], item['path']): item.get('sha256') for item in items}
    checked, mismatches, missing = [], [], []
    for record in audit.get('entries', []):
        source_partition = record.get('source_partition')
        expected = record.get('original_sha256')
        if not source_partition or not expected:
            continue
        path = record['path']
        prefix = source_partition + '/'
        if not path.startswith(prefix):
            continue
        # The Android 16 system image is system-as-root: its ext4 filesystem
        # already contains the top-level `system/` directory. The other
        # logical partitions are mounted beneath their own names.
        relative = path if source_partition == 'system' else path[len(prefix):]
        actual = item_hashes.get((source_partition, relative))
        if actual is None:
            missing.append(path)
        elif actual != expected:
            mismatches.append({'path': path, 'expected': expected, 'actual': actual})
        else:
            checked.append(path)
    if missing or mismatches:
        raise AssemblyError(f'base critical-file verification failed: missing={missing}, mismatched={mismatches}')
    return {'verified_base_critical_files': checked, 'mismatch_count': 0,
            'missing_count': 0}


def _validate_no_selinux_bypass(items: list[dict], preload_references: list[str]) -> dict:
    bypass_paths = [item['partition'] + '/' + item['path'] for item in items
                    if 'libselinux_shim.so' in item['path']]
    return {'status': 'PASS' if not bypass_paths and not preload_references else 'FAIL',
            'shim_paths': bypass_paths,
            'preload_references': sorted(preload_references)}


def _prepare_mountpoints(rootfs: Path) -> list[str]:
    created = []
    for relative in SPECIAL_ROOTFS_DIRS:
        path = rootfs / relative
        if path.is_symlink():
            continue
        if path.exists():
            if not path.is_dir():
                raise AssemblyError(f'Android mountpoint is not a directory: {relative}')
            continue
        path.mkdir(parents=True)
        created.append(relative)
    return created


def _remove_owned_stage(workspace: Path, stage: Path, profile_id: str,
                        archive_sha256: str) -> None:
    """Remove only a validated assembly staging tree using its UID map."""
    expected = (workspace / 'tmp' / 'android-rootfs-build' /
                f'{profile_id}-{aaas_profiles.profiles()[profile_id]["build_id"]}').resolve()
    if stage.is_symlink() or stage.resolve(strict=True) != expected:
        raise AssemblyError(f'refusing to remove unexpected assembly path: {stage}')
    code = r'''import json, shutil, sys
from pathlib import Path
stage = Path(sys.argv[1])
expected = Path(sys.argv[2])
marker = stage / '.aaas-assembly-staging'
if stage.is_symlink() or stage.resolve(strict=True) != expected.resolve(strict=True):
    raise SystemExit('staging path changed during validation')
if marker.is_symlink() or not marker.is_file():
    raise SystemExit('staging marker missing or unsafe')
value = json.loads(marker.read_text(encoding='utf-8'))
if (not isinstance(value, dict) or value.get('profile') != sys.argv[3]
        or value.get('archive_sha256') != sys.argv[4]
        or value.get('created_by') != 'scripts/assemble_android_rootfs.py'):
    raise SystemExit('staging marker provenance mismatch')
shutil.rmtree(stage)
'''
    result = subprocess.run(
        ['unshare', '--user', '--map-root-user', '--map-auto', sys.executable,
         '-c', code, str(stage), str(expected), profile_id, archive_sha256],
        capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise AssemblyError(f'could not safely discard prior staging tree: '
                            f'{(result.stderr or result.stdout).strip()[-1000:]}')


def assemble(workspace: Path, profile_id: str, *, image_path: Path | None = None,
             dry_run: bool = False) -> dict:
    workspace = Path(workspace).expanduser().absolute()
    profile = aaas_profiles.profiles().get(profile_id)
    if profile is None:
        raise AssemblyError(f'unsupported Android profile: {profile_id}')
    source = profile['source_image']
    build_id = profile['build_id']
    image_path = Path(image_path) if image_path else workspace / 'images' / source['archive']
    budget = ws.check(workspace, PREDICTED_ASSEMBLY_BYTES)
    plan = {'profile': profile_id, 'archive': str(image_path),
            'predicted_workspace_bytes': PREDICTED_ASSEMBLY_BYTES,
            'workspace_used_bytes': budget['used_bytes'],
            'workspace_free_bytes': budget['free_bytes'],
            'candidate_relative': str(Path('rootfs-candidates') / profile_id / build_id)}
    if dry_run:
        return {'status': 'PLAN', 'plan': plan}
    verified_image = _verify_archive(image_path, source)
    super_image, super_record = _materialize_system_super(workspace,
                                                           Path(verified_image['path']),
                                                           source)
    lp_metadata = read_lp_metadata(super_image)
    if lp_metadata.get('error') or not lp_metadata.get('is_super'):
        raise AssemblyError(f'Android system.img is not a readable LP super image: {lp_metadata.get("error")}')
    partition_inputs = _ensure_partitions(workspace, super_image, profile, lp_metadata)
    final_parent = _workspace_directory(workspace, f'rootfs-candidates/{profile_id}')
    final = final_parent / build_id
    if final.exists() or final.is_symlink():
        raise AssemblyError(f'refusing to overwrite existing rootfs candidate: {final}')
    stage_parent = _workspace_directory(workspace, 'tmp/android-rootfs-build')
    stage = stage_parent / f'{profile_id}-{build_id}'
    if stage.is_symlink():
        raise AssemblyError(f'refusing symlinked assembly staging path: {stage}')
    if stage.exists():
        marker = stage / '.aaas-assembly-staging'
        if marker.is_symlink() or not marker.is_file():
            raise AssemblyError(f'preserving unrecognized staging path for inspection: {stage}')
        try:
            marker_data = json.loads(marker.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as error:
            raise AssemblyError(f'preserving unrecognized staging path for inspection: {stage}') from error
        if (not isinstance(marker_data, dict) or marker_data.get('profile') != profile_id
                or marker_data.get('archive_sha256') != verified_image['sha256']
                or marker_data.get('created_by') != 'scripts/assemble_android_rootfs.py'):
            raise AssemblyError(f'preserving staging path with unknown provenance: {stage}')
        # This tree contains only disposable outputs from this deterministic assembly
        # recipe. Remove it as a whole and restart from the already-verified cached inputs.
        _remove_owned_stage(workspace, stage, profile_id, verified_image['sha256'])
    stage.mkdir()
    (stage / '.aaas-assembly-staging').write_text(json.dumps({
        'profile': profile_id, 'archive_sha256': verified_image['sha256'],
        'created_by': 'scripts/assemble_android_rootfs.py',
    }) + '\n', encoding='utf-8')
    inputs_dir = stage / 'inputs' / 'partitions'
    inputs_dir.mkdir(parents=True)
    rootfs = stage / 'rootfs'
    rootfs.mkdir()
    partition_items, partition_records, missing_components = [], {}, []
    for name in REQUIRED_PARTITIONS:
        source_record = partition_inputs[name]
        tar_path = inputs_dir / f'{name}.tar.gz'
        _partition_tar(source_record['path'], tar_path)
        items, stats = _inventory_tar(tar_path, name)
        # The SDK's system image is system-as-root and includes top-level
        # symlinks such as /bin -> /system/bin. Overlay it at the root; the
        # other logical partitions are mounted at their named directories.
        destination = rootfs if name == 'system' else rootfs / name
        _extract_tar(tar_path, destination)
        partition_items.extend(items)
        partition_records[name] = {
            'source_partition_path': str(source_record['path']),
            'source_partition_sha256': source_record['sha256'],
            'source_partition_size_bytes': source_record['partition']['total_size_bytes'],
            'filesystem': source_record['partition'].get('fs_type', 'unknown'),
            'tarball': str(Path('inputs/partitions') / tar_path.name),
            'tarball_sha256': sha256_file(tar_path),
            **stats,
        }
    ramdisk_path, ramdisk_record = _ramdisk_bytes(Path(verified_image['path']), stage)
    ramdisk_inventory = _extract_ramdisk(ramdisk_path, rootfs, stage)
    _verify_critical_files(partition_items)
    preload_references = [f'{name}/{path}'
                          for name, record in partition_records.items()
                          for path in record.get('selinux_preload_references', [])]
    bypass = _validate_no_selinux_bypass(partition_items, preload_references)
    if bypass['status'] != 'PASS':
        raise AssemblyError(f'base image unexpectedly contains SELinux bypass artifacts: {bypass}')
    created_mountpoints = _prepare_mountpoints(rootfs)
    inventory_path = stage / 'file-inventory.jsonl'
    with inventory_path.open('w', encoding='utf-8') as output:
        for item in partition_items:
            output.write(json.dumps(item, sort_keys=True) + '\n')
        for item in ramdisk_inventory['inventory']:
            output.write(json.dumps({'partition': 'ramdisk', **item}, sort_keys=True) + '\n')
        output.flush()
        os.fsync(output.fileno())
    selinux_attr_count = sum(
        record['selinux_xattrs_retained_in_archive']
        for record in partition_records.values())
    transformations = json.loads(TRANSFORMATION_MAP.read_text(encoding='utf-8'))
    if (transformations.get('schema') != 1
            or transformations.get('base_image', {}).get('sha256') != source.get('sha256')):
        raise AssemblyError('historical transformation map does not match the selected base image')
    unresolved_critical = [entry['path'] for entry in transformations.get('entries', [])
                           if entry.get('classification') == 'UNRESOLVED'
                           and entry.get('source_partition')]
    missing_components.extend([
        f'{len(unresolved_critical)} critical historical changes remain unresolved; '
        'they were not copied into this candidate.',
        'The diagnostic apexd wrapper and vdc stub are excluded; stock apexd remains and the verified stock vdc is retained. The M1D read-only vdc session-overlay recipe is recorded separately.',
        'Android SELinux contexts are retained in source partition tarballs but are not materialized as host security.selinux xattrs because the host has no active SELinux LSM.',
        'No verified APEX activation recipe or live activation evidence is available.',
        'Ranchu graphics allocator/mapper require emulator devices; compatible allocator/mapper/Composer outputs are not built for this exact SDK ABI.',
        'Native Bridge, audio overlays, session helpers, and M2/M3/M4 runtime adapters are not installed into this candidate.',
        'Rootless runtime security and live Android startup have not been validated for this candidate.',
    ])
    manifest = {
        'schema': 1,
        'status': 'ASSEMBLED_INCOMPLETE',
        'profile': profile_id,
        'trust_classification': 'RECONSTRUCTED_EXPERIMENTAL',
        'runtime_ready': False,
        'distribution_approved': False,
        'source_archive': verified_image,
        'system_super': super_record,
        'logical_partition_metadata': {
            'is_super': lp_metadata['is_super'],
            'partition_count': len(lp_metadata.get('partitions', [])),
            'required_partitions': list(REQUIRED_PARTITIONS),
        },
        'partitions': partition_records,
        'ramdisk': {**ramdisk_record,
                    'inventory': str(Path('ramdisk-inventory.json')),
                    'files': len(ramdisk_inventory['inventory']),
                    'skipped_runtime_device_nodes': ramdisk_inventory['skipped_special_nodes']},
        'critical_base_file_verification': _verify_critical_files(partition_items),
        'historical_transformations': {
            'map': 'manifests/android16-reconstruction-transformations.json',
            'map_sha256': sha256_file(TRANSFORMATION_MAP),
            'status': transformations['status'],
            'unresolved_critical_files': unresolved_critical,
            'excluded_security_artifacts': transformations['excluded_security_artifacts'],
        },
        'security': {
            'selinux_lsm_available_on_host': Path('/sys/fs/selinux/load').exists(),
            'authorization_bypass_artifacts': bypass,
            'selinux_xattr_count_preserved_in_source_tarballs': selinux_attr_count,
            'selinux_xattrs_materialized': False,
            'android_permissions_modified': False,
        },
        'file_inventory': {'path': str(inventory_path.name),
                           'entries': len(partition_items) + len(ramdisk_inventory['inventory']),
                           'sha256': sha256_file(inventory_path)},
        'missing_components': missing_components,
        'assembly_recipe': {
            'tool': 'scripts/assemble_android_rootfs.py',
            'rootfs_source': 'verified Android SDK image archive only',
            'partition_export': 'libguestfs guestfish tar-out, numeric owners, xattrs, SELinux labels, POSIX ACLs',
            'materialization': 'GNU tar in a rootless user namespace using the configured subordinate UID/GID map; SELinux xattrs excluded from host tree and retained in source tarballs',
            'ramdisk': 'Android newc CPIO unpack with device nodes omitted for session-time creation',
            'diagnostic_rootfs_used_as_input': False,
            'diagnostic_rootfs_modified': False,
            'userdata_included': False,
        },
        'candidate_rootfs_relative': 'rootfs',
        'candidate_file_count': len(partition_items) + len(ramdisk_inventory['inventory']),
        'created_mountpoints': created_mountpoints,
        'candidate_logical_bytes': sum(item['size'] for item in partition_items
                                       if item['type'] in ('file', 'hardlink')),
    }
    manifest_path = stage / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    manifest_path.chmod(0o644)
    # Keep a full rebuild reserve until the candidate is atomically activated.
    ws.check(workspace, PREDICTED_ASSEMBLY_BYTES)
    # Keep source tars and the file inventory; remove only the staging marker
    # immediately before the atomic move to the versioned candidate directory.
    (stage / '.aaas-assembly-staging').unlink()
    os.replace(stage, final)
    return {'status': manifest['status'], 'candidate': str(final),
            'rootfs': str(final / 'rootfs'), 'manifest': str(final / 'manifest.json'),
            'file_inventory': str(final / 'file-inventory.jsonl'),
            'runtime_ready': False, 'missing_components': missing_components,
            'candidate_file_count': manifest['candidate_file_count'],
            'candidate_logical_bytes': manifest['candidate_logical_bytes']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--profile', default='android16-ranchu-x86_64')
    parser.add_argument('--image', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = assemble(args.workspace, args.profile, image_path=args.image,
                          dry_run=args.dry_run)
    except (AssemblyError, ws.WorkspaceError, OSError, ValueError,
            subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f'Android rootfs assembly: {error}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
