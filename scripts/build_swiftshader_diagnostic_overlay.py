#!/usr/bin/env python3
"""Build and attest a coherent Android SwiftShader diagnostic overlay.

The source tree must be an isolated worktree at the pinned revision with the
committed coherent diagnostic patch applied. CMake compiles the full target
graph; this script then relinks those exact objects and archives against the
runtime's Bionic libraries and the project's Android HAL shim.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


PINNED_REVISION = 'cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5'
PRODUCTION_SHA256 = '1b29507504c649431380d689e27325c5ad23b742ea430d55758fb31045ee3181'
PRODUCTION_BUILD_ID = '48176d3bf7c52ad4a2e1c8445fac8d52b83864ba'
ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def run(command, *, capture=False):
    return subprocess.run(command, check=True, text=True,
                          capture_output=capture)


def resolve_build_inputs(workspace, source, build, output):
    workspace = workspace.resolve(strict=True)
    source = source.resolve(strict=True)
    build = build.resolve(strict=True)
    output = output.resolve()
    tmp = (workspace / 'tmp').resolve(strict=True)
    output.relative_to(tmp)
    if output == tmp / 'm1b83_sampling_lock_vulkan.so':
        raise ValueError('refusing to overwrite the production Vulkan overlay')
    if build == source or source in build.parents or build in source.parents:
        raise ValueError('source and build directories must be separate')
    return workspace, source, build, output


def get_build_commands(build):
    return run(['ninja', '-C', str(build), '-t', 'commands',
                'vk_swiftshader'], capture=True).stdout.splitlines()


def extract_link_inputs(commands, build, source):
    links = [line for line in commands
             if ' -shared ' in line and 'libvk_swiftshader.so' in line]
    if not links:
        raise ValueError('Ninja did not expose a vk_swiftshader shared link command')
    raw = links[-1].split(' && cd ', 1)[0]
    raw = raw.removeprefix(': && ')
    parts = shlex.split(raw)
    objects, archives, flags = [], [], []
    index = 0
    while index < len(parts):
        item = parts[index]
        if item == '-o':
            index += 2
            continue
        if item.startswith(('-Wl,--dependency-file=', '-Wl,-rpath,',
                            '-Wl,-rpath-link,')):
            index += 1
            continue
        if item.endswith(('.o', '.a')):
            path = Path(item)
            if not path.is_absolute():
                path = build / path
            if not path.is_file():
                raise ValueError(f'missing generated link input: {path}')
            (objects if path.suffix == '.o' else archives).append(path.resolve())
        elif item.endswith('.so') and item.startswith('/'):
            # CMake's host linker line names Android rootfs libraries here.
            pass
        elif item.startswith('-Wl,--version-script='):
            version_script = Path(item.split('=', 1)[1]).resolve()
            expected = (source / 'src/Vulkan/android_vk_swiftshader.lds').resolve()
            if version_script != expected:
                raise ValueError(f'wrong Android export map: {version_script}')
            flags.append(item)
        else:
            flags.append(item)
        index += 1
    if not objects or not archives:
        raise ValueError('complete Vulkan objects and static archives are required')
    if len(objects) != len(set(objects)):
        raise ValueError('duplicate object in CMake link graph')
    return objects, archives, flags


def validate_build_definitions(commands, diagnostics_enabled):
    proc = next((line for line in commands if 'VkGetProcAddress.cpp' in line), '')
    reactor = next((line for line in commands if 'SubzeroReactor.cpp' in line), '')
    pipeline = next((line for line in commands if 'PixelRoutine.cpp' in line), '')
    if '-D__ANDROID__=1' not in proc:
        raise ValueError('Android HAL definition is missing from Vulkan build')
    trace_flag = '-DAAAS_SWIFTSHADER_JIT_TRACE=1'
    if diagnostics_enabled:
        if trace_flag not in proc:
            raise ValueError('diagnostic tracing is missing from Vulkan build')
        if trace_flag not in reactor:
            raise ValueError('JIT tracing is missing from the Reactor build')
        if trace_flag not in pipeline:
            raise ValueError('pixel routine tracing is missing from the pipeline build')
    elif trace_flag in proc or trace_flag in reactor or trace_flag in pipeline:
        raise ValueError('non-tracing build unexpectedly enables JIT tracing')


def cache_value(cache_text, name):
    prefix = name + ':'
    line = next((line for line in cache_text.splitlines()
                 if line.startswith(prefix)), None)
    if line is None:
        raise ValueError(f'incompatible CMake configuration: missing {name}')
    return line.split('=', 1)[1]


def resolve_patch_input(path):
    patch = ROOT / 'experiments/m1e/patches/swiftshader_coherent_diagnostic.patch'
    return (path if path is not None else patch).resolve(strict=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--patch', type=Path,
                        help='alternate explicit source patch for controlled diagnostics')
    parser.add_argument('--no-tracing', action='store_true',
                        help='build the same coherent source without diagnostic tracing')
    args = parser.parse_args(argv)
    try:
        workspace, source, build, output = resolve_build_inputs(
            args.workspace, args.source, args.build, args.output)
        run([sys.executable, str(ROOT / 'scripts/android_workspace.py'),
             '--workspace', str(workspace), 'check'])
        revision = run(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                       capture=True).stdout.strip()
        if revision != PINNED_REVISION:
            raise ValueError(f'SwiftShader source revision mismatch: {revision}')
        status = run(['git', '-C', str(source), 'status', '--porcelain'],
                     capture=True).stdout
        if any(line.startswith('??') for line in status.splitlines()):
            raise ValueError('untracked source files make the diagnostic build ambiguous')
        patch = resolve_patch_input(args.patch)
        diff = run(['git', '-C', str(source), 'diff', '--binary', 'HEAD'],
                   capture=True).stdout.encode()
        patch_hash = hashlib.sha256(patch.read_bytes()).hexdigest()
        if hashlib.sha256(diff).hexdigest() != patch_hash:
            raise ValueError('isolated source diff does not match the committed patch')
        cache_path = build / 'CMakeCache.txt'
        cache_text = cache_path.read_text()
        diagnostics_enabled = not args.no_tracing
        required_cache = (
            'AAAS_ANDROID_BUILD:BOOL=ON',
            f'AAAS_SWIFTSHADER_DIAGNOSTICS:BOOL={"OFF" if args.no_tracing else "ON"}',
            f'AAAS_ANDROID_HEADERS:PATH={workspace / "sources"}',
            f'AAAS_ANDROID_ROOTFS:PATH={workspace / "rootfs_m1b1"}',
            'REACTOR_BACKEND:STRING=Subzero',
        )
        for item in required_cache:
            if item not in cache_text:
                raise ValueError(f'incompatible CMake configuration: missing {item}')

        run(['ninja', '-C', str(build), 'vk_swiftshader'])
        commands = get_build_commands(build)
        validate_build_definitions(commands, diagnostics_enabled)
        objects, archives, flags = extract_link_inputs(commands, build, source)

        shim = build / 'aaas_bionic_stubs.o'
        run(['/usr/bin/c++', '-fPIC', '-O2', '-c',
             str(ROOT / 'experiments/m1b/swiftshader/bionic_stubs.cpp'),
             '-o', str(shim)])
        rootfs_lib = workspace / 'rootfs_m1b1/system/lib64'
        command = [
            '/usr/bin/c++', '-shared', '-fPIC', '-O2', '-static-libstdc++',
            '-static-libgcc', '-Wl,-Bsymbolic', '-Wl,--no-undefined',
            '-Wl,--version-script=' + str(source / 'src/Vulkan/android_vk_swiftshader.lds'),
            '-Wl,-soname,vulkan.pastel.so', '-o', str(output),
            *(str(path) for path in objects), str(shim),
            *(str(path) for path in archives), '-ldl', '-lpthread', '-lrt',
            '-L' + str(rootfs_lib), '-lnativewindow', '-lsync',
        ]
        run(command)

        dynamic = run(['readelf', '-d', str(output)], capture=True).stdout
        needed = [line.split('[', 1)[1].split(']', 1)[0]
                  for line in dynamic.splitlines() if '(NEEDED)' in line]
        if any(name in dynamic for name in ('RPATH', 'RUNPATH')):
            raise ValueError('diagnostic overlay contains an absolute runtime path')
        expected_needed = {'libdl.so', 'libnativewindow.so', 'libsync.so',
                           'libm.so', 'libc.so'}
        if set(needed) - expected_needed:
            raise ValueError(f'host or unexpected dependencies: {needed}')
        symbols = run(['nm', '-D', str(output)], capture=True).stdout
        for symbol in (' HMI', ' vk_icdGetInstanceProcAddr',
                       ' vk_icdNegotiateLoaderICDInterfaceVersion'):
            if symbol not in symbols:
                raise ValueError(f'missing required Android ICD export:{symbol}')
        note = run(['readelf', '-n', str(output)], capture=True).stdout
        build_id = next((line.split('Build ID:', 1)[1].strip()
                         for line in note.splitlines() if 'Build ID:' in line), None)
        if not build_id:
            raise ValueError('diagnostic overlay has no ELF Build ID')
        production = workspace / 'tmp/m1b83_sampling_lock_vulkan.so'
        production_hash = sha256(production)
        if production_hash != PRODUCTION_SHA256:
            raise ValueError('production overlay does not match its pinned identity')
        headers = []
        for header in (
            workspace / 'sources/frameworks-native-qpr2/libs/nativewindow/include/android/hardware_buffer.h',
            workspace / 'sources/frameworks-native-qpr2/vulkan/include/hardware/hwvulkan.h',
            workspace / 'sources/logging-android16/liblog/include/android/log.h',
            workspace / 'sources/core-android16/libsync/include/sync/sync.h',
        ):
            if header.is_file():
                headers.append({'path': str(header), 'sha256': sha256(header)})
        manifest = {
            'schema_version': 1,
            'source_revision': revision,
            'source_diff_sha256': patch_hash,
            'android_build': True,
            'diagnostics_enabled': diagnostics_enabled,
            'source_dirty_files': status.splitlines(),
            'build': {
                'directory': str(build), 'generator': 'Ninja',
                'target': 'vk_swiftshader',
                'cmake_cache_sha256': sha256(cache_path),
                'configuration': {
                    'build_type': cache_value(cache_text, 'CMAKE_BUILD_TYPE'),
                    'cxx_flags': cache_value(cache_text, 'CMAKE_CXX_FLAGS'),
                    'release_cxx_flags': cache_value(cache_text, 'CMAKE_CXX_FLAGS_RELEASE'),
                    'warnings_as_errors': cache_value(
                        cache_text, 'SWIFTSHADER_WARNINGS_AS_ERRORS'),
                    'android_build': cache_value(cache_text, 'AAAS_ANDROID_BUILD'),
                    'diagnostics_enabled': cache_value(
                        cache_text, 'AAAS_SWIFTSHADER_DIAGNOSTICS'),
                    'reactor_backend': cache_value(cache_text, 'REACTOR_BACKEND'),
                },
                'ninja_commands_sha256': hashlib.sha256(
                    '\0'.join(commands).encode()).hexdigest(),
                'compiler_version': run(['/usr/bin/c++', '--version'],
                                        capture=True).stdout.splitlines()[0],
                'effective_link_command_sha256': hashlib.sha256(
                    '\0'.join(command).encode()).hexdigest(),
                'objects': [{'path': str(path), 'sha256': sha256(path)}
                            for path in objects],
                'static_archives': [{'path': str(path), 'sha256': sha256(path),
                                     'size_bytes': path.stat().st_size}
                                    for path in archives],
                'flags': flags,
            },
            'headers': headers,
            'output': {
                'path': str(output), 'sha256': sha256(output),
                'build_id': build_id, 'size_bytes': output.stat().st_size,
                'architecture': run(['file', '-b', str(output)],
                                    capture=True).stdout.strip(),
                'needed': needed,
            },
            'production_overlay': {
                'path': str(production), 'sha256': production_hash,
                'build_id': PRODUCTION_BUILD_ID,
            },
        }
        manifest_path = Path(str(output) + '.manifest.json')
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        os.chmod(manifest_path, 0o600)
        print(json.dumps({'output': manifest['output'],
                          'manifest': str(manifest_path),
                          'production_overlay': manifest['production_overlay']},
                         indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'build_swiftshader_diagnostic_overlay: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
