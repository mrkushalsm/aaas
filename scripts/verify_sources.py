#!/usr/bin/env python3
"""Read-only remote revision check; never substitutes a moving branch."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sources = json.loads((ROOT / 'manifests/sources.json').read_text())['sources']
rows = []
for source in sources:
    rev = source['revision']
    row = {'name': source['name'], 'url': source['url'], 'requested': rev}
    if rev is None:
        row['status'] = 'unresolved-no-report-pin'
    elif len(rev) == 40 and all(c in '0123456789abcdef' for c in rev):
        # GitHub and Gitiles both expose commit objects over HTTPS without cloning.
        url = source['url'].removesuffix('.git')
        if 'github.com/' in url:
            url = url.replace('github.com/', 'api.github.com/repos/') + '/commits/' + rev
        else:
            url += '/+/' + rev + '?format=JSON'
        p = subprocess.run(['curl', '-L', '-sS', '-o', '/dev/null', '-w', '%{http_code}', '--max-time', '20', url], capture_output=True, text=True)
        row['status'] = 'verified-commit-object' if p.returncode == 0 and p.stdout == '200' else 'unverified'
        row['http_status'] = p.stdout
        row['error'] = p.stderr.strip()
    else:
        p = subprocess.run(['git', 'ls-remote', '--heads', source['url'], rev], capture_output=True, text=True, timeout=30)
        row['status'] = 'verified-moving-ref' if p.returncode == 0 and p.stdout.strip() else 'unverified'
        row['resolved'] = p.stdout.split()[0] if p.stdout.strip() else None
        row['error'] = p.stderr.strip()
    rows.append(row)
out = ROOT / 'results/m0/source-verification.json'
out.write_text(json.dumps(rows, indent=2) + '\n')
print(json.dumps({r['name']: r['status'] for r in rows}, indent=2))
sys.exit(0 if all(r['status'].startswith('verified') or r['status'].startswith('unresolved') for r in rows) else 1)
