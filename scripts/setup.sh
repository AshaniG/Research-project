#!/usr/bin/env bash
#
# setup.sh - Install everything needed to build and run the XDP/eBPF DDoS
# detector on a fresh Debian/Ubuntu server. Run once, as root.
#
#   sudo ./scripts/setup.sh
#
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
	echo "Please run as root:  sudo $0" >&2
	exit 1
fi

echo "[*] Updating package lists..."
apt-get update -y

echo "[*] Installing build toolchain and eBPF/XDP libraries..."
apt-get install -y \
	clang \
	llvm \
	libbpf-dev \
	libelf-dev \
	zlib1g-dev \
	gcc \
	make \
	linux-headers-"$(uname -r)" \
	bpftool \
	iproute2

echo "[*] Installing attack-simulation + load tools (lab testing only)..."
# hping3: crafts SYN/UDP/ICMP floods.  iperf3: bandwidth load.
apt-get install -y hping3 iperf3 python3 || \
	echo "[!] Optional tools failed to install; core detector is unaffected."

echo
echo "[+] Setup complete."
echo "    Build with:   make"
echo "    Run with:     sudo ./build/xdp_ddos_loader -i <iface>"
