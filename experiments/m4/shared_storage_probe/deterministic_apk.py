"""Normalize APK ZIP metadata before Android alignment and signing."""
from __future__ import annotations

from pathlib import Path
import zipfile

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def normalize_zip_timestamps(source: Path, destination: Path) -> None:
    """Copy an unsigned APK with stable entry ordering and DOS timestamps.

    Call before zipalign and apksig: both tools then produce stable offsets and
    signatures for unchanged inputs.  APK entry payloads and permissions are
    retained; only archive metadata is normalized.
    """
    with zipfile.ZipFile(source, 'r') as incoming, \
            zipfile.ZipFile(destination, 'w') as outgoing:
        outgoing.comment = incoming.comment
        for old in incoming.infolist():
            new = zipfile.ZipInfo(old.filename, FIXED_ZIP_TIME)
            new.compress_type = old.compress_type
            new.create_system = old.create_system
            new.external_attr = old.external_attr
            new.internal_attr = old.internal_attr
            new.extra = b''
            new.comment = old.comment
            new.flag_bits = old.flag_bits & ~0x08
            outgoing.writestr(new, incoming.read(old.filename),
                              compress_type=old.compress_type)
