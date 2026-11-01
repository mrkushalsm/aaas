import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from scripts import aaas_bluetooth


class BluetoothUnavailablePolicyTests(unittest.TestCase):
    def make_rootfs(self, root):
        for relative, body in {
            "vendor/etc/permissions/handheld_core_hardware.xml": (
                '<permissions>\n'
                '  <feature name="android.hardware.audio.output" />\n'
                '  <feature name="android.hardware.bluetooth" />\n'
                '  <feature name="android.hardware.bluetooth_le" />\n'
                '  <feature name="android.hardware.touchscreen" />\n'
                '</permissions>\n'),
            "vendor/etc/permissions/android.hardware.bluetooth.xml": (
                '<permissions><feature name="android.hardware.bluetooth" /></permissions>\n'),
            "vendor/etc/permissions/android.hardware.bluetooth_le.xml": (
                '<permissions><feature name="android.hardware.bluetooth_le" /></permissions>\n'),
            aaas_bluetooth.HAL_INIT: (
                'service vendor.bluetooth-default /vendor/bin/hw/bluetooth\n'
                '    class hal\n'),
            aaas_bluetooth.HAL_MANIFEST: (
                '<manifest version="9.0" type="device">'
                '<hal format="aidl"><name>android.hardware.bluetooth</name>'
                '<fqname>IBluetoothHci/default</fqname></hal></manifest>\n'),
            aaas_bluetooth.RANCHU_INIT: (
                'service unrelated /vendor/bin/unrelated\n'
                '    class main\n\n'
                'on property:vendor.qemu.vport.bluetooth=*\n'
                '    symlink ${vendor.qemu.vport.bluetooth} /dev/bluetooth0\n\n'
                'service bt_vhci_forwarder /vendor/bin/bt_vhci_forwarder -virtio_console_dev=/dev/bluetooth0\n'
                '    class main\n'
                '    user bluetooth\n'
                '    group root bluetooth\n\n'
                'on property:vendor.qemu.vport.uwb=*\n'
                '    start vendor.uwb_hal\n'),
        }.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)

    def test_policy_removes_only_bluetooth_features_and_hci_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rootfs"
            policy = Path(tmp) / "session" / "bluetooth-policy"
            self.make_rootfs(root)
            before = {
                relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
                for relative in (*aaas_bluetooth.FEATURE_FILES,
                                 aaas_bluetooth.HAL_INIT,
                                 aaas_bluetooth.HAL_MANIFEST,
                                 aaas_bluetooth.RANCHU_INIT)
            }

            receipt = aaas_bluetooth.create_unavailable_policy(root, policy)

            features = ET.parse(policy / aaas_bluetooth.FEATURE_FILES[0]).getroot()
            names = {node.get("name") for node in features.findall("feature")}
            self.assertEqual(names, {"android.hardware.audio.output",
                                     "android.hardware.touchscreen"})
            self.assertFalse(ET.parse(policy / aaas_bluetooth.HAL_MANIFEST)
                             .getroot().findall("hal"))
            self.assertNotIn(b"service vendor.bluetooth-default",
                             (policy / aaas_bluetooth.HAL_INIT).read_bytes())
            ranchu = (policy / aaas_bluetooth.RANCHU_INIT).read_text()
            self.assertNotIn("bt_vhci_forwarder", ranchu)
            self.assertIn("service unrelated", ranchu)
            self.assertIn("vendor.uwb_hal", ranchu)
            self.assertTrue(all(
                hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest
                for relative, digest in before.items()))
            self.assertFalse(receipt["base_image_modified"])
            self.assertEqual(receipt["policy"],
                             "bluetooth-unavailable-rootless-no-controller")
            self.assertTrue(all(
                (policy / relative).stat().st_mode & 0o444 == 0o444
                for relative in receipt["files"]))

    def test_policy_is_reproducible_and_binds_are_hash_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rootfs"
            self.make_rootfs(root)
            first = Path(tmp) / "session-a" / "policy"
            second = Path(tmp) / "session-b" / "policy"
            aaas_bluetooth.create_unavailable_policy(root, first)
            aaas_bluetooth.create_unavailable_policy(root, second)
            first_manifest = json.loads((first / "manifest.json").read_text())
            second_manifest = json.loads((second / "manifest.json").read_text())
            self.assertEqual(first_manifest, second_manifest)
            binds = aaas_bluetooth.policy_bind_command(first)
            self.assertEqual(binds.count("--ro-bind"), 6)
            self.assertIn("/vendor/etc/permissions/handheld_core_hardware.xml", binds)
            self.assertIn("/vendor/etc/init/hw/init.ranchu.rc", binds)
            target = first / aaas_bluetooth.HAL_INIT
            target.write_text("tampered")
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                aaas_bluetooth.policy_bind_command(first)

    def test_policy_rejects_missing_or_unexpected_base_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rootfs"
            self.make_rootfs(root)
            (root / aaas_bluetooth.RANCHU_INIT).write_text("service unrelated\n")
            with self.assertRaisesRegex(ValueError, "expected one Bluetooth VHCI"):
                aaas_bluetooth.create_unavailable_policy(
                    root, Path(tmp) / "policy")


if __name__ == "__main__":
    unittest.main()
