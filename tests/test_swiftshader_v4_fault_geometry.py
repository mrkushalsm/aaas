import json
import unittest
from pathlib import Path


EVIDENCE = (Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' /
            'graphics' / 'v4-fault-geometry.json')


class SwiftShaderV4FaultGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(EVIDENCE.read_text())
        cls.fault = cls.data['historical_incident']

    def test_jit_effective_address_is_the_557th_row_of_live_target(self):
        fault = self.fault
        regs = fault['registers']
        target = fault['mapping_geometry']
        arithmetic = fault['address_calculation']
        base = int(target['target_base'], 16)
        r8 = int(regs['r8'], 16)
        rdx = int(regs['rdx'], 16)
        rcx = int(regs['rcx'], 16)
        rax = int(regs['rax'], 16)
        pitch = target['target_row_pitch_bytes']

        self.assertEqual(rcx, r8 + rdx)
        self.assertEqual(int(arithmetic['r8_minus_target_base'], 16), r8 - base)
        self.assertEqual(r8 - base, 556 * pitch)
        self.assertEqual(rdx, 832 * 4)
        self.assertEqual(rax, pitch)
        self.assertEqual(rcx + rax, int(fault['effective_address'], 16))
        self.assertEqual(rcx + rax, base + 557 * pitch + 832 * 4)
        self.assertEqual(fault['effective_address'],
                         target['first_unmapped_address'])

    def test_released_578_buffer_is_adjacent_alias_not_jit_target(self):
        fault = self.fault
        target = fault['mapping_geometry']
        released = fault['adjacent_released_allocation']
        mapped_start = int(target['tombstone_mapping_start'], 16)
        mapped_end = int(target['tombstone_mapping_end_inclusive'], 16)
        access = int(fault['effective_address'], 16)

        self.assertEqual(mapped_end - mapped_start + 1,
                         int(target['mapped_length'], 16))
        self.assertEqual(access, mapped_end + 1)
        self.assertEqual(access, int(released['base'], 16))
        self.assertEqual(target['target_height'], 557)
        self.assertEqual(released['height'], 578)
        self.assertTrue(fault['address_calculation']['one_past_target_mapping'])

    def test_corrected_candidate_and_both_resize_modes_are_recorded(self):
        correction = self.data['correction']
        candidate = correction['production_candidate']
        self.assertEqual(correction['commit'],
                         'f38251d52f4a49b5b8f690ded737c7d1143e2b45')
        self.assertFalse(candidate['diagnostics_enabled'])
        self.assertTrue(candidate['selected_by_default_runner'])

        runs = self.data['before_after_runtime_evidence']['post_fix']
        self.assertEqual(len(runs), 2)
        expected = ['720x1280', '960x578', '960x557', '960x565', '720x1280']
        for run in runs:
            self.assertEqual(run['sequence'], expected)
            self.assertEqual(run['result'], 'STOPPED')
            self.assertTrue(run['matching_android_frames'])
            self.assertTrue(run['presenter_imports_submissions_releases_balanced'])
            self.assertEqual(run['outstanding_buffers'], 0)


if __name__ == '__main__':
    unittest.main()
