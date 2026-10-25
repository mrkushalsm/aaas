#!/usr/bin/env python3
"""Validate JSON Lines observations against the versioned benchmark contract."""
import json
import sys
from pathlib import Path
from jsonschema import Draft202012Validator

root = Path(__file__).resolve().parents[1]
schema = json.loads((root / 'benchmarks/record.schema.json').read_text())
validator = Draft202012Validator(schema)
errors = 0
for filename in sys.argv[1:]:
    for number, line in enumerate(Path(filename).read_text().splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f'{filename}:{number}: {exc}', file=sys.stderr)
            errors += 1
            continue
        for error in validator.iter_errors(value):
            print(f'{filename}:{number}: {error.message}', file=sys.stderr)
            errors += 1
if not sys.argv[1:]:
    print('usage: benchmarks/validate.py FILE.jsonl [...]', file=sys.stderr)
    sys.exit(2)
print(f'validated {len(sys.argv)-1} files; errors={errors}')
sys.exit(1 if errors else 0)
