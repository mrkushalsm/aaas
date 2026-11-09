"""Host DRM render-device discovery for the Wayland presenter."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess


class GraphicsDeviceError(RuntimeError):
    pass


def discover_render_node(dev_root='/dev/dri', *, env=None):
    """Choose the compositor's DRM render device to avoid cross-GPU imports.

    Wayland linux-dmabuf feedback identifies the compositor's main device. If
    it is unavailable, automatic selection is allowed only when exactly one
    accessible render node exists.
    """
    env = os.environ if env is None else env
    root = Path(dev_root)
    requested = env.get('AAAS_DRM_RENDER_NODE')
    candidates = sorted(root.glob('renderD[0-9]*'), key=lambda path: path.name)

    def validate(path):
        try:
            resolved = path.resolve(strict=True)
            if (resolved.parent != root.resolve(strict=True)
                    or not resolved.name.startswith('renderD')
                    or not resolved.is_char_device()
                    or not os.access(resolved, os.R_OK | os.W_OK)):
                return None
            return resolved
        except OSError:
            return None

    if requested:
        selected = validate(Path(requested))
        if selected:
            return selected
        raise GraphicsDeviceError(
            f'AAAS_DRM_RENDER_NODE is not an accessible DRM render node: {requested}')

    accessible = [node for candidate in candidates if (node := validate(candidate))]
    wayland_info = shutil.which('wayland-info')
    detail = 'wayland-info is unavailable'
    if wayland_info:
        try:
            report = subprocess.run([wayland_info], capture_output=True, text=True,
                                    env=dict(env), timeout=8, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            detail = str(error)
        else:
            detail = f'wayland-info exited {report.returncode}'
            match = re.search(r"main device:[^\n]*?/dev/dri/(renderD[0-9]+)",
                              report.stdout + '\n' + report.stderr)
            if match:
                selected = validate(root / match.group(1))
                if selected:
                    return selected
                raise GraphicsDeviceError(
                    f'compositor main DRM device is not accessible: {match.group(1)}')

    if len(accessible) == 1:
        return accessible[0]
    if not accessible:
        raise GraphicsDeviceError(f'no accessible DRM render node found under {root}')
    raise GraphicsDeviceError(
        'multiple DRM render nodes are accessible but the compositor main device '
        f'could not be determined ({detail}); set AAAS_DRM_RENDER_NODE explicitly')
