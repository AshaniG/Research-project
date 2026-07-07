# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A research project that detects and mitigates volumetric DDoS attacks (SYN/UDP/ICMP floods) **inside the Linux kernel** using XDP/eBPF, plus the supporting lab tooling (victim server, attack simulator, two-VM Vagrant environment) needed to demonstrate it.

The eBPF/XDP detector only builds and runs on Linux (kernel 5.5+, native XDP or SKB/generic mode). The Python simulator/web UI pieces are plain Python 3 and portable.

## Commands

```bash
sudo ./scripts/setup.sh        # one-time: installs clang/llvm, libbpf-dev, libelf-dev,
                                # kernel headers, bpftool, hping3, iperf3 (Debian/Ubuntu, needs root)
make                            # builds build/xdp_ddos.bpf.o and build/xdp_ddos_loader
make clean                      # removes build/

sudo ./build/xdp_ddos_loader -i <iface> [-p pkt] [-s syn] [-w window_ms] [-b block_sec] [-S skb-mode]
                                # attach the detector; requires CAP_NET_ADMIN/CAP_BPF (root)

python3 server/target_server.py [host] [port]           # victim HTTP server (default 0.0.0.0:8080)
sudo python3 ddos-simulator/ddos_simulator.py <target> --mode syn|udp|icmp|http --port <p> -t <threads> -d <secs>
sudo python3 ddos-simulator/webui/server.py [host] [port]  # browser control panel for the simulator (default port 5000)
sudo ./ddos-simulator/attack_sim.sh <target> syn|udp|icmp|mixed <secs>  # hping3-based alternative to the Python simulator

./demo.sh                       # single-machine demo: runs target_server.py + webui/server.py locally, no root/VMs needed
vagrant up                      # builds the full two-VM lab (target-server 192.168.56.10, attacker 192.168.56.11);
                                 # provisioning scripts: vagrant/provision_server.sh, vagrant/provision_attacker.sh
```

There is no test suite. There is no linter config. "Building" means the `make` step above (compiles the BPF object with clang targeting `bpf`, and links the loader against `libbpf`/`libelf`/`libz` with gcc). Both `build/xdp_ddos.bpf.o` and `build/xdp_ddos_loader` must exist before the loader will run — the loader hardcodes `build/xdp_ddos.bpf.o` as a relative path, so `xdp_ddos_loader` must be run from the repo root.

## Architecture

Two independent halves connected only through `src/common.h`, which defines the shared BPF map value layouts (`struct ip_stats`, `struct config`, `enum stat_index`) — kernel and user space must agree on these byte-for-byte, so any change to that header requires updating both sides and rebuilding.

**Kernel side — `src/xdp_ddos.bpf.c`** (compiled to `build/xdp_ddos.bpf.o`, attached at the XDP hook):
- Parses Ethernet → IPv4 → (TCP/UDP/ICMP) headers directly out of the packet buffer with explicit bounds checks against `data_end` (required by the BPF verifier).
- Tracks per-source-IPv4 state in `ip_track_map`, a `BPF_MAP_TYPE_LRU_HASH` keyed by source IP (bounded to `MAX_TRACKED_IPS`, so a spoofed-IP flood evicts old entries rather than exhausting memory).
- Maintains a sliding time window (`window_start`/`packets`/`syn_count`) per IP; TCP SYN-without-ACK is counted separately from total packets since SYN floods use a lower threshold.
- On threshold breach (`packets > pkt_threshold` or `syn_count > syn_threshold`), flags the IP `blocked` with a `block_until` timestamp and returns `XDP_DROP` for the cool-down duration; everything else returns `XDP_PASS`.
- Reads tunable thresholds from `config_map` (single-entry array map) at runtime, falling back to the `DEFAULT_*` constants in `common.h` if unset — thresholds are adjustable without recompiling the BPF object.
- Global running counters live in `stats_map` (`BPF_MAP_TYPE_ARRAY`, indexed by `enum stat_index`).

**User space — `src/xdp_ddos_loader.c`** (compiled to `build/xdp_ddos_loader`):
- Opens/loads the BPF object via libbpf, writes CLI-supplied thresholds into `config_map`, attaches the program to the given interface (tries native/`XDP_FLAGS_DRV_MODE` first, automatically retries `XDP_FLAGS_SKB_MODE` if the driver/veth doesn't support native XDP — this is expected and normal inside VMs), and detaches cleanly on SIGINT/SIGTERM.
- Runs a 1-second poll loop that reads `stats_map` and walks `ip_track_map` (via `bpf_map_get_next_key`) to render a live terminal dashboard of packet counts and currently-blocked source IPs.

**Lab/demo tooling (all Python/shell, independent of the BPF build):**
- `server/target_server.py` — minimal `ThreadingHTTPServer` "victim" whose only job is to prove real traffic still gets through while the detector is dropping flood traffic.
- `ddos-simulator/ddos_simulator.py` — self-contained Python flood generator (no hping3 dependency); modes `syn`/`udp`/`icmp` use raw sockets with randomized spoofed source IPs (needs root) and `http` mode sends real HTTP GETs (no root). Refuses non-RFC1918 targets unless `--force` is passed — this guard exists for safety/legal reasons, not just correctness, so don't relax it casually.
- `ddos-simulator/webui/server.py` + `index.html` — stdlib-only (no Flask) HTTP server exposing a browser control panel that drives the same simulator engine as the CLI, with the same private-target guard.
- `ddos-simulator/attack_sim.sh` — alternative flood generator wrapping `hping3` directly.
- `Vagrantfile` + `vagrant/provision_*.sh` — stands up the canonical two-VM lab (`target-server` at 192.168.56.10 runs the victim + detector, `attacker` at 192.168.56.11 runs the simulator) on a private host-only network, since XDP can only observe traffic arriving over a real NIC — you cannot demonstrate detection against loopback traffic on a single machine.

## Key constraint to keep in mind when editing

The detector fundamentally requires two machines (or VMs) on a shared network: XDP inspects packets as they arrive on a NIC, so a single machine attacking itself never triggers it (loopback traffic doesn't traverse the XDP hook). `demo.sh` sidesteps this by only exercising the HTTP-flood/target-server/web-UI path locally — it does not exercise `xdp_ddos.bpf.c` at all.
