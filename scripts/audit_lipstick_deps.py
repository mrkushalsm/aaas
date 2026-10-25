#!/usr/bin/env python3
"""Inspect immediate Lipstick spec dependencies; no inferred transitive clearance."""
import argparse
import json
import re
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
spec = (args.source / 'rpm/lipstick-qt5.spec').read_text()
entries = []
for line in spec.splitlines():
    match = re.match(r'^(BuildRequires|Requires(?:\(post(?:un)?\))?):\s+(.+)$', line)
    if not match:
        continue
    category, requirement = match.groups()
    package = requirement.split()[0]
    if package.startswith('pkgconfig(') and package.endswith(')'):
        module = package[10:-1]
        result = subprocess.run(['pkg-config', '--modversion', module], capture_output=True, text=True)
        state = 'environment-pkgconfig-present' if result.returncode == 0 else 'environment-pkgconfig-missing'
        version = result.stdout.strip() or None
    else:
        state, version = 'not-checked-by-pkgconfig', None
    entries.append(dict(category=category, requirement=requirement, module=package,
                        state=state, detected_version=version))
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(dict(source_spec='rpm/lipstick-qt5.spec',
                                       immediate_requirements=entries,
                                       transitive_closure='unresolved'), indent=2) + '\n')
print(f'{len(entries)} immediate spec requirements; {sum(e["state"] == "environment-pkgconfig-missing" for e in entries)} missing pkg-config modules')
