"""Prepare a private Android-visible copy of the running host kernel config."""

from __future__ import annotations

import gzip
import os
from pathlib import Path
import platform
import tempfile


def prepare_proc_config_fallback(
        ipc_dir: Path, release: str | None = None, *,
        proc_config: Path = Path('/proc/config.gz'),
        candidates: tuple[Path, ...] | None = None) -> Path | None:
    """Stage CONFIG_GZ only when this kernel does not expose /proc/config.gz.

    Android 16's Debug.isVmapStack() requires kernel configs and fatally aborts
    system_server when CONFIG_GZ is unavailable. Prefer the live procfs export;
    otherwise use the config installed for the exact running kernel. The file is
    placed in the session IPC directory, which the runtime already binds read-
    only into Android at /dev/aaas.
    """
    proc_config = Path(proc_config)
    if proc_config.is_file() and os.access(proc_config, os.R_OK):
        return None

    kernel_release = release or platform.uname().release
    if candidates is None:
        candidates = (
            Path('/boot') / f'config-{kernel_release}',
            Path('/usr/lib/modules') / kernel_release / 'config',
            Path('/lib/modules') / kernel_release / 'build/.config',
        )
    source = next((candidate for candidate in candidates
                   if candidate.is_file() and os.access(candidate, os.R_OK)), None)
    if source is None:
        searched = ', '.join(str(path) for path in candidates)
        raise RuntimeError(
            'Android requires the running kernel configuration for CONFIG_GZ, but '
            f'/proc/config.gz is unavailable and no readable matching config was found; '
            f'searched: {searched}')

    data = source.read_bytes()
    if b'CONFIG_' not in data or b'CONFIG_VMAP_STACK' not in data:
        raise RuntimeError(f'kernel configuration at {source} is incomplete or invalid')

    ipc_dir = Path(ipc_dir)
    ipc_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.kernel-config-', suffix='.gz', dir=ipc_dir)
    temporary = Path(name)
    target = ipc_dir / f'kernel-config-{os.getpid()}.gz'
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(gzip.compress(data, mtime=0))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o444)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target
