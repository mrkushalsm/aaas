"""Tests for the M1B.8.6 delegated cgroup v2 memory policy."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


POLICY = load_script('aaas_cgroup')


def delegated_root():
    try:
        return POLICY.discover_delegated_root()
    except (POLICY.CgroupError, OSError):
        return None


DELEGATED = delegated_root() is not None


def unique(name):
    return f'{name}-{os.getpid()}-{time.monotonic_ns()}'


class DiscoveryTests(unittest.TestCase):
    def test_discovers_user_service_sibling(self):
        text = ('0::/user.slice/user-1000.slice/user@1000.service/'
                'app.slice/app-konsole.scope/tab.scope\n')
        root = POLICY.discover_delegated_root(cgroup_text=text)
        self.assertEqual(
            root,
            POLICY.CGROUP_MOUNT / 'user.slice/user-1000.slice/'
            'user@1000.service/aaas')

    def test_rejects_non_user_service_scope(self):
        with self.assertRaisesRegex(POLICY.DelegationError, 'user@'):
            POLICY.discover_delegated_root(cgroup_text='0::/system.slice/foo.service\n')

    def test_rejects_missing_v2_entry(self):
        with self.assertRaisesRegex(POLICY.DelegationError, 'exactly one'):
            POLICY.discover_delegated_root(cgroup_text='1::/legacy\n')

    def test_rejects_relative_override(self):
        with self.assertRaisesRegex(POLICY.DelegationError, 'absolute'):
            POLICY.discover_delegated_root(environ={'AAAS_CGROUP_ROOT': 'relative'})

    def test_rejects_escaping_cgroup_path(self):
        with self.assertRaisesRegex(POLICY.CgroupError, r'\.\.'):
            POLICY.cgroup_dir('/a/../b')


class ActivityManagerParserTests(unittest.TestCase):
    TEXT = """\
ACTIVITY MANAGER RUNNING PROCESSES
  *PERS* UID 1000 ProcessRecord{4833291 283:system/1000}
    oom adj: max=-900 curRaw=-900 setRaw=-900 cur=-900 set=-900
    curProcState=0 mRepProcState=0 setProcState=0
    cached=false empty=false
  *APP* UID 1000 ProcessRecord{1a87cd 666:com.android.settings/1000}
    oom adj: max=1001 curRaw=0 setRaw=0 cur=0 set=0
    curProcState=2 mRepProcState=2 setProcState=2
    cached=false empty=false
  *APP* UID 10124 ProcessRecord{ed1095e 739:com.android.launcher3/u0a124}
    oom adj: max=1001 curRaw=100 setRaw=100 cur=100 set=100
    curProcState=5 mRepProcState=5 setProcState=5
    cached=false empty=false
  *APP* UID 10074 ProcessRecord{b0ea006 826:com.android.cellbroadcastreceiver/u0a74}
    oom adj: max=1001 curRaw=915 setRaw=915 cur=915 set=915
    curProcState=19 mRepProcState=19 setProcState=19
    cached=true empty=true
  *APP* UID 10106 ProcessRecord{69f223c 932:com.android.inputmethod.latin/u0a106}
    oom adj: max=1001 curRaw=500 setRaw=500 cur=500 set=500
    curProcState=10 mRepProcState=10 setProcState=10
    cached=false empty=false
"""

    def test_parses_stable_fields(self):
        records = POLICY.parse_activity_processes(self.TEXT)
        self.assertEqual(set(records), {283, 666, 739, 826, 932})
        self.assertEqual((records[283].adj, records[283].proc_state), (-900, 0))
        self.assertEqual(records[666].name, 'com.android.settings')
        self.assertTrue(records[826].cached)
        self.assertEqual(records[932].uid, 'u0a106')

    def test_classifies_activity_manager_states(self):
        records = POLICY.parse_activity_processes(self.TEXT)
        self.assertEqual(POLICY.classify_priority(records[283]), 'critical')
        self.assertEqual(POLICY.classify_priority(records[666]), 'foreground')
        self.assertEqual(POLICY.classify_priority(records[739]), 'foreground')
        self.assertEqual(POLICY.classify_priority(records[826]), 'cached')
        self.assertEqual(POLICY.classify_priority(records[932]), 'background')

    def test_native_fallback_uses_processgroup_branch(self):
        self.assertEqual(
            POLICY.classify_cgroup_fallback('/user.slice/u/user@1000.service/'
                                            'aaas/system/uid_1069/pid_18'),
            'critical')
        self.assertEqual(
            POLICY.classify_cgroup_fallback('/user.slice/u/user@1000.service/'
                                            'aaas/apps/uid_10124/pid_739'),
            'background')
        self.assertIsNone(POLICY.classify_cgroup_fallback('/user.slice/other'))

    def test_anchor_detection(self):
        self.assertTrue(POLICY.is_anchor_name('system'))
        self.assertTrue(POLICY.is_anchor_name('init'))
        self.assertTrue(POLICY.is_anchor_name('whatever', '/system/bin/lmkd'))
        self.assertFalse(POLICY.is_anchor_name('com.android.settings'))

    def test_default_policy_has_no_android_hard_limit(self):
        for name in POLICY.CLASS_NAMES:
            policy = POLICY.DEFAULT_POLICIES[name]
            self.assertIsNone(policy.max, name)
            self.assertEqual(policy.oom_group, 0, name)
        self.assertGreater(POLICY.DEFAULT_POLICIES['critical'].low,
                           POLICY.DEFAULT_POLICIES['foreground'].low)
        self.assertEqual(POLICY.DEFAULT_POLICIES['background'].low, 0)
        self.assertEqual(POLICY.DEFAULT_POLICIES['cached'].low, 0)


@unittest.skipUnless(DELEGATED, 'delegated user cgroup v2 scope unavailable')
class RealHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.session = None
        self.probes = []
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        if self.session is not None:
            try:
                self.session.shutdown()
            except Exception:
                pass
        for probe in self.probes:
            try:
                probe.rmdir()
            except OSError:
                pass

    def make_session(self):
        self.session = POLICY.CgroupSession.create(unique('test'))
        return self.session

    def make_probe(self):
        probe = self.session.root / unique('probe')
        probe.mkdir(mode=0o755)
        self.probes.append(probe)
        return probe

    def test_creates_hierarchy_with_policy_files(self):
        session = self.make_session()
        for klass in POLICY.CLASS_NAMES:
            directory = session.class_dir(klass)
            self.assertTrue(directory.is_dir())
            self.assertEqual((directory / 'memory.low').read_text().strip(),
                             str(POLICY.DEFAULT_POLICIES[klass].low))
            self.assertEqual((directory / 'memory.max').read_text().strip(), 'max')
            self.assertEqual((directory / 'memory.oom.group').read_text().strip(), '0')
        state = session.state()
        self.assertEqual(state['session'], str(session.session_dir))
        self.assertEqual(set(state['classes']), set(POLICY.CLASS_NAMES))

    def test_moves_and_reclassifies_a_verified_process(self):
        session = self.make_session()
        probe = self.make_probe()
        process = subprocess.Popen(['/usr/bin/sleep', '60'])
        self.processes.append(process)
        probe.joinpath('cgroup.procs').write_text(f'{process.pid}\n')
        identity = POLICY.read_process_identity(process.pid)
        first = session.apply_class(identity, 'foreground')
        self.assertTrue(first.changed)
        self.assertIn('/foreground', POLICY.read_process_identity(process.pid).cgroup)
        # Existing charges stay in the original leaf; it must receive the
        # same class protection in place.
        foreground_low = int((probe / 'memory.low').read_text().strip())
        self.assertGreaterEqual(foreground_low, POLICY.IN_PLACE_LOW_FLOOR)
        self.assertLessEqual(
            foreground_low, POLICY.IN_PLACE_POLICIES['foreground'].low)
        second = session.apply_class(
            POLICY.read_process_identity(process.pid), 'cached')
        self.assertEqual(second.previous, 'foreground')
        self.assertIn('/cached', POLICY.read_process_identity(process.pid).cgroup)
        self.assertEqual((probe / 'memory.low').read_text().strip(), '0')
        self.assertEqual(
            int((probe / 'memory.high').read_text().strip()),
            POLICY.IN_PLACE_POLICIES['cached'].high)
        third = session.apply_class(
            POLICY.read_process_identity(process.pid), 'background')
        self.assertIn('/background', POLICY.read_process_identity(process.pid).cgroup)
        self.assertEqual(
            int((probe / 'memory.high').read_text().strip()),
            POLICY.IN_PLACE_POLICIES['background'].high)

    def test_shutdown_restores_live_process_and_removes_hierarchy(self):
        session = self.make_session()
        probe = self.make_probe()
        process = subprocess.Popen(['/usr/bin/sleep', '60'])
        self.processes.append(process)
        probe.joinpath('cgroup.procs').write_text(f'{process.pid}\n')
        session.apply_class(POLICY.read_process_identity(process.pid), 'foreground')
        result = session.shutdown()
        self.assertTrue(result['removed'], result)
        self.assertEqual(result['failures'], {})
        self.assertFalse(session.session_dir.exists())
        self.assertIn('/' + str(probe.relative_to(POLICY.CGROUP_MOUNT)), POLICY.read_process_identity(process.pid).cgroup)

    def test_shutdown_retries_transient_restore_readback_mismatch(self):
        from unittest.mock import patch

        session = self.make_session()
        mismatch = {123: 'restore failed: /session/cached != /original/pid_123'}
        with patch.object(session, 'restore_all',
                          side_effect=[mismatch, mismatch, {}]) as restore:
            result = session.shutdown()
        self.assertEqual(restore.call_count, 3)
        self.assertTrue(result['removed'], result)
        self.assertEqual(result['failures'], {})

    def test_anchor_is_protected_in_place(self):
        session = self.make_session()
        probe = self.make_probe()
        process = subprocess.Popen(['/usr/bin/sleep', '60'])
        self.processes.append(process)
        probe.joinpath('cgroup.procs').write_text(f'{process.pid}\n')
        session.apply_class(
            POLICY.read_process_identity(process.pid), 'critical', anchor=True)
        self.assertIn('/' + str(probe.relative_to(POLICY.CGROUP_MOUNT)), POLICY.read_process_identity(process.pid).cgroup)
        self.assertEqual(
            int((probe / 'memory.low').read_text().strip()),
            POLICY.ANCHOR_POLICY.low)
        session.shutdown()
        self.assertEqual((probe / 'memory.low').read_text().strip(), '0')

    def test_identity_rejects_unrelated_process(self):
        session = self.make_session()
        process = subprocess.Popen(['/usr/bin/sleep', '60'])
        self.processes.append(process)
        with self.assertRaisesRegex(POLICY.IdentityError, 'outside'):
            session.apply_class(POLICY.read_process_identity(process.pid), 'foreground')

    def test_identity_rejects_pid_reuse(self):
        session = self.make_session()
        probe = self.make_probe()
        process = subprocess.Popen(['/usr/bin/sleep', '60'])
        self.processes.append(process)
        probe.joinpath('cgroup.procs').write_text(f'{process.pid}\n')
        old = POLICY.read_process_identity(process.pid)
        process.terminate()
        process.wait(timeout=5)
        replacement = subprocess.Popen(['/usr/bin/sleep', '60'])
        self.processes.append(replacement)
        probe.joinpath('cgroup.procs').write_text(f'{replacement.pid}\n')
        with self.assertRaisesRegex(POLICY.IdentityError, 'reuse|starttime|exited'):
            session.apply_class(old, 'foreground')

    def test_no_internal_process_guard(self):
        session = self.make_session()
        probe = self.make_probe()
        process = subprocess.Popen(['/usr/bin/sleep', '60'])
        self.processes.append(process)
        probe.joinpath('cgroup.procs').write_text(f'{process.pid}\n')
        with self.assertRaisesRegex(POLICY.DelegationError, 'no-internal-process'):
            POLICY.ensure_memory_controller(probe)

    def test_shutdown_after_process_exit_removes_hierarchy(self):
        session = self.make_session()
        probe = self.make_probe()
        process = subprocess.Popen(['/usr/bin/sleep', '60'])
        probe.joinpath('cgroup.procs').write_text(f'{process.pid}\n')
        session.apply_class(POLICY.read_process_identity(process.pid), 'cached')
        process.terminate()
        process.wait(timeout=5)
        session.prune()
        self.assertEqual((probe / 'memory.low').read_text().strip(), '0')
        self.assertEqual((probe / 'memory.high').read_text().strip(), 'max')
        result = session.shutdown()
        self.assertTrue(result['removed'], result)
        self.assertEqual(result['failures'], {})
        self.assertFalse(session.session_dir.exists())

    def test_shutdown_tolerates_exit_race(self):
        session = self.make_session()
        probe = self.make_probe()
        process = subprocess.Popen(['/usr/bin/sleep', '60'])
        probe.joinpath('cgroup.procs').write_text(f'{process.pid}\n')
        session.apply_class(POLICY.read_process_identity(process.pid), 'foreground')
        process.terminate()
        process.wait(timeout=5)
        # Deliberately do not prune: cleanup must treat the vanished process as
        # an expected shutdown race rather than a policy failure.
        result = session.shutdown()
        self.assertTrue(result['removed'], result)
        self.assertEqual(result['failures'], {})
        # The empty pid leaf may still own charges, so its class policy must be
        # reset even though the process exited first.
        self.assertEqual((probe / 'memory.low').read_text().strip(), '0')
        self.assertEqual((probe / 'memory.high').read_text().strip(), 'max')

    def test_cleanup_stale_in_place_skips_live_leaves(self):
        session = self.make_session()
        stale = self.make_probe()
        live = self.session.root / unique('live')
        live.mkdir(mode=0o755)
        self.probes.append(live)
        stale.joinpath('memory.low').write_text(f'{16 * 1024 * 1024}\n')
        stale.joinpath('memory.high').write_text(f'{64 * 1024 * 1024}\n')
        process = subprocess.Popen(['/usr/bin/sleep', '60'])
        self.processes.append(process)
        live.joinpath('cgroup.procs').write_text(f'{process.pid}\n')
        live.joinpath('memory.low').write_text(f'{16 * 1024 * 1024}\n')
        cleaned = POLICY.cleanup_stale_in_place(self.session.root)
        self.assertIn(str(stale), cleaned)
        self.assertNotIn(str(live), cleaned)
        self.assertEqual((stale / 'memory.low').read_text().strip(), '0')
        self.assertEqual((stale / 'memory.high').read_text().strip(), 'max')
        self.assertEqual((live / 'memory.low').read_text().strip(),
                         str(16 * 1024 * 1024))


class RunAaasInterfaceTests(unittest.TestCase):
    def test_default_memory_policy_is_none(self):
        source = (ROOT / 'scripts/run_aaas.py').read_text()
        self.assertIn("--memory-policy", source)
        self.assertIn("default='none'", source)
        self.assertIn("choices=('none', 'cgroup')", source)

    def test_launcher_cleans_policy_in_finally(self):
        source = (ROOT / 'scripts/run_aaas.py').read_text()
        self.assertIn('policy.shutdown()', source)
        self.assertIn("session / 'policy-summary.json'", source)
        self.assertIn('policy_monitor.stop(', source)


if __name__ == '__main__':
    unittest.main()
