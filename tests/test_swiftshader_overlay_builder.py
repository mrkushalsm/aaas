import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "build_android_swiftshader_overlay.py"
SPEC = importlib.util.spec_from_file_location("swiftshader_overlay_builder", SCRIPT)
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class SwiftShaderOverlayBuilderTests(unittest.TestCase):
    def _run_builder(self, extra_args):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        workspace = pathlib.Path(temporary.name)
        (workspace / "sources/swiftshader/build").mkdir(parents=True)
        (workspace / "tmp").mkdir()
        output = workspace / "diagnostic.so"
        command = (
            "c++ -shared -o libvk_swiftshader.so object.cpp.o "
            "src/Reactor/libReactorSubzero.a"
        )
        with mock.patch.object(sys, "argv", [str(SCRIPT), "--workspace", str(workspace),
                                               "--output", str(output), *extra_args]), \
                mock.patch.object(BUILDER.subprocess, "run") as run, \
                mock.patch.object(BUILDER.subprocess, "check_output", return_value=command):
            BUILDER.main()
        return run.call_args_list

    def test_diagnostic_archive_override_skips_ninja(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = pathlib.Path(temporary) / "libReactorSubzero-trace.a"
            calls = self._run_builder([
                "--skip-ninja", "--reactor-subzero-archive", str(archive),
            ])
        self.assertEqual(len(calls), 2)  # shim compile and final relink
        link = calls[-1].args[0]
        self.assertIn(str(archive.resolve()), link)
        self.assertNotIn("/sources/swiftshader/build/src/Reactor/libReactorSubzero.a", link)

    def test_default_build_keeps_pinned_archive_path(self):
        calls = self._run_builder([])
        self.assertEqual(len(calls), 3)  # Ninja, shim compile, final relink
        self.assertEqual(calls[0].args[0][-1], "ReactorSubzero")
        link = calls[-1].args[0]
        self.assertTrue(any(item.endswith("/build/src/Reactor/libReactorSubzero.a")
                            for item in link))


if __name__ == "__main__":
    unittest.main()
