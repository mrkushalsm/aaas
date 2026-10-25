import unittest

from scripts import probe_cgroup_delegation as probe


class CgroupDelegationTest(unittest.TestCase):
    def test_parses_single_v2_membership(self):
        self.assertEqual(probe.current_cgroup('0::/user.slice/test.scope\n'),
                         '/user.slice/test.scope')

    def test_rejects_ambiguous_or_relative_membership(self):
        for contents in ('', '0::/a\n0::/b\n', '0::/a/../b\n', '1:cpu:/a\n'):
            with self.subTest(contents=contents), self.assertRaises(ValueError):
                probe.current_cgroup(contents)


if __name__ == '__main__':
    unittest.main()
