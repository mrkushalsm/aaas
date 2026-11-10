import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aaas_portable_installer


class PortableInstallerCleanupTests(unittest.TestCase):
    def test_uninstall_cleans_subordinate_owned_rootfs_cache(self):
        unshare = shutil.which('unshare')
        if not unshare:
            self.skipTest('unshare is unavailable')
        with tempfile.TemporaryDirectory(prefix='aaas-uninstall-') as temporary:
            root = Path(temporary)
            root.chmod(0o755)
            (root / 'rootfs').mkdir()
            (root / 'rootfs').chmod(0o755)
            parent_fd = os.open(root / 'rootfs', os.O_RDONLY | os.O_DIRECTORY)
            create = (
                'import os; os.mkdir("cache", 0o770); '
                'os.chown("cache", 100999, 102000); '
                'os.mkdir("cache/backup", 0o700); '
                'open("cache/backup/marker", "w").write("cache"); '
                'os.chown("cache/backup", 100999, 102000)')
            maps = ['--map-users=0:' + str(os.getuid()) + ':1',
                    '--map-users=100999:100999:1',
                    '--map-groups=0:' + str(os.getgid()) + ':1',
                    '--map-groups=102000:102000:1']
            try:
                result = subprocess.run(
                    [unshare, '--user', *maps, '--setgroups', 'allow',
                     sys.executable, '-c',
                     'import os; os.fchdir(int(os.environ["FD"])); ' + create],
                    env=dict(os.environ, FD=str(parent_fd)), pass_fds=(parent_fd,),
                    capture_output=True, text=True, timeout=15)
            finally:
                os.close(parent_fd)
            if result.returncode:
                self.skipTest('host does not permit subordinate user namespace test')
            self.assertTrue((root / 'rootfs/cache').exists())
            self.assertTrue(aaas_portable_installer.clear_rootfs_cache_for_uninstall(root))
            self.assertFalse((root / 'rootfs/cache').exists())


if __name__ == '__main__':
    unittest.main()
