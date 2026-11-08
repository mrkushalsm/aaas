"""Host DRM render-device discovery for the Wayland presenter."""

from __future__ import annotations

import os
from pathlib import Path


class GraphicsDeviceError(RuntimeError):
    pass


def discover_render_node(dev_root='/dev/dri', *, env=None):
    """Select an accessible render node without assuming its numeric suffix."""
    env = os.environ if env is None else env
    root = Path(dev_root)
    requested = env.get('AAAS_DRM_RENDER_NODE')
    candidates = [Path(requested)] if requested else sorted(
        root.glob('renderD[0-9]*'), key=lambda path: path.name)
    for path in candidates:
        try:
            resolved = path.resolve(strict=True)
            if (resolved.parent != root.resolve(strict=True)
                    or not resolved.name.startswith('renderD')
                    or not resolved.is_char_device()
                    or not os.access(resolved, os.R_OK | os.W_OK)):
                continue
            return resolved
        except OSError:
            continue
    if requested:
        raise GraphicsDeviceError(
            f'AAAS_DRM_RENDER_NODE is not an accessible DRM render node: {requested}')
    raise GraphicsDeviceError(f'no accessible DRM render node found under {root}')
