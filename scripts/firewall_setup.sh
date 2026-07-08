#!/usr/bin/env bash
#
# firewall_setup.sh - Baseline firewall for the TARGET (victim) Ubuntu server
# in the DDoS-detection lab. Run once, as root, ON THE SERVER YOU PROTECT.
#
#   sudo ./scripts/firewall_setup.sh
#
# This configures ufw (Uncomplicated Firewall) with a sane default-deny policy
# that still lets the lab work: SSH in, the exam portal reachable, and ICMP/traffic
# from the private lab network allowed so the attacker VM can actually reach you.
#
# IMPORTANT — how this relates to XDP:
#   XDP runs in the NIC driver, BEFORE netfilter/iptables/ufw in the ingress path.
#   So your XDP/eBPF detector drops flood packets *earlier* than ufw ever sees them.
#   ufw here is the ordinary host firewall (baseline hardening + access control);
#   the XDP detector is the line-rate DDoS mitigation layer in front of it. They
#   are complementary, not a substitute for each other.
#
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
	echo "Please run as root:  sudo $0" >&2
	exit 1
fi

# --- Tunables (override via environment) ---------------------------------
PORTAL_PORT="${PORTAL_PORT:-8080}"     # port the exam portal listens on
SSH_PORT="${SSH_PORT:-22}"             # keep this open or you lock yourself out
LAB_SUBNET="${LAB_SUBNET:-192.168.56.0/24}"  # private lab network (attacker lives here)

if ! command -v ufw >/dev/null; then
	echo "[*] ufw not found; installing..."
	apt-get update -y
	apt-get install -y ufw
fi

echo "[*] Setting default policy: deny incoming, allow outgoing..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing

echo "[*] Allowing SSH on port ${SSH_PORT} (so you keep access)..."
ufw allow "${SSH_PORT}/tcp" comment "SSH admin"

echo "[*] Allowing the exam portal on port ${PORTAL_PORT}/tcp..."
ufw allow "${PORTAL_PORT}/tcp" comment "Exam results portal"

echo "[*] Allowing all traffic from the private lab network ${LAB_SUBNET}..."
# The attacker VM must be able to reach us to run the experiment. Restricting
# this to the private lab subnet keeps the box closed to everything else.
ufw allow from "${LAB_SUBNET}" comment "Private lab network (attacker)"

echo "[*] Enabling firewall..."
ufw --force enable

echo
echo "[+] Firewall configured. Current rules:"
ufw status verbose

cat <<EOF

Next steps on this (target) server:
  1. Start the victim service:   python3 server/exam_portal.py 0.0.0.0 ${PORTAL_PORT}
  2. Attach the XDP detector:    sudo ./build/xdp_ddos_loader -i <iface>
Then flood it from the attacker machine and watch the detector drop the attack.

Note: ufw counts/blocks are separate from the XDP detector's counters. XDP acts
first (in the driver), so during a flood the detector's "Dropped (attack)" is
where you'll see mitigation happening, not ufw.
EOF
