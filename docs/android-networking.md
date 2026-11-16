# Android application networking

AaaS presents an isolated virtual Ethernet device to Android and forwards packets
through the user's host network with rootless `slirp4netns`. Android owns DHCP
configuration for `eth0`; the current slirp endpoint assigns `10.0.2.15/24`,
with gateway `10.0.2.2` and DNS `10.0.2.3`. The host Wi-Fi/Ethernet device stays
under the host network manager. AaaS does not expose the host interface or grant
the Android runtime host network-administration privileges.

The runtime builds `slirp4netns` from pinned upstream commit
`944fa94090e1fd1312232cbc0e6b43585553d824`, checks its recorded binary hash,
starts it against the Android user namespace, waits for its ready-fd handshake,
and terminates it with the Android namespace. The runtime closure includes the
binary and build receipt. `scripts/run_aaas.py` prepares a session-local Android
Ethernet capability overlay and compatible NetworkStack artifacts from the
installed image inputs; it binds these read-only for that session and leaves the
system image and userdata unchanged.

Android's `EthernetTracker` registers `eth0` with ConnectivityService. The
NetworkStack performs DNS, HTTP, and HTTPS validation, after which Android marks
network 100 as the default, `INTERNET`, and `VALIDATED`. This is a truthful
Ethernet transport. AaaS does not provide a physical or virtual Wi-Fi HAL, does
not fabricate SSIDs, and does not advertise `wlan0`; Android Wi-Fi settings and
Wi-Fi-only APIs are not supported. Apps using Android's default network, DNS,
Java networking, or native sockets can use the host's uplink.

## Rootless compatibility limits

The Android image's NetworkStats BPF interface map is unavailable in this
rootless namespace. A narrowly hash- and instruction-checked session overlay
makes `bpfRegisterIface` a no-op so registration cannot abort system_server.
Android's `TcpSocketTracker` also queries a missing UID firewall BPF map while
validating a network. The session-local NetworkStack patch skips that optional
socket-filter query; it does not change firewall rules or packet forwarding.
The namespace remains the network isolation boundary. Android per-UID BPF
firewall/statistics behavior is not equivalent to a BPF-capable Android kernel
and is a known limitation.

## Reproduction and evidence

Start and inspect the installed service with `systemctl --user start aaas-runtime.service`
and `aaas-portable runtime status`. `scripts/build_ethernet_connectivity_overlay.py`
builds the Android compatibility overlay; its JSON receipt records input and
output hashes. Focused regression checks are `python -m unittest
 tests.test_ethernet_network_stack_overlay tests.test_run_aaas`.

The live installed-runtime results, session path, app-level HTTPS probe, Android
network-validation evidence, host-network check, interruption/recovery check,
and overlay hashes are recorded in
**`results/networking/2026-11-10.json`** (maintainer archive only).
