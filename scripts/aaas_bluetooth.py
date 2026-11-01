"""Session-scoped Android Bluetooth-unavailable policy for rootless AaaS."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET


BLUETOOTH = "android.hardware.bluetooth"
BLUETOOTH_LE = "android.hardware.bluetooth_le"

FEATURE_FILES = (
    "vendor/etc/permissions/handheld_core_hardware.xml",
    "vendor/etc/permissions/android.hardware.bluetooth.xml",
    "vendor/etc/permissions/android.hardware.bluetooth_le.xml",
)
HAL_INIT = "vendor/etc/init/bluetooth-service-default.rc"
HAL_MANIFEST = "vendor/etc/vintf/manifest/bluetooth-service-default.xml"
RANCHU_INIT = "vendor/etc/init/hw/init.ranchu.rc"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _remove_features(source: bytes, names: set[str], path: str) -> bytes:
    try:
        root = ET.fromstring(source)
    except ET.ParseError as error:
        raise ValueError(f"invalid Android feature XML: {path}") from error
    if root.tag != "permissions":
        raise ValueError(f"unexpected Android feature XML root in {path}")
    removed = set()
    for child in list(root):
        if child.tag == "feature" and child.get("name") in names:
            removed.add(child.get("name"))
            root.remove(child)
    if not removed.issubset(names):
        raise ValueError(f"unexpected feature removal in {path}")
    # Preserve comments, whitespace, declarations, and unrelated features by
    # removing only the exact self-closing feature elements.
    text = source.decode("utf-8")
    for name in removed:
        pattern = rf"<feature\s+name=[\"']{re.escape(name)}[\"']\s*/>"
        text, count = re.subn(pattern, "", text)
        if count != 1:
            raise ValueError(f"expected one removable {name} element in {path}, got {count}")
    return text.encode("utf-8")


def _without_ranchu_bluetooth(source: bytes) -> bytes:
    text = source.decode("utf-8")
    pattern = (
        r"(?m)^on property:vendor\.qemu\.vport\.bluetooth=\*\n"
        r"    symlink \$\{vendor\.qemu\.vport\.bluetooth\} /dev/bluetooth0\n"
        r"\nservice bt_vhci_forwarder /vendor/bin/bt_vhci_forwarder -virtio_console_dev=/dev/bluetooth0\n"
        r"    class main\n"
        r"    user bluetooth\n"
        r"    group root bluetooth\n"
    )
    text, count = re.subn(pattern, "\n", text)
    if count != 1:
        raise ValueError(f"expected one Bluetooth VHCI block in {RANCHU_INIT}, got {count}")
    return text.encode("utf-8")


def create_unavailable_policy(rootfs: Path, destination: Path) -> dict:
    """Derive a minimal no-controller view without modifying the Android image."""
    rootfs = Path(rootfs)
    destination = Path(destination)
    originals: dict[str, Path] = {}
    outputs: dict[str, bytes] = {}

    for relative in FEATURE_FILES:
        original = rootfs / relative
        if not original.is_file():
            raise FileNotFoundError(f"required Android feature file missing: {original}")
        originals[relative] = original
        names = {BLUETOOTH, BLUETOOTH_LE}
        outputs[relative] = _remove_features(original.read_bytes(), names, relative)

    # The no-controller profile must not expose or launch the emulator HCI HAL.
    for relative in (HAL_INIT, HAL_MANIFEST):
        original = rootfs / relative
        if not original.is_file():
            raise FileNotFoundError(f"required Android Bluetooth HAL file missing: {original}")
        originals[relative] = original
    outputs[HAL_INIT] = (
        b"# Bluetooth HCI HAL intentionally absent in rootless AaaS mode.\n"
    )
    outputs[HAL_MANIFEST] = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b'<manifest version="9.0" type="device"/>\n'
    )

    original = rootfs / RANCHU_INIT
    if not original.is_file():
        raise FileNotFoundError(f"required Android init file missing: {original}")
    originals[RANCHU_INIT] = original
    outputs[RANCHU_INIT] = _without_ranchu_bluetooth(original.read_bytes())

    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    file_records = {}
    for relative, payload in outputs.items():
        target = destination / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(payload)
        # Android framework/init/VINTF readers are non-root; match read-only
        # system configuration-file permissions rather than the private
        # session receipt permissions.
        target.chmod(0o644)
        file_records[relative] = {
            "base_sha256": _sha256(originals[relative]),
            "overlay_sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }

    # Verify the generated declarations, rather than trusting the text edits.
    for relative in FEATURE_FILES:
        root = ET.parse(destination / relative).getroot()
        advertised = {node.get("name") for node in root.findall("feature")}
        if {BLUETOOTH, BLUETOOTH_LE} & advertised:
            raise ValueError(f"Bluetooth feature remains advertised in {relative}")
    manifest = ET.parse(destination / HAL_MANIFEST).getroot()
    if manifest.findall("hal"):
        raise ValueError("Bluetooth HCI HAL remains declared")
    if b"bt_vhci_forwarder" in outputs[RANCHU_INIT]:
        raise ValueError("Bluetooth VHCI forwarder remains configured")

    receipt = {
        "schema_version": 1,
        "policy": "bluetooth-unavailable-rootless-no-controller",
        "base_image_modified": False,
        "android_features_removed": [BLUETOOTH, BLUETOOTH_LE],
        "bluetooth_hci_hal": "not declared or started",
        "files": file_records,
    }
    receipt_path = destination / "manifest.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    receipt_path.chmod(0o600)
    return receipt


def policy_bind_command(policy_dir: Path) -> str:
    """Return bwrap read-only binds for the known, complete policy payload."""
    policy_dir = Path(policy_dir).resolve(strict=True)
    records = json.loads((policy_dir / "manifest.json").read_text())
    if records.get("policy") != "bluetooth-unavailable-rootless-no-controller":
        raise ValueError("unsupported Bluetooth runtime policy manifest")
    targets = (*FEATURE_FILES, HAL_INIT, HAL_MANIFEST, RANCHU_INIT)
    binds = []
    for relative in targets:
        source = (policy_dir / relative).resolve(strict=True)
        expected = records.get("files", {}).get(relative, {}).get("overlay_sha256")
        if not expected or _sha256(source) != expected:
            raise ValueError(f"Bluetooth policy artifact missing or changed: {relative}")
        binds.append(f'  --ro-bind "{source}" /{relative} \\\n')
    return "".join(binds)
