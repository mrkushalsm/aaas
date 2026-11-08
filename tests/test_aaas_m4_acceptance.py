import unittest

from scripts.aaas_m4_acceptance import REQUIRED_GATES, summarize_campaign


def passing_document():
    return {'final_autonomous_closure_campaign_2026_11_08': {
        'required_gates': {gate: {'status': 'PASS', 'evidence': ['session:test']}
                           for gate in REQUIRED_GATES}}}


class M4AcceptanceManifestTests(unittest.TestCase):
    def test_complete_manifest_computes_closed(self):
        self.assertEqual(('PASS/CLOSED', []), summarize_campaign(passing_document()))

    def test_missing_gate_cannot_pass(self):
        document = passing_document()
        del document['final_autonomous_closure_campaign_2026_11_08'][
            'required_gates']['pipewire_capture_outage']
        status, failures = summarize_campaign(document)
        self.assertEqual('PARTIAL/OPEN', status)
        self.assertTrue(any('pipewire_capture_outage' in item for item in failures))

    def test_failed_gate_cannot_pass(self):
        document = passing_document()
        document['final_autonomous_closure_campaign_2026_11_08'][
            'required_gates']['native_windows']['status'] = 'BLOCKED'
        self.assertEqual('PARTIAL/OPEN', summarize_campaign(document)[0])

    def test_gate_without_evidence_cannot_pass(self):
        document = passing_document()
        document['final_autonomous_closure_campaign_2026_11_08'][
            'required_gates']['automated_regression']['evidence'] = []
        self.assertEqual('PARTIAL/OPEN', summarize_campaign(document)[0])

    def test_missing_campaign_cannot_pass(self):
        self.assertEqual('PARTIAL/OPEN', summarize_campaign({})[0])


if __name__ == '__main__':
    unittest.main()
