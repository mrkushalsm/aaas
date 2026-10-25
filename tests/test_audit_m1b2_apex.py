from pathlib import Path
import tempfile
import unittest

from scripts import audit_m1b2_apex as audit


class ApexAuditTest(unittest.TestCase):
    def test_staged_apex_does_not_count_as_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apex = root / 'apex'
            for name in ('com.android.runtime', 'com.android.art'):
                directory = apex / name
                directory.mkdir(parents=True)
                (directory / 'apex_manifest.pb').write_bytes(b'manifest')
            (apex / 'apex-info-list.xml').write_text(
                '<apex-info-list>'
                '<apex-info moduleName="com.android.runtime" isActive="false"/>'
                '<apex-info moduleName="com.android.art" isActive="false"/>'
                '</apex-info-list>')
            log = root / 'apex.log'
            log.write_text('Failed to activate /system/apex/com.android.art.capex: '
                           'Failed to open loop-control: No such file or directory\n')
            result = audit.audit(root, log)
            self.assertTrue(result['required_runtime_staged'])
            self.assertFalse(result['required_runtime_active'])
            self.assertFalse(result['activation_verified'])
            self.assertEqual(result['loop_control_activation_failures'], 1)


if __name__ == '__main__':
    unittest.main()
