#!/usr/bin/env python3
"""Safely unpack the small Android newc ramdisk while preserving mapped IDs."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys


class NewcError(ValueError):
    pass


def parse_newc(data):
    """Yield (metadata, name, payload) records from a newc CPIO buffer."""
    offset = 0
    while offset + 110 <= len(data):
        header = data[offset:offset + 110]
        magic = header[:6]
        if magic not in (b'070701', b'070702'):
            raise NewcError(f'invalid newc magic at byte {offset}')
        try:
            fields = [int(header[6 + index * 8:14 + index * 8], 16)
                      for index in range(13)]
        except ValueError as error:
            raise NewcError(f'invalid newc header at byte {offset}') from error
        ino, mode, uid, gid, nlink, mtime, size, devmajor, devminor, rdevmajor, rdevminor, namesize, checksum = fields
        offset += 110
        if namesize < 1 or offset + namesize > len(data):
            raise NewcError('invalid newc filename size')
        raw_name = data[offset:offset + namesize]
        if raw_name[-1:] != b'\0':
            raise NewcError('newc filename is not NUL terminated')
        try:
            name = raw_name[:-1].decode('utf-8')
        except UnicodeDecodeError as error:
            raise NewcError('newc filename is not UTF-8') from error
        offset = (offset + namesize + 3) & ~3
        if offset + size > len(data):
            raise NewcError(f'truncated newc payload for {name!r}')
        payload = data[offset:offset + size]
        if magic == b'070702' and (sum(payload) & 0xffffffff) != checksum:
            raise NewcError(f'newc checksum mismatch for {name!r}')
        offset = (offset + size + 3) & ~3
        if name == 'TRAILER!!!':
            return
        yield {
            'ino': ino, 'mode': mode, 'uid': uid, 'gid': gid,
            'nlink': nlink, 'mtime': mtime, 'size': size,
            'devmajor': devmajor, 'devminor': devminor,
            'rdevmajor': rdevmajor, 'rdevminor': rdevminor,
        }, name, payload
    raise NewcError('newc trailer is missing')


def _safe_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ('..', '') for part in path.parts):
        raise NewcError(f'unsafe ramdisk path: {name!r}')
    if name in ('.', './'):
        return Path('.')
    return Path(*path.parts)


def extract_newc(data, destination, *, uid_limit=65536, gid_limit=65536,
                 replace_existing_symlinks=('init',)):
    """Materialize ordinary files; runtime-owned device nodes are reported."""
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    records = list(parse_newc(data))
    symlink_names = set()
    names = set()
    for metadata, name, _payload in records:
        relative = _safe_name(name)
        if relative == Path('.'):
            continue
        norm = relative.as_posix()
        if norm in names and not stat.S_ISDIR(metadata['mode']):
            raise NewcError(f'duplicate non-directory ramdisk entry: {norm}')
        names.add(norm)
        if stat.S_ISLNK(metadata['mode']):
            symlink_names.add(norm)
        if metadata['uid'] > uid_limit or metadata['gid'] > gid_limit:
            raise NewcError(f'ramdisk owner exceeds configured user-namespace map: {norm}')
    for _metadata, name, _payload in records:
        relative = _safe_name(name)
        if relative == Path('.'):
            continue
        for parent in relative.parents:
            if parent == Path('.'):
                continue
            if parent.as_posix() in symlink_names:
                raise NewcError(f'ramdisk entry traverses an archived symlink: {name!r}')

    inventory = []
    skipped = []
    dirs = []
    hardlinks = {}
    replace_existing_symlinks = set(replace_existing_symlinks)
    for metadata, name, payload in records:
        relative = _safe_name(name)
        if relative == Path('.'):
            continue
        target = destination / relative
        parent = destination
        for part in relative.parts[:-1]:
            parent = parent / part
            if parent.is_symlink():
                raise NewcError(f'ramdisk path traverses an existing symlink: {name!r}')
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = metadata['mode']
        kind = stat.S_IFMT(mode)
        if target.is_symlink() and relative.as_posix() in replace_existing_symlinks:
            target.unlink()
        elif target.exists() or target.is_symlink():
            if kind != stat.S_IFDIR or not target.is_dir() or target.is_symlink():
                raise NewcError(f'ramdisk entry conflicts with assembled partition: {relative}')
        if kind == stat.S_IFDIR:
            target.mkdir(exist_ok=True)
            dirs.append((target, metadata))
            typ = 'directory'
            digest = None
        elif kind == stat.S_IFREG:
            key = (metadata['devmajor'], metadata['devminor'], metadata['ino'])
            if metadata['nlink'] > 1 and not payload and key in hardlinks:
                os.link(hardlinks[key], target)
            else:
                with target.open('xb') as stream:
                    stream.write(payload)
                if metadata['nlink'] > 1:
                    hardlinks[key] = target
            typ = 'file'
            digest = hashlib.sha256(payload).hexdigest()
            os.chmod(target, stat.S_IMODE(mode))
            os.chown(target, metadata['uid'], metadata['gid'])
            os.utime(target, (metadata['mtime'], metadata['mtime']))
        elif kind == stat.S_IFLNK:
            link_target = payload.decode('utf-8', errors='surrogateescape')
            os.symlink(link_target, target)
            os.chown(target, metadata['uid'], metadata['gid'], follow_symlinks=False)
            typ = 'symlink'
            digest = hashlib.sha256(payload).hexdigest()
        else:
            # Android init creates these nodes in the session's private /dev.
            skipped.append({'path': relative.as_posix(), 'mode': mode,
                            'uid': metadata['uid'], 'gid': metadata['gid']})
            continue
        inventory.append({'path': relative.as_posix(), 'type': typ,
                          'mode': stat.S_IMODE(mode), 'uid': metadata['uid'],
                          'gid': metadata['gid'], 'size': metadata['size'],
                          'sha256': digest})
    for path, metadata in reversed(dirs):
        os.chmod(path, stat.S_IMODE(metadata['mode']))
        os.chown(path, metadata['uid'], metadata['gid'])
        os.utime(path, (metadata['mtime'], metadata['mtime']))
    return {'inventory': inventory, 'skipped_special_nodes': skipped}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = extract_newc(args.archive.read_bytes(), args.destination)
        args.inventory.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    except (OSError, NewcError) as error:
        print(f'Android ramdisk extraction: {error}', file=sys.stderr)
        return 2
    print(json.dumps({'status': 'extracted', 'entries': len(report['inventory']),
                      'skipped_special_nodes': len(report['skipped_special_nodes'])}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
