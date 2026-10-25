#!/usr/bin/env python3
"""Run a bounded Soong graphics build probe from pinned partial checkouts.

The source layout is deliberately incomplete. Failure identifies the next
unresolved project; success would still require ABI and runtime validation.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent))
import android_workspace as ws

MANIFEST = Path(__file__).parent.parent / 'manifests/android-graphics-candidates.json'


def verify_sources(workspace, projects):
    sources = Path(workspace) / 'sources'
    for project in projects:
        checkout = sources / project['checkout']
        if not checkout.is_dir():
            raise ws.WorkspaceError(f'missing source checkout: {checkout}')
        result = subprocess.run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'],
                                capture_output=True, text=True, check=True)
        if result.stdout.strip() != project['revision']:
            raise ws.WorkspaceError(f'revision mismatch: {project["path"]}')


def prepare_layout(workspace, projects):
    workspace = Path(workspace)
    root = workspace / 'probes' / 'graphics-qpr2'
    for project in projects:
        src = workspace / 'sources' / project['checkout']
        dest = root / project['path']
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink() and dest.resolve() == src.resolve():
                continue
            if dest.is_dir() and not dest.is_symlink():
                revision = subprocess.run(['git', '-C', str(dest), 'rev-parse', 'HEAD'],
                                          capture_output=True, text=True, check=False)
                if revision.returncode == 0 and revision.stdout.strip() == project['revision']:
                    continue
            raise ws.WorkspaceError(f'conflicting existing probe path: {dest}')
        if project['layout'] == 'copy':
            shutil.copytree(src, dest, symlinks=True)
        elif project['layout'] == 'symlink':
            dest.symlink_to(src, target_is_directory=True)
        else:
            raise ws.WorkspaceError(f'unknown layout: {project["layout"]}')
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--predict-gib', type=float, default=6)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    try:
        ws.check(args.workspace, int(args.predict_gib * ws.GIB))
        snapshot = json.loads(MANIFEST.read_text())['source_snapshot']
        projects = snapshot['projects']
        verify_sources(args.workspace, projects)
        root = prepare_layout(args.workspace, projects)
        if args.prepare_only:
            print(json.dumps({'status': 'prepared', 'root': str(root)}))
            return 0
        output = args.workspace / 'out' / 'graphics-qpr2'
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        log = args.workspace / 'logs' / f'graphics-build-probe-{stamp}.log'
        budget_log = args.workspace / 'logs' / 'graphics-build-budget.jsonl'
        command = [str(root / 'build/soong/soong_ui.bash'), '--make-mode', '-j2',
                   'mapper.minigbm', 'android.hardware.graphics.allocator-service.minigbm']
        shell_command = 'cd ' + shlex.quote(str(root)) + ' && ' + shlex.join(command)
        shell_command += ' > ' + shlex.quote(str(log)) + ' 2>&1'
        env = os.environ.copy()
        env.update(OUT_DIR=str(output), TMPDIR=str(args.workspace / 'tmp'),
                   GOCACHE=str(args.workspace / 'cache/go-build'),
                   GOMODCACHE=str(args.workspace / 'cache/go-mod'))
        # run_guarded uses the current environment; no host paths are written.
        old = os.environ.copy()
        os.environ.update(env)
        try:
            code = ws.run_guarded(args.workspace, int(args.predict_gib * ws.GIB),
                                  2, ['sh', '-c', shell_command], budget_log)
        finally:
            os.environ.clear()
            os.environ.update(old)
        print(json.dumps({'status': 'build_succeeded' if code == 0 else 'build_failed',
                          'exit_code': code, 'log': str(log)}))
        return code
    except (ws.WorkspaceError, OSError, subprocess.CalledProcessError) as exc:
        print(f'graphics build probe: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
