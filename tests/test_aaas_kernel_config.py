import gzip
from pathlib import Path
import tempfile
import unittest

from scripts import aaas_kernel_config


class KernelConfigFallbackTests(unittest.TestCase):
    def test_existing_proc_config_needs_no_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_config = root / 'proc-config.gz'
            proc_config.write_bytes(gzip.compress(b'CONFIG_VMAP_STACK=y\n'))
            result = aaas_kernel_config.prepare_proc_config_fallback(
                root / 'ipc', release='test', proc_config=proc_config, candidates=())
            self.assertIsNone(result)
            self.assertFalse((root / 'ipc').exists())

    def test_matching_kernel_config_is_compressed_for_android(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_config = root / 'proc-config.gz'
            kernel_config = root / 'config-test-kernel'
            expected = b'CONFIG_VMAP_STACK=y\nCONFIG_ANDROID_BINDERFS=y\n'
            kernel_config.write_bytes(expected)
            result = aaas_kernel_config.prepare_proc_config_fallback(
                root / 'ipc', release='test-kernel', proc_config=proc_config,
                candidates=(kernel_config,))
            self.assertEqual(gzip.decompress(result.read_bytes()), expected)
            self.assertEqual(result.parent, root / 'ipc')
            self.assertEqual(result.stat().st_mode & 0o777, 0o444)

    def test_missing_config_fails_with_actionable_message(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'running kernel configuration'):
                aaas_kernel_config.prepare_proc_config_fallback(
                    root / 'ipc', release='missing', proc_config=root / 'missing-proc',
                    candidates=(root / 'missing-file',))

    def test_generated_config_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kernel_config = root / 'config'
            kernel_config.write_bytes(b'CONFIG_VMAP_STACK=y\n')
            kwargs = dict(release='test', proc_config=root / 'absent',
                          candidates=(kernel_config,))
            first = aaas_kernel_config.prepare_proc_config_fallback(root / 'ipc', **kwargs)
            first_bytes = first.read_bytes()
            first.unlink()
            second = aaas_kernel_config.prepare_proc_config_fallback(root / 'ipc', **kwargs)
            self.assertEqual(second.read_bytes(), first_bytes)


if __name__ == '__main__':
    unittest.main()
