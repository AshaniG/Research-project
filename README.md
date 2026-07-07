# Kernel-Level DDoS Detection with XDP and eBPF

A research project that detects and mitigates volumetric DDoS attacks **inside
the Linux kernel** using XDP (eXpress Data Path) and eBPF. The detector runs at
the earliest point in the network receive path — in the NIC driver, before the
kernel builds an `sk_buff` — so attack traffic is counted and dropped at line
rate with very little CPU cost.

This repository contains everything needed to stand up a small lab: the
in-kernel detector, a user-space monitor, a target ("victim") server, and a
controlled attack simulator to validate detection.

> **New to this? Read [`SETUP_GUIDE.md`](SETUP_GUIDE.md)** — a beginner
> step-by-step walkthrough that builds the Ubuntu server, explains why you need
> a second (attacker) machine, and shows exactly how to run the attack and see
> detection working.

### Fastest path — build both servers automatically

If you have **VirtualBox** and **Vagrant** installed, you don't have to create
or configure the VMs by hand. From this folder run:

```bash
vagrant up
```

This creates **two** Ubuntu 24.04 VMs on a private network, installs everything,
and pre-builds the detector:

| VM | IP | Role |
|----|----|------|
| `ddos-server`   | 192.168.56.10 | victim service + XDP detector |
| `ddos-attacker` | 192.168.56.11 | runs the flood |

Then:

```bash
# terminal 1 - on the server
vagrant ssh ddos-server
python3 /vagrant/server/target_server.py 0.0.0.0 8080

# terminal 2 - on the server (attach the detector)
vagrant ssh ddos-server
sudo /vagrant/build/xdp_ddos_loader -i enp0s8

# terminal 3 - on the attacker
vagrant ssh ddos-attacker
sudo /vagrant/scripts/attack_sim.sh 192.168.56.10 syn 20
```

Watch the detector dashboard on the server fill with dropped packets and blocked
IPs. `vagrant destroy -f` removes both VMs when you're done.

---

## How it works

```
                +-------------------------------------------------+
   attack /     |  Linux server (protected)                       |
   normal   →   |                                                 |
   traffic      |   NIC ──► [ XDP hook: xdp_ddos.bpf.o ]           |
                |               │        │                        |
                |          XDP_DROP   XDP_PASS ──► kernel stack ──►│──► target_server.py
                |          (attack)   (allowed)                    |
                |                                                 |
                |   user space:  xdp_ddos_loader  (live monitor)  |
                +-------------------------------------------------+
```

The XDP program (`src/xdp_ddos.bpf.c`) tracks each source IPv4 address in an LRU
hash map and, per sliding time window:

- counts total packets, and TCP **SYN** packets separately (SYN-flood signal);
- if a source exceeds the packet **or** SYN threshold, it is flagged and all of
  its traffic is dropped (`XDP_DROP`) for a cool-down period;
- everything else is passed up the stack untouched (`XDP_PASS`).

Global counters (total / passed / dropped / per-protocol / SYN / block events)
live in a stats map that the user-space monitor reads once per second to render
a live dashboard, including the list of currently blocked source IPs.

Thresholds are runtime-tunable from the loader — no recompile needed.

---

## Repository layout

| Path | Purpose |
|------|---------|
| `src/xdp_ddos.bpf.c`    | Kernel-space XDP/eBPF detector |
| `src/xdp_ddos_loader.c` | User-space loader + live monitor |
| `src/common.h`          | Structs/constants shared by both |
| `server/target_server.py` | Minimal HTTP "victim" service |
| `scripts/setup.sh`      | Installs toolchain + libraries |
| `scripts/attack_sim.sh` | Controlled flood generator (lab only) |
| `Makefile`              | Builds the eBPF object and the monitor |

---

## Requirements

- Linux kernel **5.5+** (XDP + libbpf; developed against 6.x)
- `clang`/`llvm`, `libbpf-dev`, `libelf`, kernel headers
- Root (`CAP_NET_ADMIN` / `CAP_BPF`) to attach XDP

On Debian/Ubuntu, `scripts/setup.sh` installs all of the above.

---

## Quick start

### 1. Set up the server (the machine you want to protect)

```bash
git clone <this-repo> && cd Research-project
sudo ./scripts/setup.sh
make
```

`make` produces `build/xdp_ddos.bpf.o` (the kernel program) and
`build/xdp_ddos_loader` (the monitor).

### 2. Start the target service

```bash
python3 server/target_server.py 0.0.0.0 8080
```

### 3. Attach the detector

Find your interface with `ip link` (e.g. `eth0`), then:

```bash
sudo ./build/xdp_ddos_loader -i eth0
```

You'll see a live dashboard. Useful options:

```
-i, --iface <name>   interface to protect (required)
-p, --pkt <n>        packets/window before an IP is blocked (default 2000)
-s, --syn <n>        SYN packets/window before block (default 200)
-w, --window <ms>    window length in milliseconds (default 1000)
-b, --block <sec>    block duration in seconds (default 30)
-S, --skb            use SKB/generic mode (for veth/VMs without native XDP)
```

> On virtual NICs (`veth`, many cloud VMs) native XDP may be unavailable; the
> loader automatically retries in SKB mode, or pass `-S` explicitly.

### 4. Simulate an attack (from a *separate* client on the lab network)

```bash
# SYN flood for 15s against the server at 10.0.0.5
sudo ./scripts/attack_sim.sh 10.0.0.5 syn 15

# also: udp | icmp | mixed
```

Watch the monitor: `Dropped (attack)` and `IP block events` climb, offending
source IPs appear under **Currently blocked sources**, while normal `curl`
requests to the target keep succeeding.

---

## Tuning for your traffic

Start permissive and tighten. Measure your **legitimate** peak with the monitor
first, then set `-p`/`-s` above that peak but below attack levels. Too low and
you drop real users (false positives); too high and floods leak through. The
window (`-w`) trades detection speed against burst tolerance.

---

## Detection methods included

- **Per-IP rate limiting** — packets/second per source over a sliding window.
- **SYN-flood detection** — separate, lower threshold on half-open SYNs.
- **Automatic block + cool-down** — flagged sources are dropped, then
  re-evaluated after the block expires.
- **LRU source table** — bounded memory; spoofed-source floods can't exhaust it.

Natural extensions for further research: per-protocol thresholds, entropy-based
detection, connection-tracking for ACK/RST floods, and exporting metrics to
Prometheus.

---

## ⚠️ Ethical & legal use

`scripts/attack_sim.sh` generates real flood traffic. Use it **only** against
systems you own or are explicitly authorized to test, on an **isolated/private
network**. The script refuses non-RFC1918 targets by default. Attacking hosts
you don't control is illegal in most jurisdictions. This project is for
defensive security research and education.

---

## License

The eBPF program is GPL-2.0 (required for GPL-only BPF kernel helpers).
