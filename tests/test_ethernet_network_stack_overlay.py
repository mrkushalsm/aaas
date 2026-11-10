from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_ethernet_connectivity_overlay import patch_tcp_socket_tracker


class TcpSocketTrackerCompatibilityTest(unittest.TestCase):
    def test_skips_optional_bpf_map_query_for_rootless_validation(self):
        source = '''\
.method private pollSocketsInfo()V
    iget-object v12, v3, Lcom/android/networkstack/netlink/TcpSocketTracker;->mCm:Landroid/net/ConnectivityManager;
    iget v13, v10, Lcom/android/networkstack/netlink/TcpSocketTracker$SocketInfo;->uid:I
    invoke-virtual {v12, v13, v5}, Landroid/net/ConnectivityManager;->isUidNetworkingBlocked(IZ)Z
    move-result v5
    if-eqz v5, :cond_5
.end method
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'TcpSocketTracker.smali'
            path.write_text(source)
            patch_tcp_socket_tracker(path)
            result = path.read_text()
        self.assertIn('    const/4 v5, 0x0\n', result)
        self.assertNotIn('isUidNetworkingBlocked', result)

    def test_rejects_unrecognized_networkstack_bytecode(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'TcpSocketTracker.smali'
            path.write_text('.class public Lcom/android/networkstack/netlink/TcpSocketTracker;\n')
            with self.assertRaisesRegex(RuntimeError, 'expected one TcpSocketTracker BPF query'):
                patch_tcp_socket_tracker(path)


if __name__ == '__main__':
    unittest.main()
