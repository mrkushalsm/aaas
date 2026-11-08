#!/usr/bin/env python3
"""Read-only first-boot preflight for reconstructed Android candidates.

This command deliberately does not launch Android. A candidate must first have
a validated runtime/security profile; the current reconstructed candidate is
structural-only and must fail closed here.
"""

from __future__ import annotations

import json
from pathlib import Path

import android_workspace
import aaas_profiles


class BootPreflightError(ValueError):
    pass


def _check(name, state, detail, mandatory=True):
    return {'name': name, 'state': state, 'detail': detail,
            'mandatory': mandatory}


def inspect_candidate(candidate, workspace, *, lsm_path=Path('/sys/kernel/security/lsm'),
                      selinux_load=Path('/sys/fs/selinux/load')):
    """Inspect a candidate and host without starting a process or mounting anything."""
    raw_workspace = Path(workspace).expanduser().absolute()
    raw_candidate = Path(candidate).expanduser()
    if not raw_candidate.is_absolute():
        raw_candidate = raw_workspace / raw_candidate
    if raw_candidate.is_symlink():
        raise BootPreflightError('candidate path must not be a symlink')
    try:
        workspace_real = raw_workspace.resolve(strict=True)
        candidate_real = raw_candidate.resolve(strict=True)
    except OSError as error:
        raise BootPreflightError(f'workspace or candidate does not exist: {error}') from error
    if not candidate_real.is_relative_to(workspace_real):
        raise BootPreflightError('candidate must be located inside the configured workspace')
    if not candidate_real.is_dir():
        raise BootPreflightError('candidate must be a directory')
    manifest_path = candidate_real / 'manifest.json'
    rootfs = candidate_real / 'rootfs'
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise BootPreflightError('candidate has no regular manifest.json')
    if not rootfs.is_dir() or rootfs.is_symlink():
        raise BootPreflightError('candidate has no real rootfs directory')

    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if (manifest.get('status') != 'ASSEMBLED_INCOMPLETE'
                or manifest.get('candidate_rootfs_relative') != 'rootfs'
                or manifest.get('runtime_ready') is not False
                or manifest.get('trust_classification') != 'RECONSTRUCTED_EXPERIMENTAL'):
            raise BootPreflightError(
                'candidate manifest is not an incomplete reconstructed Android image')
        workspace_result = android_workspace.check(workspace_real)
        image = aaas_profiles.inspect_rootfs(rootfs)
    except (OSError, ValueError, json.JSONDecodeError,
            android_workspace.WorkspaceError, aaas_profiles.ProfileError) as error:
        raise BootPreflightError(str(error)) from error

    checks = [
        _check('workspace_health', 'PASS',
               f"{workspace_result['health']['state']}; {workspace_result['mount']['filesystem']} "
               f"UUID {workspace_result['mount']['uuid']}"),
        _check('candidate_identity', 'PASS',
               f"{manifest.get('profile')} / {manifest.get('build_id')}; "
               f"{manifest.get('status')}"),
        _check('assembly_record', 'PASS' if image['assembly_record_validation'] == 'PASS'
               else 'FAIL', image['assembly_record_validation']),
        _check('rootfs_compatibility', 'PASS' if image['compatibility'] == 'MATCH'
               else 'FAIL', image['compatibility']),
    ]

    try:
        lsms = lsm_path.read_text(encoding='ascii').strip().split(',')
    except OSError:
        lsms = []
    selinux_available = 'selinux' in lsms and selinux_load.exists()
    checks.append(_check(
        'android_selinux_kernel_interface', 'SUPPORTED' if selinux_available else 'BLOCKED',
        ('SELinux LSM and policy-load interface detected' if selinux_available else
         f"host LSMs={','.join(lsms) or 'unavailable'}; "
         f"policy-load interface={'present' if selinux_load.exists() else 'absent'}")))
    bypass = image.get('security', {}).get('status') == 'BYPASS_DETECTED'
    checks.append(_check('authorization_bypass_scan', 'FAIL' if bypass else 'PASS',
                         'known authorization bypass detected' if bypass else
                         'no known SELinux success shim or preload found'))

    missing = manifest.get('missing_components', [])
    checks.append(_check('apex_activation', 'UNVERIFIED',
                         'static candidate files do not prove apexd verification or active mounts'))
    checks.append(_check('graphics_stack', 'MISSING' if any('graphics' in item.lower()
                                                            for item in missing) else 'UNVERIFIED',
                         next((item for item in missing if 'graphics' in item.lower()),
                              'no live allocator/mapper/Composer checks performed')))
    checks.append(_check('android_runtime_boot', 'NOT_ATTEMPTED',
                         'preflight is read-only; no Android process or session was launched'))

    security_blocked = not selinux_available or bypass or not image.get('provisionable')
    if security_blocked:
        outcome = 'SECURITY_BLOCKED'
        failure_class = 'SECURITY_GATE'
        first_failure = ('host lacks a verified Android SELinux policy interface; '
                         'the candidate is not a security-validated runtime')
    elif missing:
        outcome = 'BLOCKED'
        failure_class = 'ROOTFS_LAYOUT'
        first_failure = 'candidate manifest lists unresolved runtime components'
    else:
        outcome = 'PREFLIGHT_ONLY'
        failure_class = None
        first_failure = None

    return {
        'schema': 1,
        'kind': 'android16-first-boot-preflight',
        'outcome': outcome,
        'failure_class': failure_class,
        'first_failure': first_failure,
        'candidate': str(candidate_real),
        'rootfs': str(rootfs),
        'trust_classification': manifest.get('trust_classification'),
        'runtime_ready': manifest.get('runtime_ready') is True,
        'launch_permitted': False,
        'session_id': None,
        'checks': checks,
        'unresolved_components': missing,
        'workspace': workspace_result,
        'runtime_inspection': {
            'compatibility': image.get('compatibility'),
            'provenance': image.get('provenance'),
            'assembly_status': image.get('assembly_status'),
            'security': image.get('security'),
            'provisioning_blockers': image.get('provisioning_blockers', []),
        },
        'historical_boot_evidence': {
            'source': 'docs/m1b4-runtime-decision.md',
            'finding': ('the clean stock ServiceManager aborts at selinux_status_open; '
                        'stock init also expects SELinux transitions and labels'),
            'scope': 'historical diagnostic evidence; no candidate runtime was launched',
        },
        'side_effects': [],
    }
