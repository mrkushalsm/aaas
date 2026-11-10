import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_ethernet_connectivity_overlay import verified_packaged_overlay, sha256

class PackagedEthernetTests(unittest.TestCase):
    def test_relocation_without_signing_keys_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'rootfs'
            out = Path(d) / 'overlay'
            out.mkdir()
            inputs = {}
            for rel in ('system/framework/framework-res.apk',
                        'vendor/overlay/goldfish_overlay_connectivity_gsi.apk',
                        'apex/com.android.tethering/javalib/service-connectivity.jar',
                        'system/priv-app/NetworkStack/NetworkStack.apk'):
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(rel.encode())
                inputs['/old/rootfs/' + rel] = sha256(p)
            outputs = {}
            for key, name in {'connectivity_overlay':'aaas_ethernet_connectivity_overlay.apk',
                              'service_connectivity_jar':'aaas_service-connectivity.jar',
                              'network_stack_apk':'aaas_NetworkStack.apk'}.items():
                p = out / name
                p.write_bytes(name.encode())
                outputs[key] = sha256(p)
            (out/'aaas_ethernet_connectivity_overlay.json').write_text(json.dumps(
                {'schema_version':3, 'inputs':inputs, 'outputs':outputs}))
            self.assertIsNotNone(verified_packaged_overlay(Path(d),root,out))
            target = root/'system/framework/framework-res.apk'
            original=target.read_bytes()
            target.write_bytes(b'wrong image')
            self.assertIsNone(verified_packaged_overlay(Path(d),root,out))
            target.write_bytes(original)
            (out/'aaas_NetworkStack.apk').write_bytes(b'tampered')
            self.assertIsNone(verified_packaged_overlay(Path(d),root,out))
