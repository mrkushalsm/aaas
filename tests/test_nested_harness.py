import json
import tempfile
import unittest
from pathlib import Path
from experiments.lipstick.nested_test import validate


class NestedHarnessTest(unittest.TestCase):
    def test_focus_resize_close_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            logs = {}
            for name in ('a', 'b'):
                path = Path(directory) / f'{name}.jsonl'
                kinds = ['expose', 'focus_in', 'resize', 'resize']
                if name == 'a': kinds.append('close')
                path.write_text(''.join(json.dumps({'event': kind, 'width': 400 + i, 'height': 300}) + '\n' for i, kind in enumerate(kinds)))
                logs[name] = path
            self.assertEqual(validate(logs), [])
            logs['a'].write_text('{"event":"expose"}\n')
            self.assertTrue(any('missing focus_in' in error for error in validate(logs)))


if __name__ == '__main__': unittest.main()
