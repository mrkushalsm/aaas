#!/usr/bin/env python3
"""Validate recorded M4 gate evidence and optionally run workspace preflight."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACCEPTANCE = ROOT / 'results/m4/acceptance.json'
REQUIRED_GATES = (
    'workspace_health', 'runtime_lifecycle', 'native_windows', 'native_bridge',
    'persistent_storage', 'launcher_catalog', 'clipboard_android_to_linux',
    'clipboard_linux_to_android', 'notifications_lifecycle', 'media_playback',
    'playback_controls_and_concurrency', 'microphone_permission_cycle',
    'pipewire_capture_outage', 'resource_cleanup', 'automated_regression',
)


def summarize_campaign(document):
    campaign = document.get('final_autonomous_closure_campaign_2026_11_08')
    if not isinstance(campaign, dict):
        return 'PARTIAL/OPEN', ['final campaign record is missing']
    gates = campaign.get('required_gates')
    if not isinstance(gates, dict):
        return 'PARTIAL/OPEN', ['required_gates manifest is missing']
    failures = []
    for gate in REQUIRED_GATES:
        result = gates.get(gate)
        if not isinstance(result, dict):
            failures.append(f'{gate}: missing result')
            continue
        if result.get('status') != 'PASS':
            failures.append(f'{gate}: status is not PASS')
        evidence = result.get('evidence')
        if not isinstance(evidence, list) or not evidence or any(
                not isinstance(item, str) or not item.strip() for item in evidence):
            failures.append(f'{gate}: missing evidence reference')
    return ('PASS/CLOSED' if not failures else 'PARTIAL/OPEN'), failures


def run_workspace_guard(workspace):
    command = [sys.executable, str(ROOT / 'scripts/android_workspace.py'),
               '--workspace', str(workspace), 'health']
    return subprocess.run(command, cwd=ROOT, check=False, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acceptance', type=Path, default=DEFAULT_ACCEPTANCE)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--preflight', action='store_true',
                        help='run the existing workspace health guard first')
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.acceptance.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f'acceptance record unavailable: {exc}', file=sys.stderr)
        return 2
    if args.preflight:
        if args.workspace is None:
            parser.error('--preflight requires --workspace')
        guard = run_workspace_guard(args.workspace)
        print(guard.stdout.rstrip())
        if guard.returncode:
            print('M4 acceptance: BLOCKED by workspace guard')
            return 2
    classification, failures = summarize_campaign(document)
    for failure in failures:
        print(f'INCOMPLETE: {failure}')
    print(f'M4 acceptance: {classification}')
    return 0 if classification == 'PASS/CLOSED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
