from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.m4.shared_storage_probe.deterministic_apk import normalize_zip_timestamps


class DeterministicApkTests(unittest.TestCase):
    def test_normalization_stabilizes_zip_metadata_and_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.apk'
            outputs = (root / 'one.apk', root / 'two.apk')
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('classes.dex', b'dex-data')
            for output in outputs:
                normalize_zip_timestamps(source, output)
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            with zipfile.ZipFile(outputs[0]) as archive:
                entry = archive.getinfo('classes.dex')
                self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(archive.read('classes.dex'), b'dex-data')


if __name__ == '__main__':
    unittest.main()
