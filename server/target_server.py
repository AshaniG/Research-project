#!/usr/bin/env python3
"""
target_server.py - A minimal HTTP "victim" server for the DDoS-detection lab.

This is the legitimate service that sits behind the XDP/eBPF detector. Point
the attack simulator at this host so you can watch benign requests keep
working (or degrade) while the detector filters flood traffic.

Run:
    python3 server/target_server.py            # listens on 0.0.0.0:8080
    python3 server/target_server.py 0.0.0.0 80 # custom host/port

Then, from a client:
    curl http://<server-ip>:8080/
"""
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

START = time.time()
HITS = 0


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API name)
        global HITS
        HITS += 1
        body = (
            f"OK - target server alive\n"
            f"uptime: {time.time() - START:.0f}s\n"
            f"requests served: {HITS}\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Keep the console quiet under load; comment out to see every hit.
        pass


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"Target server listening on http://{host}:{port}/  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print(f"\nServed {HITS} requests. Bye.")


if __name__ == "__main__":
    main()
