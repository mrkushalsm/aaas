#!/usr/bin/env python3
"""Build pinned slirp4netns for the isolated Android network namespace."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

UPSTREAM = 'https://github.com/rootless-containers/slirp4netns.git'
COMMIT = '944fa94090e1fd1312232cbc0e6b43585553d824'


def run(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'command failed ({result.returncode}): {command!r}\n'
                           + result.stdout[-1600:])
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve()
    source = workspace / 'tmp/slirp4netns-src'
    build = workspace / 'tmp/slirp4netns-build'
    staging = workspace / 'tmp/slirp4netns-stage'
    output = workspace / 'tmp/slirp4netns'
    manifest = workspace / 'tmp/slirp4netns.build.json'
    workspace.joinpath('tmp').mkdir(parents=True, exist_ok=True)
    for tool in ('git', 'autoconf', 'automake', 'make', 'gcc', 'pkg-config'):
        if not shutil.which(tool):
            raise SystemExit(f'missing host build tool: {tool}')
    for package in ('slirp', 'glib-2.0', 'libseccomp'):
        if subprocess.run(['pkg-config', '--exists', package]).returncode:
            raise SystemExit(f'missing host development library: {package}')
    if not source.is_dir():
        run(['git', 'clone', '--no-checkout', UPSTREAM, str(source)])
    run(['git', 'fetch', '--depth', '1', 'origin', COMMIT], cwd=source)
    run(['git', 'checkout', '--detach', COMMIT], cwd=source)
    actual = run(['git', 'rev-parse', 'HEAD'], cwd=source)
    if actual != COMMIT:
        raise SystemExit(f'upstream source mismatch: expected {COMMIT}, got {actual}')
    run(['./autogen.sh'], cwd=source)
    if build.exists():
        shutil.rmtree(build)
    if staging.exists():
        shutil.rmtree(staging)
    if (source / 'Makefile').is_file():
        run(['make', 'distclean'], cwd=source)
    build.mkdir(parents=True)
    run([str(source / 'configure'), f'--prefix={staging}'], cwd=build)
    run(['make', '-j2'], cwd=build)
    run(['make', 'install'], cwd=build)
    binary = staging / 'bin/slirp4netns'
    shutil.copy2(binary, output)
    output.chmod(0o755)
    report = {
        'source': UPSTREAM,
        'commit': COMMIT,
        'binary_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'libslirp_version': run(['pkg-config', '--modversion', 'slirp']),
        'glib_version': run(['pkg-config', '--modversion', 'glib-2.0']),
        'libseccomp_version': run(['pkg-config', '--modversion', 'libseccomp']),
        'build_command': 'autogen.sh; configure; make -j2; make install',
        'build_host_architecture': os.uname().machine,
    }
    manifest.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
