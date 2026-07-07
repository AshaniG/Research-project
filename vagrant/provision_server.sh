#!/usr/bin/env bash
# provision_server.sh - Runs automatically (as root) when `vagrant up` builds
# the ddos-server VM. Installs the eBPF/XDP toolchain and builds the detector.
set -euo pipefail

echo "=== [ddos-server] installing toolchain ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
	clang llvm libbpf-dev libelf-dev zlib1g-dev \
	gcc make linux-headers-"$(uname -r)" bpftool iproute2 \
	python3 hping3 curl

echo "=== [ddos-server] building the detector ==="
cd /vagrant
make clean || true
make

# Detect the private-network interface (the one holding 192.168.56.10).
IFACE="$(ip -o -4 addr show | awk '/192\.168\.56\.10/ {print $2; exit}')"
IFACE="${IFACE:-enp0s8}"

cat > /etc/motd <<EOF

========================================================================
  DDoS-detection LAB  ::  ddos-server (this machine, the victim)
  Private IP : 192.168.56.10        Interface : ${IFACE}
------------------------------------------------------------------------
  1) Start the target website:
       python3 /vagrant/server/target_server.py 0.0.0.0 8080

  2) In another shell (vagrant ssh ddos-server), attach the detector:
       sudo /vagrant/build/xdp_ddos_loader -i ${IFACE}

  3) From the attacker VM, run scripts/attack_sim.sh 192.168.56.10 ...
     and watch the dashboard here.
========================================================================
EOF

echo "=== [ddos-server] ready. Interface = ${IFACE} ==="
