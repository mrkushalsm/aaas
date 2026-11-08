"""Resolve subordinate UID/GID mappings from the current host account."""

from __future__ import annotations

from dataclasses import dataclass
import os
import pwd
from pathlib import Path


MAP_LENGTH = 65535


class IdMapError(RuntimeError):
    pass


@dataclass(frozen=True)
class SubordinateRange:
    start: int
    length: int

    def __post_init__(self):
        if self.start < 1 or self.length < MAP_LENGTH:
            raise IdMapError(f'subordinate range must contain at least {MAP_LENGTH} IDs')


def parse_subid_file(path, account_name, account_id, *, minimum=MAP_LENGTH):
    """Return a sufficient range assigned to this username or numeric ID."""
    ranges = []
    try:
        lines = Path(path).read_text(encoding='ascii').splitlines()
    except OSError as error:
        raise IdMapError(f'cannot read subordinate ID file {path}: {error}') from error
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        fields = line.split(':')
        if len(fields) != 3:
            raise IdMapError(f'invalid subordinate ID entry at {path}:{number}')
        owner, raw_start, raw_length = fields
        if owner not in (account_name, str(account_id)):
            continue
        try:
            start, length = int(raw_start), int(raw_length)
        except ValueError as error:
            raise IdMapError(f'invalid subordinate ID numbers at {path}:{number}') from error
        if start < 1 or length < minimum or start + length > 2**32:
            continue
        ranges.append(SubordinateRange(start, length))
    if not ranges:
        raise IdMapError(
            f'no {minimum}-ID subordinate range assigned to {account_name} in {path}')
    return ranges[0]


def current_ranges(*, subuid_file='/etc/subuid', subgid_file='/etc/subgid'):
    account = pwd.getpwuid(os.getuid())
    return (
        parse_subid_file(subuid_file, account.pw_name, account.pw_uid),
        parse_subid_file(subgid_file, account.pw_name, account.pw_gid),
    )


def android_host_id(android_id, *, kind='uid'):
    if not isinstance(android_id, int) or android_id < 0:
        raise IdMapError('Android identity must be a nonnegative integer')
    uid_range, gid_range = current_ranges()
    selected = uid_range if kind == 'uid' else gid_range if kind == 'gid' else None
    if selected is None:
        raise IdMapError(f'unknown subordinate ID kind: {kind}')
    if android_id == 0:
        raise IdMapError('Android root identity maps to the caller, not a subordinate ID')
    if android_id >= selected.length:
        raise IdMapError(f'Android identity {android_id} is outside the subordinate range')
    return selected.start + android_id - 1


def map_commands(pid, *, host_uid=None, host_gid=None):
    """Build newuidmap/newgidmap argv for the namespace's standard AaaS map."""
    uid_range, gid_range = current_ranges()
    host_uid = os.getuid() if host_uid is None else int(host_uid)
    host_gid = os.getgid() if host_gid is None else int(host_gid)
    return (
        ['newuidmap', str(pid), '0', str(host_uid), '1',
         '1', str(uid_range.start), str(MAP_LENGTH)],
        ['newgidmap', str(pid), '0', str(host_gid), '1',
         '1', str(gid_range.start), str(MAP_LENGTH)],
        uid_range,
        gid_range,
    )
