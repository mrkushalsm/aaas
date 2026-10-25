#!/usr/bin/env python3
"""Inspect a pinned repo manifest or validate repo's post-sync revision lock.

No branch revision is silently treated as an immutable commit.
"""
import argparse
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r'^[0-9a-f]{40}$')


def manifest_projects(directory):
    def visit(filename, seen):
        path = directory / filename
        if path in seen:
            raise ValueError(f'include cycle: {filename}')
        tree = ET.parse(path).getroot()
        if tree.tag != 'manifest':
            raise ValueError(f'not a repo manifest: {filename}')
        seen = seen | {path}
        for child in tree:
            if child.tag == 'include':
                yield from visit(child.attrib['name'], seen)
            else:
                yield child

    projects = {}
    default_revision = None
    remotes = {}
    for node in visit('default.xml', set()):
        if node.tag == 'default':
            default_revision = node.get('revision')
        elif node.tag == 'remote':
            remotes[node.get('name')] = node.get('fetch')
        elif node.tag == 'project':
            path = node.get('path', node.attrib['name'])
            if path in projects:
                raise ValueError(f'duplicate project path: {path}')
            projects[path] = dict(name=node.attrib['name'], path=path,
                                  remote=node.get('remote', 'aosp'),
                                  revision=node.get('revision'))
        elif node.tag == 'remove-project':
            path = node.get('path')
            if path not in projects:
                raise ValueError(f'remove-project target absent: {path}')
            del projects[path]
    for project in projects.values():
        project['revision'] = project['revision'] or default_revision
    return projects, remotes


def validate_locked(path, expected_overrides):
    manifest = ET.parse(path).getroot()
    if manifest.tag != 'manifest':
        raise ValueError('not a repo manifest')
    projects = {}
    for node in manifest.iter('project'):
        directory = node.get('path', node.get('name'))
        revision = node.get('revision', '')
        if directory in projects:
            raise ValueError(f'duplicate project path: {directory}')
        if not SHA.fullmatch(revision):
            raise ValueError(f'unpinned project: {directory} {revision}')
        projects[directory] = revision
    if not projects:
        raise ValueError('empty locked manifest')
    for directory, revision in expected_overrides.items():
        if projects.get(directory) != revision:
            raise ValueError(f'override mismatch: {directory}')
    return projects


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['inspect', 'validate', 'generate'])
    parser.add_argument('--manifest-dir', type=Path, default=ROOT / 'sources/digitalis-manifest')
    parser.add_argument('--lock', type=Path, default=ROOT / 'manifests/android16-locked.xml')
    args = parser.parse_args()
    sources = json.loads((ROOT / 'manifests/sources.json').read_text())['sources']
    overrides = {s['path']: s['revision'] for s in sources if s.get('kind') == 'repo-project'}
    if args.action == 'inspect':
        projects, remotes = manifest_projects(args.manifest_dir)
        print(json.dumps(dict(project_count=len(projects), remote_count=len(remotes),
                              unresolved_paths=[p for p, v in projects.items() if not SHA.fullmatch(v['revision'])],
                              override_paths=sorted(overrides)), indent=2))
    elif args.action == 'generate':
        # Run only inside a completed repo sync. repo itself emits the resolved SHA graph.
        subprocess.run(['repo', 'manifest', '-r', '-o', str(args.lock)], check=True)
        projects = validate_locked(args.lock, overrides)
        print(f'locked {len(projects)} project revisions')
    else:
        projects = validate_locked(args.lock, overrides)
        print(f'validated {len(projects)} immutable project revisions')


if __name__ == '__main__':
    main()
