#!/usr/bin/env bash
#
# demo.sh - The easiest possible way to SEE the simulator run.
#
# Runs everything on THIS ONE computer, no root, no VMs, no second machine:
#   1) starts the target web server (the "victim") on port 8080
#   2) starts the DDoS simulator's web control panel on port 5000
#
# Then you just open a browser at  http://localhost:5000  and click
# "Launch attack" (use mode = HTTP, target = 127.0.0.1, port = 8080).
#
# This is only to learn how the tools run. The real experiment (with the
# XDP/eBPF kernel detection) still needs the two-machine lab - see README.
#
#   ./demo.sh          # start; press Ctrl-C to stop everything
#
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
	echo "Python 3 is required but not found. Install it:  sudo apt-get install -y python3"
	exit 1
fi

echo "[*] Starting the TARGET server (victim) on http://127.0.0.1:8080 ..."
python3 server/target_server.py 127.0.0.1 8080 &
TARGET_PID=$!

echo "[*] Starting the DDoS simulator CONTROL PANEL on http://127.0.0.1:5000 ..."
python3 ddos-simulator/webui/server.py 127.0.0.1 5000 &
PANEL_PID=$!

# Make sure both children are killed when this script exits (Ctrl-C).
cleanup() {
	echo
	echo "[*] Stopping..."
	kill "$TARGET_PID" "$PANEL_PID" 2>/dev/null || true
	wait 2>/dev/null || true
	echo "[*] Done."
}
trap cleanup INT TERM EXIT

sleep 1
cat <<EOF

============================================================
  Everything is running on THIS computer.

  1. Open your web browser and go to:

         http://localhost:5000

  2. On the page, set:
         Target IP    = 127.0.0.1
         Attack type  = HTTP GET flood
         Target port  = 8080
     then click  "Launch attack".

  3. Watch the live packet count and rate chart climb.

  (HTTP mode needs no root. For SYN/UDP/ICMP against a real
   target, use the full two-machine lab - see the README.)

  Press Ctrl-C here to stop everything.
============================================================
EOF

# Keep running until the user presses Ctrl-C.
wait
