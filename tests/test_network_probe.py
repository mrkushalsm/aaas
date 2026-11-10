import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE = ROOT / 'experiments/m4/networking/src/org/aaas/netprobe/MainActivity.java'
BUILDER = ROOT / 'experiments/m4/networking/build_probe.py'


class AndroidNetworkProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PROBE.read_text()
        cls.builder = BUILDER.read_text()

    def test_probe_checks_connectivitymanager_dns_and_verified_https(self):
        for expected in (
                'getActiveNetwork', 'getNetworkCapabilities',
                'getLinkProperties', 'hasCapability',
                'connectivitycheck.gstatic.com',
                'https://www.google.com/generate_204',
                'getCipherSuite', 'code != 204'):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.source)

    def test_probe_reports_result_through_downloads_provider(self):
        self.assertIn('content://media/external/downloads', self.source)
        self.assertIn('relative_path', self.source)
        self.assertIn('AaasNetworkProbe.txt', self.source)
        self.assertIn('openOutputStream', self.source)
        self.assertNotIn('WRITE_EXTERNAL_STORAGE', self.builder)

    def test_probe_bundle_is_a_debug_fixture_not_a_release_payload(self):
        manifest = self.builder.split('<manifest', 1)[1].split('</manifest>', 1)[0]
        self.assertIn('android.permission.INTERNET', manifest)
        self.assertIn('android.permission.ACCESS_NETWORK_STATE', manifest)
        self.assertRegex(manifest, r'android:minSdkVersion="24"')
        self.assertRegex(manifest, r'android:targetSdkVersion="24"')


if __name__ == '__main__':
    unittest.main()
