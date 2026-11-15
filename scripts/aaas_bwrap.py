"""Resolve and validate the host Bubblewrap executable used by AaaS."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess


# Do not search user-writable PATH entries for a security boundary executable.
# Administrators can still use a non-standard installation through AAAS_BWRAP.
SYSTEM_SEARCH_PATH = os.pathsep.join((os.defpath, '/usr/local/bin'))
REQUIRED_OPTIONS = ('--as-pid-1', '--ro-bind', '--proc', '--unshare-net')


class BubblewrapError(RuntimeError):
    """Bubblewrap could not be safely resolved for this runtime."""


def _executable(path: Path, *, allow_script: bool = False) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
        metadata = resolved.stat()
        with resolved.open('rb') as stream:
            magic = stream.read(4)
    except OSError as error:
        raise BubblewrapError(f'cannot inspect Bubblewrap executable {path}: {error}') from error
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        raise BubblewrapError(f'Bubblewrap path is not an executable regular file: {resolved}')
    if magic != b'\x7fELF' and not (allow_script and magic.startswith(b'#!')):
        raise BubblewrapError(f'Bubblewrap must be an ELF executable: {resolved}')
    return resolved


def _validate_bwrap(path: Path) -> Path:
    executable = _executable(path)
    try:
        result = subprocess.run([str(executable), '--help'], capture_output=True,
                                text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise BubblewrapError(f'cannot query Bubblewrap capabilities at {executable}: {error}') from error
    help_text = result.stdout + result.stderr
    missing = [option for option in REQUIRED_OPTIONS if option not in help_text]
    if result.returncode or missing:
        detail = ', '.join(missing) if missing else f'exit status {result.returncode}'
        raise BubblewrapError(f'incompatible Bubblewrap executable {executable}: {detail}')
    return executable


def resolve_bwrap(environ=None, *, allow_trace_wrapper=True) -> Path:
    """Return an absolute validated Bubblewrap path.

    Normal operation searches only system directories, so a user-local tracing
    wrapper cannot shadow the real binary. ``AAAS_BWRAP`` is an explicit path
    override and must name a compatible ELF Bubblewrap. Diagnostics may opt in
    to an executable wrapper through ``AAAS_BWRAP_TRACE_WRAPPER``.
    """
    env = os.environ if environ is None else environ
    if allow_trace_wrapper and env.get('AAAS_BWRAP_TRACE_WRAPPER'):
        raw = env['AAAS_BWRAP_TRACE_WRAPPER']
        candidate = Path(raw)
        if not candidate.is_absolute():
            raise BubblewrapError('AAAS_BWRAP_TRACE_WRAPPER must be an absolute path')
        return _executable(candidate, allow_script=True)

    raw = env.get('AAAS_BWRAP')
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            raise BubblewrapError('AAAS_BWRAP must be an absolute path')
    else:
        located = shutil.which('bwrap', path=SYSTEM_SEARCH_PATH)
        if not located:
            raise BubblewrapError(
                'Bubblewrap was not found in system directories; install it or set AAAS_BWRAP')
        candidate = Path(located)
    return _validate_bwrap(candidate)
