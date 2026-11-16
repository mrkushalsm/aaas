import json
import re
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]

class FoundationTest(unittest.TestCase):
    def test_source_manifest(self):
        manifest = json.loads((ROOT / 'manifests/sources.json').read_text())
        self.assertEqual(len(manifest['report_sha256']), 64)
        names = [s['name'] for s in manifest['sources']]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn('digitalis', names)
        self.assertIn('drm_hwcomposer', names)
        self.assertTrue(all(re.fullmatch(r'[0-9a-f]{40}', s['revision']) for s in manifest['sources']))
        self.assertTrue(all(s['kind'] in ('standalone-git', 'repo-manifest', 'repo-project', 'repo-superproject', 'aosp-project-reference') for s in manifest['sources']))
        evidence = json.loads((ROOT / 'tests/fixtures/m0/source-verification.json').read_text())
        self.assertEqual({s['name'] for s in manifest['sources']}, {s['name'] for s in evidence})
        self.assertTrue(all(s['status'].startswith('verified') for s in evidence))

    def test_schema_contract(self):
        schema = json.loads((ROOT / 'benchmarks/record.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        for key in ('launch_first_present_ms', 'frame_interval_p99_ms', 'cpu_time_ms', 'memory_pss_mib', 'gpu_blits', 'cpu_copies', 'acquire_fence_count', 'release_fence_count'):
            self.assertIn(key, schema['properties'])

    def test_baseline_records(self):
        path = ROOT / 'results/m0/baselines.jsonl'
        if not path.exists(): self.skipTest('baseline not yet run')
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        self.assertEqual({x['runtime'] for x in rows}, {'waydroid', 'droidloom'})
        self.assertTrue(all(x['status'] != 'measured' and x['reason'] for x in rows))
        validator = Draft202012Validator(json.loads((ROOT / 'benchmarks/record.schema.json').read_text()))
        self.assertTrue(all(validator.is_valid(x) for x in rows))

if __name__ == '__main__': unittest.main()
