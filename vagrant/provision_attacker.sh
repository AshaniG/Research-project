#!/usr/bin/env bash
# provision_attacker.sh - Runs automatically (as root) when `vagrant up` builds
# the ddos-attacker VM. Installs the flood-generation tools.
set -euo pipefail

echo "=== [ddos-attacker] installing attack/test tools ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y hping3 iperf3 curl iproute2

cat > /etc/motd <<'EOF'

========================================================================
  DDoS-detection LAB  ::  attacker / DDoS server (this machine)
  Private IP : 192.168.56.11    Target (server) : 192.168.56.10
------------------------------------------------------------------------
  Check you can reach the server:
       ping -c3 192.168.56.10
       curl http://192.168.56.10:8080/

  Launch a controlled flood (watch the server's dashboard):
       sudo /vagrant/scripts/attack_sim.sh 192.168.56.10 syn 20
       # modes: syn | udp | icmp | mixed

  ONLY attack this lab server. Flooding other hosts is illegal.
========================================================================
EOF

echo "=== [ddos-attacker] ready ==="
