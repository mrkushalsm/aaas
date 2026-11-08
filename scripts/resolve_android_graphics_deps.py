#!/usr/bin/env python3
"""Resolve a bounded Soong source closure from one pinned AOSP superproject."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).parent))
import android_workspace as ws
import probe_android_graphics_build as graphics


ERROR = re.compile(r'Error parsing directory "([^"]+)"')
EXEC_ERROR = re.compile(r'fork/exec (prebuilts/[^ :]+): no such file or directory')
MAKE_ERROR = re.compile(r'error: ([^ :]+): No such file or directory')
MODULE_TYPE_ERROR = re.compile(r'unrecognized module type \"([^\"]+)\"')
MODULE_TYPE_PROJECT = {
    'hidl_interface': 'system/tools/hidl',
    'hidl_package_root': 'system/tools/hidl',
    'prebuilt_hidl_interfaces': 'system/tools/hidl',
    'aidl_interface': 'system/tools/aidl',
    'aidl_interface_defaults': 'system/tools/aidl',
    'xsd_config': 'system/tools/xsdc',
}
BASE = 'https://android.googlesource.com/platform/superproject'


def project_layout(project_path):
    """Copy source projects so Soong discovers their Android.bp files.

    Large prebuilts are executable/data inputs rather than Soong source roots,
    so they remain links to the verified checkout to avoid duplicate gigabyte
    trees.
    """
    return 'symlink' if (project_path.startswith('prebuilts/') or
                         project_path == 'toolchain/pgo-profiles') else 'copy'


def missing_source(log, build_root):
    contents = Path(log).read_text()
    module_type = MODULE_TYPE_ERROR.search(contents)
    if module_type:
        return MODULE_TYPE_PROJECT.get(module_type.group(1))
    match = ERROR.search(contents)
    if not match:
        other = EXEC_ERROR.search(contents) or MAKE_ERROR.search(contents)
        return other.group(1) if other else None
    path = Path(match.group(1))
    try:
        relative = path.relative_to(build_root)
    except ValueError as exc:
        raise ValueError(f'missing path outside build root: {path}') from exc
    if '..' in relative.parts or len(relative.parts) < 2:
        raise ValueError(f'invalid missing source path: {relative}')
    return relative.as_posix()


def superproject_entry(superproject, missing):
    parts = missing.split('/')
    for length in range(len(parts), 1, -1):
        project_path = '/'.join(parts[:length])
        url = f'{BASE}/+/{superproject}/{quote(project_path)}?format=JSON'
        try:
            with urlopen(url, timeout=20) as response:
                entry = json.loads(response.read().decode().removeprefix(")]}'\n"))
        except HTTPError as exc:
            try:
                if exc.code == 404:
                    continue
                raise
            finally:
                exc.close()
        source_url = urlparse(entry.get('url', ''))
        if (entry.get('path') == project_path
                and source_url.scheme == 'https'
                and source_url.netloc == 'android.googlesource.com'
                and source_url.path in (f'/{project_path}', f'/platform/{project_path}')
                and re.fullmatch(r'[0-9a-f]{40}', entry.get('revision', ''))):
            return entry
        raise ValueError(f'unexpected superproject entry for {project_path}: {entry}')
    raise ValueError(f'no pinned superproject entry owns {missing}')


def resolve_once(workspace, log, manifest, missing_override=None):
    root = workspace / 'probes' / 'graphics-qpr2'
    missing = missing_override or missing_source(log, root)
    if missing is None:
        return None
    snapshot = manifest['source_snapshot']
    entry = superproject_entry(snapshot['superproject_revision'], missing)
    project_path = entry['path']
    if any(item['path'] == project_path for item in snapshot['projects']):
        raise ValueError(f'already pinned but missing: {project_path}')
    checkout_name = project_path.replace('/', '-') + '-qpr2'
    checkout = workspace / 'sources' / checkout_name
    if checkout.exists():
        raise ValueError(f'conflicting checkout: {checkout}')
    ws.check(workspace, 2 * ws.GIB)
    code = ws.run_guarded(workspace, 2 * ws.GIB, 2,
                          ['git', 'clone', '--filter=blob:none', '--no-checkout',
                           entry['url'], str(checkout)],
                          workspace / 'logs' / 'graphics-source-fetch-budget.jsonl')
    if code:
        raise ValueError(f'clone failed for {project_path}: exit {code}')
    checkout_code = ws.run_guarded(
        workspace, 2 * ws.GIB, 2,
        ['git', '-C', str(checkout), 'checkout', '--detach', entry['revision']],
        workspace / 'logs' / 'graphics-source-fetch-budget.jsonl')
    if checkout_code:
        raise ValueError(f'checkout failed for {project_path}: exit {checkout_code}')
    actual = subprocess.run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True, check=True).stdout.strip()
    if actual != entry['revision']:
        raise ValueError(f'revision mismatch for {project_path}')
    layout = project_layout(project_path)
    project = {'path': project_path, 'checkout': checkout_name,
               'revision': actual, 'layout': layout}
    snapshot['projects'].append(project)
    graphics.MANIFEST.write_text(json.dumps(manifest, indent=2) + '\n')
    return project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--missing', help='source path inferred from a nonstandard build failure')
    parser.add_argument('--max-projects', type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.max_projects <= 20:
        parser.error('--max-projects must be between 1 and 20')
    workspace = args.workspace.resolve()
    ws.check(workspace, 2 * ws.GIB)
    manifest = json.loads(graphics.MANIFEST.read_text())
    log = args.log
    for index in range(args.max_projects):
        project = resolve_once(workspace, log, manifest,
                               args.missing if index == 0 else None)
        if project is None:
            print(json.dumps({'status': 'non_source_failure', 'log': str(log)}))
            return 1
        print(json.dumps({'resolved': project}), flush=True)
        result = subprocess.run([sys.executable, str(Path(graphics.__file__)),
                                 '--workspace', str(workspace), '--predict-gib', '2'],
                                capture_output=True, text=True)
        print(result.stdout.strip(), flush=True)
        if result.returncode == 0:
            return 0
        try:
            log = Path(json.loads(result.stdout)['log'])
        except (ValueError, KeyError) as exc:
            raise ValueError(f'probe failed without log: {result.stderr}') from exc
    print(json.dumps({'status': 'project_limit', 'log': str(log)}))
    return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError, ws.WorkspaceError) as exc:
        print(f'graphics source resolver: {exc}', file=sys.stderr)
        sys.exit(2)
