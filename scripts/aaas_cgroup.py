#!/usr/bin/env python3
"""Rootless delegated cgroup v2 memory policy for AaaS.

The Android runtime already bind-mounts the delegated ``aaas`` cgroup into the
container and libprocessgroup creates ``system/uid_*/pid_*`` and
``apps/uid_*/pid_*`` leaves there.  This module uses those delegated leaves as
the identity boundary, applies conservative memory controls, and moves
non-anchor Android processes into a small session hierarchy:

    aaas/
      system/...                 Android native services and system processes
      apps/...                   Android application processes
      m1b86-<session>/
        critical/                critical app/native services
        foreground/              top / visible application processes
        background/              service and perceptible background processes
        cached/                  cached application processes

``memory.low`` is used for best-effort relative protection.  ``memory.high`` is
used only as a soft reclaim throttle for background classes.  No ``memory.max``
is set on Android classes, so this policy does not create a second kernel OOM
killer next to Android LMKD.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping


MIB = 1024 * 1024
CGROUP_MOUNT = Path('/sys/fs/cgroup')
AAAS_SCOPE = 'aaas'
CLASS_NAMES = ('critical', 'foreground', 'background', 'cached')


class CgroupError(RuntimeError):
    """Base class for delegated cgroup failures."""


class DelegationError(CgroupError):
    """The current user does not have a usable delegated cgroup subtree."""


class IdentityError(CgroupError):
    """A PID cannot be verified as a member of the active AaaS session."""


@dataclass(frozen=True)
class MemoryPolicy:
    low: int = 0
    high: int | None = None
    max: int | None = None
    oom_group: int = 0

    def as_dict(self) -> dict:
        return {
            'memory.low': self.low,
            'memory.high': 'max' if self.high is None else self.high,
            'memory.max': 'max' if self.max is None else self.max,
            'memory.oom.group': self.oom_group,
        }


# Conservative, measurement-backed defaults.  Protection is relative and
# best-effort; the kernel scales it down when siblings overcommit.  Android
# classes deliberately have no memory.max, so kernel OOM remains an explicit
# disposable-test behaviour rather than an Android runtime policy.
DEFAULT_POLICIES: dict[str, MemoryPolicy] = {
    'critical': MemoryPolicy(low=512 * MIB),
    'foreground': MemoryPolicy(low=384 * MIB),
    'background': MemoryPolicy(low=0, high=512 * MIB),
    'cached': MemoryPolicy(low=0, high=256 * MIB),
}
ANCHOR_POLICY = MemoryPolicy(low=256 * MIB)

# cgroup v2 does not migrate existing memory charges when a process moves.
# The pid leaf that already owns those charges therefore receives the same
# class protection in place.  Values are capped to avoid claiming more
# guaranteed memory than the runtime can support.
IN_PLACE_POLICIES: dict[str, MemoryPolicy] = {
    'critical': MemoryPolicy(low=128 * MIB),
    'foreground': MemoryPolicy(low=128 * MIB),
    'background': MemoryPolicy(low=0, high=256 * MIB),
    'cached': MemoryPolicy(low=0, high=128 * MIB),
}
IN_PLACE_LOW_FLOOR = 8 * MIB


def in_place_policy(klass: str, current_bytes: int) -> MemoryPolicy:
    """Class policy for the pid leaf that already owns existing charges.

    ``memory.low`` is capped per process and sized to half of current usage so
    that many small critical services do not claim an unbounded global
    protection budget.  Background classes only get a soft reclaim throttle.
    """

    base = IN_PLACE_POLICIES[klass]
    if base.low:
        low = min(base.low, max(IN_PLACE_LOW_FLOOR, current_bytes // 2))
        return MemoryPolicy(low=low, high=base.high, max=None,
                            oom_group=base.oom_group)
    return base

# These processes stay in their original libprocessgroup leaves.  They are the
# framework boot chain and are protected in place to avoid interfering with
# libprocessgroup/zygote lifecycle management.
ANCHOR_NAMES = frozenset({
    'init', 'ueventd', 'system_server', 'system', 'surfaceflinger',
    'zygote', 'zygote64', 'servicemanager', 'hwservicemanager', 'lmkd',
})

# Android ActivityManager process states (ActivityManager.java).
PROCESS_STATE_PERSISTENT = 0
PROCESS_STATE_PERSISTENT_UI = 1
PROCESS_STATE_TOP = 2
PROCESS_STATE_IMPORTANT_FOREGROUND = 6
PROCESS_STATE_CACHED = 14


def _read(path: Path) -> str:
    return path.read_text().strip()


def _write(path: Path, value) -> None:
    path.write_text(f'{value}\n')


def _read_optional(path: Path) -> str | None:
    try:
        return _read(path)
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None


def normalize_cgroup_path(value: str) -> str:
    if not value or not value.startswith('/'):
        raise CgroupError(f'cgroup path is not absolute: {value!r}')
    if '..' in Path(value).parts:
        raise CgroupError(f'cgroup path contains ..: {value!r}')
    return value


def cgroup_dir(cgroup_path: str, mount: Path = CGROUP_MOUNT) -> Path:
    path = mount / normalize_cgroup_path(cgroup_path).lstrip('/')
    if mount not in path.parents and path != mount:
        raise CgroupError(f'cgroup path escapes {mount}: {cgroup_path!r}')
    return path


def is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _read_v2_cgroup(text: str) -> str:
    matches = [line[3:] for line in text.splitlines() if line.startswith('0::')]
    if len(matches) != 1:
        raise DelegationError('expected exactly one cgroup v2 entry in /proc/self/cgroup')
    return normalize_cgroup_path(matches[0])


def discover_delegated_root(
    cgroup_text: str | None = None,
    mount: Path = CGROUP_MOUNT,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return the delegated ``aaas`` cgroup directory.

    Discovery is based on the current process's cgroup path, not a hardcoded
    boot path.  The AaaS scope is a sibling of the user manager's current
    session slice, under ``user@<uid>.service``.
    """

    env = os.environ if environ is None else environ
    override = env.get('AAAS_CGROUP_ROOT')
    if override:
        candidate = Path(override)
        if not candidate.is_absolute():
            raise DelegationError('AAAS_CGROUP_ROOT must be absolute')
        if '..' in candidate.parts:
            raise DelegationError('AAAS_CGROUP_ROOT contains ..')
        candidate = candidate.resolve()
        if not is_under(candidate, mount):
            raise DelegationError(f'AAAS_CGROUP_ROOT is outside {mount}')
        return candidate

    if cgroup_text is None:
        cgroup_text = Path('/proc/self/cgroup').read_text()
    current = _read_v2_cgroup(cgroup_text)
    parts = Path(current).parts
    service_index = None
    for index, part in enumerate(parts):
        if part.startswith('user@') and part.endswith('.service'):
            service_index = index
            break
    if service_index is None:
        raise DelegationError(
            'current cgroup is not below a systemd user@<uid>.service; '
            'start AaaS from a delegated user session'
        )
    relative = Path(*parts[:service_index + 1]) / AAAS_SCOPE
    candidate = mount / relative.relative_to('/')
    if not is_under(candidate, mount):
        raise DelegationError(f'discovered AaaS scope escapes {mount}')
    return candidate


def ensure_memory_controller(root: Path) -> None:
    """Make ``memory`` available to children of ``root`` without internal procs."""

    controllers = set(_read(root / 'cgroup.controllers').split())
    if 'memory' not in controllers:
        raise DelegationError(f'memory controller is not delegated to {root}')
    subtree = set(_read(root / 'cgroup.subtree_control').split())
    if 'memory' in subtree:
        return
    procs = _read(root / 'cgroup.procs')
    if procs:
        raise DelegationError(
            f'{root} contains processes; refusing to enable a domain controller '
            '(no-internal-process constraint)'
        )
    _write(root / 'cgroup.subtree_control', '+memory')
    if 'memory' not in set(_read(root / 'cgroup.subtree_control').split()):
        raise DelegationError(f'failed to enable memory controller on {root}')


def read_pid_starttime(pid: int) -> int:
    stat = Path(f'/proc/{pid}/stat').read_text()
    fields = stat.rsplit(')', 1)[1].split()
    return int(fields[19])


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    starttime: int
    uid: int
    nspid: tuple[int, ...]
    cgroup: str
    cmdline: str = ''
    name: str = ''

    @property
    def android_pid(self) -> int:
        return self.nspid[-1] if self.nspid else self.pid


def read_process_identity(pid: int) -> ProcessIdentity:
    status = Path(f'/proc/{pid}/status').read_text()
    values = {}
    for line in status.splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            values[key] = value.strip()
    uid = int(values['Uid'].split()[0])
    nspid = tuple(int(value) for value in values.get('NSpid', str(pid)).split())
    cgroup_line = next(
        line for line in Path(f'/proc/{pid}/cgroup').read_text().splitlines()
        if line.startswith('0::')
    )
    cgroup = normalize_cgroup_path(cgroup_line[3:])
    try:
        cmdline = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode(
            'utf-8', 'replace').strip()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        cmdline = ''
    name = values.get('Name', '')
    return ProcessIdentity(
        pid=pid,
        starttime=read_pid_starttime(pid),
        uid=uid,
        nspid=nspid,
        cgroup=cgroup,
        cmdline=cmdline,
        name=name,
    )


def _pidfd(pid: int):
    if not hasattr(os, 'pidfd_open'):
        return None
    try:
        return os.pidfd_open(pid)
    except OSError:
        return None


@dataclass
class ManagedProcess:
    identity: ProcessIdentity
    klass: str
    original_cgroup: str | None
    anchor: bool
    moved: bool
    updated_ns: int


@dataclass(frozen=True)
class ApplyResult:
    pid: int
    klass: str
    previous: str | None
    target: str
    moved: bool
    anchor: bool

    @property
    def changed(self) -> bool:
        return self.previous != self.klass


class CgroupSession:
    """A disposable memory-policy hierarchy below the delegated AaaS scope."""

    def __init__(
        self,
        root: Path,
        session_dir: Path,
        policies: Mapping[str, MemoryPolicy],
        min_starttime: int,
        mount: Path = CGROUP_MOUNT,
        stale_cleaned: Iterable[str] = (),
    ):
        self.root = root
        self.session_dir = session_dir
        self.policies = dict(policies)
        self.min_starttime = min_starttime
        self.mount = mount
        self.stale_cleaned = list(stale_cleaned)
        self.processes: dict[int, ManagedProcess] = {}
        self._shutdown = False

    @classmethod
    def create(
        cls,
        name: str,
        root: Path | None = None,
        policies: Mapping[str, MemoryPolicy] | None = None,
        mount: Path = CGROUP_MOUNT,
        min_starttime_slack: float = 2.0,
    ) -> 'CgroupSession':
        root = root or discover_delegated_root(mount=mount)
        if not root.is_dir():
            raise DelegationError(f'delegated AaaS scope does not exist: {root}')
        ensure_memory_controller(root)
        stale_cleaned = cleanup_stale_in_place(root)

        safe = re.sub(r'[^A-Za-z0-9_.-]+', '-', name).strip('.-')[:80]
        if not safe:
            raise CgroupError('empty session name')
        session_dir = root / f'm1b86-{safe}'
        if session_dir.exists():
            try:
                session_dir.rmdir()
            except OSError as exc:
                raise CgroupError(f'stale session cgroup is not empty: {session_dir}') from exc
        session_dir.mkdir(mode=0o755)
        ensure_memory_controller(session_dir)

        selected = dict(DEFAULT_POLICIES if policies is None else policies)
        missing = set(CLASS_NAMES) - set(selected)
        extra = set(selected) - set(CLASS_NAMES)
        if missing or extra:
            raise CgroupError(f'policy classes mismatch: missing={missing} extra={extra}')

        for klass in CLASS_NAMES:
            directory = session_dir / klass
            directory.mkdir(mode=0o755)
            write_policy(directory, selected[klass])

        hz = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
        boot_seconds = time.clock_gettime(time.CLOCK_BOOTTIME)
        min_starttime = max(0, int((boot_seconds - min_starttime_slack) * hz))
        return cls(root, session_dir, selected, min_starttime, mount,
                   stale_cleaned=stale_cleaned)

    @property
    def name(self) -> str:
        return self.session_dir.name

    def class_dir(self, klass: str) -> Path:
        if klass not in CLASS_NAMES:
            raise CgroupError(f'unknown memory policy class: {klass!r}')
        return self.session_dir / klass

    def _validate(self, identity: ProcessIdentity) -> Path:
        if self._shutdown:
            raise CgroupError('session hierarchy is shut down')
        if identity.pid <= 0:
            raise IdentityError('invalid pid')
        try:
            current = read_process_identity(identity.pid)
        except (FileNotFoundError, ProcessLookupError) as exc:
            raise IdentityError(f'pid {identity.pid} exited before validation') from exc
        if current.starttime != identity.starttime:
            raise IdentityError(
                f'pid {identity.pid} starttime changed (pid reuse): '
                f'{identity.starttime} != {current.starttime}'
            )
        if current.uid != identity.uid:
            raise IdentityError(f'pid {identity.pid} uid changed')
        if current.cgroup != identity.cgroup:
            raise IdentityError(
                f'pid {identity.pid} cgroup changed during validation: '
                f'{identity.cgroup} -> {current.cgroup}'
            )
        if current.starttime < self.min_starttime:
            raise IdentityError(
                f'pid {identity.pid} predates the active AaaS session '
                f'({current.starttime} < {self.min_starttime})'
            )
        directory = cgroup_dir(current.cgroup, self.mount)
        if not is_under(directory, self.root):
            raise IdentityError(
                f'pid {identity.pid} is outside the delegated AaaS scope: '
                f'{current.cgroup}'
            )
        return directory

    def _move(self, pid: int, target: Path) -> None:
        _write(target / 'cgroup.procs', pid)

    def apply_class(
        self,
        identity: ProcessIdentity,
        klass: str,
        anchor: bool = False,
    ) -> ApplyResult:
        """Place a verified process in its policy class.

        Anchors (boot chain) are protected in place.  Other processes move to
        the session class leaf.  The original libprocessgroup cgroup is retained
        so cleanup can move survivors back before removing the hierarchy.
        """

        if klass not in CLASS_NAMES:
            raise CgroupError(f'unknown memory policy class: {klass!r}')
        directory = self._validate(identity)
        pidfd = _pidfd(identity.pid)
        try:
            managed = self.processes.get(identity.pid)
            if managed is not None and managed.identity.starttime != identity.starttime:
                managed = None
            previous = managed.klass if managed is not None else None

            if anchor:
                original_cgroup = managed.original_cgroup if managed else identity.cgroup
                if managed is not None and managed.moved and original_cgroup:
                    original = cgroup_dir(original_cgroup, self.mount)
                    if original.is_dir():
                        self._move(identity.pid, original)
                # Re-read because the process may just have been restored.
                directory = cgroup_dir(
                    read_process_identity(identity.pid).cgroup, self.mount)
                write_policy(directory, ANCHOR_POLICY)
                self.processes[identity.pid] = ManagedProcess(
                    identity=identity, klass=klass,
                    original_cgroup=original_cgroup,
                    anchor=True, moved=False, updated_ns=time.monotonic_ns(),
                )
                return ApplyResult(identity.pid, klass, previous, identity.cgroup, False, True)

            target = self.class_dir(klass)
            original_cgroup = managed.original_cgroup if managed else identity.cgroup
            original_dir = cgroup_dir(original_cgroup, self.mount)
            # Existing charges do not follow a migrated process.  Protect the
            # original leaf as well so the process's already-faulted memory is
            # covered by the same class policy.
            if (not is_under(original_dir, self.session_dir)
                    and original_dir.is_dir()):
                current_bytes = int(_read_optional(original_dir / 'memory.current') or 0)
                write_policy(original_dir, in_place_policy(klass, current_bytes))
            moved = directory != target
            if moved:
                self._move(identity.pid, target)
                observed = read_process_identity(identity.pid).cgroup
                expected = str(target.relative_to(self.mount))
                expected = '/' + expected.lstrip('/')
                if observed != expected:
                    raise CgroupError(
                        f'pid {identity.pid} did not move to {expected}: {observed}'
                    )
            self.processes[identity.pid] = ManagedProcess(
                identity=identity, klass=klass, original_cgroup=original_cgroup,
                anchor=False, moved=True, updated_ns=time.monotonic_ns(),
            )
            return ApplyResult(identity.pid, klass, previous, str(target), moved, False)
        finally:
            if pidfd is not None:
                os.close(pidfd)

    def prune(self) -> list[int]:
        removed = []
        for pid, managed in list(self.processes.items()):
            gone = False
            try:
                current = read_process_identity(pid)
                gone = current.starttime != managed.identity.starttime
            except (FileNotFoundError, ProcessLookupError):
                gone = True
            if gone:
                # The pid leaf may still own charges after the process exits.
                # Reset its class policy before forgetting the process.
                self._reset_original(managed)
                removed.append(pid)
                del self.processes[pid]
        return removed

    def _reset_original(self, managed: ManagedProcess) -> None:
        if not managed.original_cgroup:
            return
        try:
            original = cgroup_dir(managed.original_cgroup, self.mount)
            if original.is_dir():
                write_policy(original, MemoryPolicy())
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            pass

    def _restore_one(self, pid: int, managed: ManagedProcess) -> str | None:
        try:
            current = read_process_identity(pid)
            if current.starttime != managed.identity.starttime:
                # The original process is gone and the PID was reused.
                self._reset_original(managed)
                return None
            directory = cgroup_dir(current.cgroup, self.mount)
            if managed.anchor:
                if is_under(directory, self.root) and directory.is_dir():
                    write_policy(directory, MemoryPolicy())
                return None
            if not managed.moved or not managed.original_cgroup:
                return None
            original = cgroup_dir(managed.original_cgroup, self.mount)
            if not original.is_dir():
                return f'original cgroup is gone: {managed.original_cgroup}'
            if current.cgroup != managed.original_cgroup:
                self._move(pid, original)
                observed = read_process_identity(pid).cgroup
                if observed != managed.original_cgroup:
                    return f'restore failed: {observed} != {managed.original_cgroup}'
            if original.is_dir():
                write_policy(original, MemoryPolicy())
            return None
        except (FileNotFoundError, ProcessLookupError):
            # The process or its pid leaf disappeared during Android shutdown.
            # Its pid leaf may still own charges, so reset the policy too.
            self._reset_original(managed)
            return None
        except (PermissionError, OSError) as exc:
            return f'{type(exc).__name__}: {exc}'

    def restore_all(self) -> dict[int, str]:
        failures = {}
        for pid, managed in list(self.processes.items()):
            error = self._restore_one(pid, managed)
            if error:
                failures[pid] = error
            else:
                self.processes.pop(pid, None)
        return failures

    def state(self) -> dict:
        classes = {}
        for klass in CLASS_NAMES:
            directory = self.class_dir(klass)
            try:
                processes = len((_read_optional(directory / 'cgroup.procs') or '').split())
            except OSError:
                processes = 0
            classes[klass] = {
                'path': str(directory),
                'policy': self.policies[klass].as_dict(),
                'memory.current': _read_optional(directory / 'memory.current'),
                'memory.low': _read_optional(directory / 'memory.low'),
                'memory.high': _read_optional(directory / 'memory.high'),
                'memory.max': _read_optional(directory / 'memory.max'),
                'processes': processes,
            }
        return {
            'root': str(self.root),
            'session': str(self.session_dir),
            'min_starttime': self.min_starttime,
            'stale_policies_reset': len(self.stale_cleaned),
            'managed': [
                {
                    'pid': pid,
                    'starttime': managed.identity.starttime,
                    'android_pid': managed.identity.android_pid,
                    'name': managed.identity.name,
                    'class': managed.klass,
                    'anchor': managed.anchor,
                    'moved': managed.moved,
                    'original_cgroup': managed.original_cgroup,
                    'original_memory': (
                        {
                            'memory.current': _read_optional(
                                cgroup_dir(managed.original_cgroup, self.mount)
                                / 'memory.current'),
                            'memory.low': _read_optional(
                                cgroup_dir(managed.original_cgroup, self.mount)
                                / 'memory.low'),
                            'memory.high': _read_optional(
                                cgroup_dir(managed.original_cgroup, self.mount)
                                / 'memory.high'),
                        }
                        if managed.original_cgroup else None
                    ),
                }
                for pid, managed in sorted(self.processes.items())
            ],
            'classes': classes,
            'memory.current': _read_optional(self.session_dir / 'memory.current'),
            'memory.events': _read_optional(self.session_dir / 'memory.events'),
            'memory.pressure': _read_optional(self.session_dir / 'memory.pressure'),
        }

    def shutdown(self) -> dict:
        self._shutdown = True
        failures = {}
        for attempt in range(3):
            try:
                failures = self.restore_all()
            except Exception as exc:  # cleanup must never mask the session result
                failures = {'restore': f'{type(exc).__name__}: {exc}'}
                break
            if not failures or not all(
                    error.startswith('restore failed:')
                    for error in failures.values()):
                break
            if attempt < 2:
                # Android app processes may still be exiting after the
                # namespace init is stopped. Retry only a verified cgroup
                # read-back mismatch; permissions and missing-path errors
                # remain immediately visible to the caller.
                time.sleep(0.05)
        try:
            final_state = self.state()
        except Exception as exc:
            final_state = {'error': f'{type(exc).__name__}: {exc}'}
        for klass in CLASS_NAMES:
            try:
                self.class_dir(klass).rmdir()
            except FileNotFoundError:
                pass
            except OSError as exc:
                failures[klass] = f'rmdir {klass}: {exc}'
        try:
            self.session_dir.rmdir()
            removed = True
        except OSError as exc:
            removed = False
            failures['session'] = f'rmdir session: {exc}'
        return {'removed': removed, 'failures': failures, 'state': final_state}


def write_policy(directory: Path, policy: MemoryPolicy) -> None:
    _write(directory / 'memory.low', policy.low)
    _write(directory / 'memory.high', 'max' if policy.high is None else policy.high)
    _write(directory / 'memory.max', 'max' if policy.max is None else policy.max)
    _write(directory / 'memory.oom.group', policy.oom_group)


def _policy_is_default(directory: Path) -> bool:
    low = _read_optional(directory / 'memory.low')
    high = _read_optional(directory / 'memory.high')
    maximum = _read_optional(directory / 'memory.max')
    oom_group = _read_optional(directory / 'memory.oom.group')
    return (low in (None, '0') and high in (None, 'max')
            and maximum in (None, 'max') and oom_group in (None, '0'))


def cleanup_stale_in_place(root: Path) -> list[str]:
    """Reset policy values left on empty leaves by an earlier session.

    Only leaves with no attached processes are touched.  The launcher's
    single-instance lock guarantees that a live session is not sharing them.
    """

    cleaned = []

    def reset_empty(directory: Path) -> None:
        if not directory.is_dir():
            return
        if (_read_optional(directory / 'cgroup.procs') or '').strip():
            return
        if _policy_is_default(directory):
            return
        try:
            write_policy(directory, MemoryPolicy())
            cleaned.append(str(directory))
        except OSError:
            pass

    for branch in ('system', 'apps'):
        parent = root / branch
        if not parent.is_dir():
            continue
        for uid_dir in parent.glob('uid_*'):
            # Uid-level directories are intermediates (memory subtree enabled)
            # and must not carry a stale protection value.
            reset_empty(uid_dir)
            for pid_dir in uid_dir.glob('pid_*'):
                reset_empty(pid_dir)

    # Also sweep disposable/session children left by an interrupted run.
    for child in root.iterdir():
        if child.name in ('system', 'apps') or not child.is_dir():
            continue
        reset_empty(child)
        for leaf in child.iterdir():
            if leaf.is_dir() and leaf.name in CLASS_NAMES:
                reset_empty(leaf)
    return cleaned


@dataclass(frozen=True)
class AndroidPriority:
    pid: int
    name: str
    uid: str
    adj: int
    proc_state: int
    cached: bool


_PROC_RECORD = re.compile(r'ProcessRecord\{[0-9a-f]+ (\d+):([^/]+)/([^}]+)\}')
_OOM_ADJ = re.compile(r'oom adj:.*\bcur=(-?\d+)')
_PROC_STATE = re.compile(r'curProcState=(\d+)')
_CACHED = re.compile(r'cached=(true|false)')


def parse_activity_processes(text: str) -> dict[int, AndroidPriority]:
    """Parse the stable fields of ``dumpsys activity processes``."""

    records: dict[int, AndroidPriority] = {}
    current = None

    def flush():
        nonlocal current
        if current is None:
            return
        if current['adj'] is not None and current['proc_state'] is not None:
            records[current['pid']] = AndroidPriority(
                pid=current['pid'], name=current['name'], uid=current['uid'],
                adj=current['adj'], proc_state=current['proc_state'],
                cached=current['cached'],
            )
        current = None

    for line in text.splitlines():
        match = _PROC_RECORD.search(line)
        if match:
            flush()
            current = {
                'pid': int(match.group(1)),
                'name': match.group(2).strip(),
                'uid': match.group(3).strip(),
                'adj': None, 'proc_state': None, 'cached': False,
            }
            continue
        if current is None:
            continue
        oom = _OOM_ADJ.search(line)
        if oom:
            current['adj'] = int(oom.group(1))
        state = _PROC_STATE.search(line)
        if state:
            current['proc_state'] = int(state.group(1))
        cached = _CACHED.search(line)
        if cached:
            current['cached'] = cached.group(1) == 'true'
    flush()
    return records


def classify_priority(priority: AndroidPriority) -> str:
    if priority.cached or priority.adj >= 900 or priority.proc_state >= PROCESS_STATE_CACHED:
        return 'cached'
    if priority.adj < 0 or priority.proc_state <= PROCESS_STATE_PERSISTENT_UI:
        return 'critical'
    if priority.adj <= 200 or priority.proc_state <= PROCESS_STATE_IMPORTANT_FOREGROUND:
        return 'foreground'
    return 'background'


def classify_cgroup_fallback(cgroup: str) -> str | None:
    parts = Path(cgroup).parts
    if 'system' in parts:
        return 'critical'
    if 'apps' in parts:
        return 'background'
    return None


def is_anchor_name(name: str, cmdline: str = '') -> bool:
    if name in ANCHOR_NAMES:
        return True
    basename = Path(cmdline.split()[0]).name if cmdline.split() else ''
    return basename in ANCHOR_NAMES


class ProcessPolicyMonitor:
    """Bounded polling adapter from ActivityManager state to cgroup classes."""

    def __init__(
        self,
        session: CgroupSession,
        log_path: Path | None = None,
        interval: float = 2.0,
        dumpsys_timeout: float = 10.0,
        max_consecutive_errors: int = 5,
    ):
        self.session = session
        self.log_path = log_path
        self.interval = interval
        self.dumpsys_timeout = dumpsys_timeout
        self.max_consecutive_errors = max_consecutive_errors
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.ticks = 0
        self.errors = 0
        self.consecutive_errors = 0
        self.last_error: str | None = None
        self.transitions = 0
        self.degraded = False
        self._logged: set[tuple[int, int, str]] = set()

    def start(self) -> None:
        if self._thread is not None:
            raise CgroupError('monitor already started')
        self._thread = threading.Thread(target=self._run, name='aaas-memory-policy',
                                        daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 8.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # keep the Android session alive
                with self._lock:
                    self.errors += 1
                    self.consecutive_errors += 1
                    self.last_error = f'{type(exc).__name__}: {exc}'
                    if self.consecutive_errors >= self.max_consecutive_errors:
                        self.degraded = True
                self._log({'event': 'error', 'error': self.last_error})
            self._stop.wait(self.interval)

    def _log(self, record: dict) -> None:
        if self.log_path is None:
            return
        record = {'monotonic_ns': time.monotonic_ns(), **record}
        try:
            with self.log_path.open('a') as stream:
                stream.write(json.dumps(record, sort_keys=True) + '\n')
        except OSError:
            pass

    def _scan(self) -> list[ProcessIdentity]:
        identities = []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                identity = read_process_identity(int(entry.name))
            except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
                continue
            if identity.starttime < self.session.min_starttime:
                continue
            directory = cgroup_dir(identity.cgroup, self.session.mount)
            if not is_under(directory, self.session.root):
                continue
            identities.append(identity)
        return identities

    def _read_priorities(self) -> dict[int, AndroidPriority] | None:
        system_server = None
        for identity in self._scan():
            if 'system_server' in identity.cmdline.split():
                system_server = identity
                break
        if system_server is None:
            return None
        command = [
            'nsenter', '-t', str(system_server.pid), '-m', '-p', '-U', '-r',
            '--', '/system/bin/dumpsys', 'activity', 'processes',
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True,
                timeout=self.dumpsys_timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._log({'event': 'dumpsys_error', 'error': str(exc)})
            return None
        if completed.returncode != 0:
            self._log({'event': 'dumpsys_error', 'returncode': completed.returncode})
            return None
        return parse_activity_processes(completed.stdout)

    def tick(self) -> list[ApplyResult]:
        priorities = self._read_priorities()
        identities = self._scan()
        applied = []
        for identity in identities:
            priority = priorities.get(identity.android_pid) if priorities else None
            managed = self.session.processes.get(identity.pid)
            if priority is not None:
                klass = classify_priority(priority)
                name = priority.name
                source = 'activity_manager'
            elif managed is not None:
                klass = managed.klass
                name = managed.identity.name
                source = 'retained'
            else:
                klass = classify_cgroup_fallback(identity.cgroup)
                if klass is None:
                    continue
                name = identity.name
                source = 'cgroup'
            anchor = is_anchor_name(name, identity.cmdline)
            try:
                result = self.session.apply_class(identity, klass, anchor=anchor)
            except (CgroupError, OSError) as exc:
                self._log({'event': 'apply_error', 'pid': identity.pid,
                           'name': name, 'class': klass,
                           'error': f'{type(exc).__name__}: {exc}'})
                continue
            key = (identity.pid, identity.starttime, klass)
            if result.changed or key not in self._logged:
                self._logged.add(key)
                if result.changed:
                    self.transitions += 1
                self._log({
                    'event': 'class', 'pid': identity.pid,
                    'android_pid': identity.android_pid, 'name': name,
                    'class': klass, 'previous': result.previous,
                    'anchor': result.anchor, 'source': source,
                    'target': result.target,
                })
            applied.append(result)
        removed = self.session.prune()
        for pid in removed:
            self._log({'event': 'exit', 'pid': pid})
        with self._lock:
            self.ticks += 1
            self.consecutive_errors = 0
        return applied

    def summary(self) -> dict:
        with self._lock:
            return {
                'ticks': self.ticks,
                'errors': self.errors,
                'last_error': self.last_error,
                'transitions': self.transitions,
                'degraded': self.degraded,
                'state': self.session.state(),
            }
