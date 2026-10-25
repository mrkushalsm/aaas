#!/usr/bin/env python3
"""Report staged APEX files separately from actual apexd activation."""

import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


LOOP_FAILURE = re.compile(r'Failed to activate .*Failed to open loop-control')


def audit(rootfs, apex_log):
    apex = Path(rootfs) / 'apex'
    info = apex / 'apex-info-list.xml'
    entries = ET.parse(info).getroot().findall('apex-info')
    active = sorted(item.get('moduleName') for item in entries
                    if item.get('isActive') == 'true')
    inactive = sorted(item.get('moduleName') for item in entries
                      if item.get('isActive') != 'true')
    staged = sorted(path.name for path in apex.iterdir()
                    if path.is_dir() and (path / 'apex_manifest.pb').is_file())
    failures = sum(bool(LOOP_FAILURE.search(line))
                   for line in Path(apex_log).read_text(errors='replace').splitlines())
    required = ('com.android.runtime', 'com.android.art')
    return {
        'staged_manifest_count': len(staged),
        'declared_module_count': len(entries),
        'active_modules': active,
        'inactive_module_count': len(inactive),
        'required_runtime_staged': all(name in staged for name in required),
        'required_runtime_active': all(name in active for name in required),
        'loop_control_activation_failures': failures,
        'activation_verified': bool(active) and failures == 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--apex-log', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.rootfs, args.apex_log), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
