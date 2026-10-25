#!/usr/bin/env python3
"""Record honest baseline availability; never treat a missing runtime as a benchmark."""
import json
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / 'results/m0/baselines.jsonl'
revision = {s['name']: s['revision'] for s in json.loads((root / 'manifests/sources.json').read_text())['sources']}
with out.open('w') as handle:
    for name in ('droidloom', 'waydroid'):
        executable = shutil.which(name)
        row = dict(schema_version=1, runtime=name, revision=revision[name], host_id='local-m0', workload='availability', state='cold', sample_count=0)
        if executable is None:
            row.update(status='unavailable', reason=f'{name} executable is not installed; no Android image or runtime was started')
        else:
            p = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=10)
            row.update(status='unsupported', reason=f'executable found at {executable}; version probe exit={p.returncode}; launch benchmark requires a controlled Android image')
        handle.write(json.dumps(row) + '\n')
        print(name, row['status'])
