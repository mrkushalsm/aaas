"""Focused checks for the isolated SwiftShader diagnostic relinker."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/build_swiftshader_diagnostic_overlay.py'
SPEC = importlib.util.spec_from_file_location('swiftshader_diagnostic_build', SCRIPT)
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class BuildInputTests(unittest.TestCase):
    def test_resolves_explicit_alternate_patch(self):
        with tempfile.TemporaryDirectory() as temporary:
            patch = Path(temporary) / 'trace.patch'
            patch.write_text('diff --git a/file b/file\n')
            self.assertEqual(BUILD.resolve_patch_input(patch), patch.resolve())

    def test_cache_metadata_requires_named_cmake_setting(self):
        self.assertEqual(BUILD.cache_value(
            'CMAKE_BUILD_TYPE:STRING=Release\nAAAS_ANDROID_BUILD:BOOL=ON',
            'AAAS_ANDROID_BUILD'), 'ON')
        with self.assertRaisesRegex(ValueError, 'missing CMAKE_CXX_FLAGS'):
            BUILD.cache_value('AAAS_ANDROID_BUILD:BOOL=ON', 'CMAKE_CXX_FLAGS')

    def test_build_definition_validation_tracks_tracing_mode(self):
        common = '-D__ANDROID__=1'
        vulkan = f'clang++ {common} VkGetProcAddress.cpp'
        reactor = 'clang++ SubzeroReactor.cpp'
        trace = '-DAAAS_SWIFTSHADER_JIT_TRACE=1'
        with self.assertRaisesRegex(ValueError, 'diagnostic tracing'):
            BUILD.validate_build_definitions([vulkan, reactor], True)
        BUILD.validate_build_definitions(
            [vulkan + ' ' + trace, reactor + ' ' + trace], True)
        BUILD.validate_build_definitions([vulkan, reactor], False)
        with self.assertRaisesRegex(ValueError, 'unexpectedly enables'):
            BUILD.validate_build_definitions([vulkan + ' ' + trace, reactor], False)

    def test_requires_workspace_tmp_output_and_separate_source_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / 'tmp').mkdir()
            source = workspace / 'source'
            build = workspace / 'build'
            source.mkdir()
            build.mkdir()
            (source / 'build').mkdir()
            with self.assertRaisesRegex(ValueError, 'production Vulkan overlay'):
                BUILD.resolve_build_inputs(
                    workspace, source, build,
                    workspace / 'tmp/m1b83_sampling_lock_vulkan.so')
            with self.assertRaisesRegex(ValueError, 'separate'):
                BUILD.resolve_build_inputs(
                    workspace, source, source / 'build', workspace / 'tmp/test.so')

    def test_extracts_only_generated_objects_and_preserves_archive_link_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            build = root / 'build'
            (source / 'src/Vulkan').mkdir(parents=True)
            build.mkdir()
            (source / 'src/Vulkan/android_vk_swiftshader.lds').write_text('HMI;')
            (build / 'one.o').write_bytes(b'object')
            (build / 'libone.a').write_bytes(b'archive')
            command = (
                ': && c++ -shared -o libvk_swiftshader.so one.o '
                'libone.a -Wl,--version-script=' +
                str(source / 'src/Vulkan/android_vk_swiftshader.lds') +
                ' libone.a && cd ' + str(build))
            objects, archives, flags = BUILD.extract_link_inputs(
                [command], build, source)
            self.assertEqual(objects, [(build / 'one.o').resolve()])
            self.assertEqual(archives, [(build / 'libone.a').resolve()] * 2)
            self.assertTrue(any(flag.startswith('-Wl,--version-script=')
                                for flag in flags))

    def test_rejects_missing_or_duplicate_generated_objects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            build = root / 'build'
            (source / 'src/Vulkan').mkdir(parents=True)
            build.mkdir()
            (source / 'src/Vulkan/android_vk_swiftshader.lds').write_text('HMI;')
            base = ': && c++ -shared -o libvk_swiftshader.so '
            with self.assertRaisesRegex(ValueError, 'missing generated link input'):
                BUILD.extract_link_inputs([base + 'missing.o lib.a'], build, source)
            (build / 'one.o').write_bytes(b'object')
            with self.assertRaisesRegex(ValueError, 'duplicate object'):
                (build / 'lib.a').write_bytes(b'archive')
                BUILD.extract_link_inputs(
                    [base + 'one.o one.o lib.a'], build, source)


if __name__ == '__main__':
    unittest.main()
