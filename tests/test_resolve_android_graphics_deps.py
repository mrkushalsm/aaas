from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts import resolve_android_graphics_deps as resolver


class GraphicsSourceResolverTest(unittest.TestCase):
    def test_finds_missing_source_below_build_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'build'
            log = Path(tmp) / 'probe.log'
            log.write_text(f'Error parsing directory "{root}/external/starlark-go/starlark"')
            self.assertEqual(resolver.missing_source(log, root),
                             'external/starlark-go/starlark')

    def test_rejects_missing_path_outside_build_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'probe.log'
            log.write_text('Error parsing directory "/tmp/elsewhere/external/x"')
            with self.assertRaisesRegex(ValueError, 'outside build root'):
                resolver.missing_source(log, Path(tmp) / 'build')

    def test_finds_missing_prebuilt_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'probe.log'
            log.write_text('Failed to run dumpvars: fork/exec '
                           'prebuilts/build-tools/linux-x86/bin/ckati: no such file or directory')
            self.assertEqual(resolver.missing_source(log, Path(tmp) / 'build'),
                             'prebuilts/build-tools/linux-x86/bin/ckati')

    def test_finds_missing_make_include(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'probe.log'
            log.write_text('build/make/core/soong_config.mk:10: error: '
                           'toolchain/pgo-profiles/sampling/afdo_profiles.mk: '
                           'No such file or directory')
            self.assertEqual(resolver.missing_source(log, Path(tmp) / 'build'),
                             'toolchain/pgo-profiles/sampling/afdo_profiles.mk')

    def test_uses_owning_superproject_project(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return (b")]}\'\n" + b'{"path":"external/starlark-go",'
                        b'"url":"https://android.googlesource.com/platform/external/starlark-go",'
                        b'"revision":"' + b'a' * 40 + b'"}')

        from urllib.error import HTTPError
        response_body = MagicMock()
        not_found = HTTPError('url', 404, 'missing', {}, response_body)
        with patch.object(resolver, 'urlopen', side_effect=[
                not_found, Response()]):
            entry = resolver.superproject_entry('b' * 40,
                                                 'external/starlark-go/starlark')
        response_body.close.assert_called_once_with()
        self.assertEqual(entry['path'], 'external/starlark-go')


if __name__ == '__main__':
    unittest.main()
