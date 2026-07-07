# Step-by-Step Lab Guide

A beginner-friendly walkthrough: build the Ubuntu server, attach the detector,
and run a (controlled, legal) DDoS attack against it to see detection working.

---

## The most important idea first

A DDoS test needs **two machines on the same private network**:

```
   ┌───────────────────────┐            ┌───────────────────────┐
   │   MACHINE A: SERVER    │            │  MACHINE B: ATTACKER   │
   │   (the "victim")       │  ◄──────── │  sends flood traffic   │
   │                        │  network   │                        │
   │  • target_server.py    │            │  • attack_sim.sh       │
   │  • xdp_ddos_loader      │            │    (hping3 flood)      │
   │    (XDP detector)      │            │                        │
   │  IP: 192.168.56.10     │            │  IP: 192.168.56.11     │
   └───────────────────────┘            └───────────────────────┘
```

You **cannot** properly attack a machine from itself — XDP inspects traffic
*arriving on the network card*, and traffic to yourself (loopback) never gets
there. So you need Machine A (the server we protect) and Machine B (the attacker
that floods it). Both can be **VirtualBox VMs on your laptop** — you don't need
real hardware or the internet. That's the safe, legal way to do this.

> ⚠️ Only ever attack a machine you own on an isolated network. Doing this
> against anything on the public internet is illegal.

---

## Option 1 (recommended): Two VirtualBox VMs on your laptop

This keeps everything on a private, isolated network. Nothing leaves your PC.

### Step 1 — Install VirtualBox and download Ubuntu Server

1. Install **VirtualBox** (free): https://www.virtualbox.org/
2. Download **Ubuntu Server 24.04 LTS** ISO: https://ubuntu.com/download/server

### Step 2 — Create the SERVER VM (Machine A)

1. In VirtualBox: **New** → Name `target-server`, Type *Linux*, Version *Ubuntu 64-bit*.
2. Memory: 2048 MB, Disk: 15 GB. Attach the Ubuntu Server ISO and install it.
   During install, create a user (e.g. `student`) and enable **OpenSSH**.
3. **Add a private network** so the two VMs can talk:
   - Power off the VM → **Settings → Network → Adapter 2**.
   - Enable it, set **Attached to: Host-only Adapter** (or "Internal Network").
   - (Adapter 1 stays NAT so the VM can reach the internet to install packages.)

### Step 3 — Create the ATTACKER VM (Machine B)

Repeat Step 2, name it `attacker` (this is your "DDoS server"). Give it the **same** Host-only / Internal
network on Adapter 2 so both VMs are on the same private LAN.

### Step 4 — Find each VM's private IP

Boot both VMs, log in, and on **each** run:

```bash
ip -4 addr show
```

Look at the adapter on the private network (often `enp0s8`). You'll see
something like `192.168.56.10` on the server and `192.168.56.11` on the
attacker. **Write these down.** From now on:

- `SERVER_IP`  = the server's private IP (e.g. `192.168.56.10`)
- The attacker floods `SERVER_IP`.

Verify they can reach each other — from the attacker VM:

```bash
ping -c 3 <SERVER_IP>
```

If ping works, the network is set up correctly.

---

## Setting up the SERVER (Machine A)

Do all of this **on the server VM**.

### Step 5 — Get the project and install dependencies

```bash
# install git if needed
sudo apt-get update && sudo apt-get install -y git

# clone your project (or copy it in)
git clone <your-repo-url> Research-project
cd Research-project

# install the eBPF/XDP toolchain (clang, libbpf, headers, hping3, etc.)
sudo ./scripts/setup.sh
```

### Step 6 — Build the detector

```bash
make
```

This creates two files in `build/`:
- `xdp_ddos.bpf.o` — the kernel program (runs inside Linux via XDP)
- `xdp_ddos_loader` — the program you run to load it and watch stats

### Step 7 — Start the target service (the thing being protected)

Open a terminal on the server and run:

```bash
python3 server/target_server.py 0.0.0.0 8080
```

Leave it running. This is a tiny web server on port 8080 — it stands in for a
"real" website that the attacker will try to overwhelm.

### Step 8 — Find your network interface name

Open a **second** terminal on the server:

```bash
ip link
```

Find the interface on the private network — the one whose IP matched `SERVER_IP`
in Step 4 (commonly `enp0s8` in VirtualBox, or `eth0`). Call it `IFACE`.

### Step 9 — Attach the XDP detector

In that second terminal:

```bash
sudo ./build/xdp_ddos_loader -i enp0s8
```

Replace `enp0s8` with your `IFACE`. You'll now see a **live dashboard** that
refreshes every second:

```
=== XDP DDoS Detector on enp0s8 ===   14:02:11   8 pps

 Total packets seen     : 128
 Passed (allowed)       : 128
 Dropped (attack)       : 0
 TCP packets            : 40
 ...
 Currently blocked sources (src IP  ->  total pkts):
   (none)
```

> If you see "native XDP attach failed, retrying in SKB mode" — that's fine.
> VirtualBox NICs often don't support native XDP, so it uses the slower but
> fully working generic mode automatically. You can also force it with `-S`.

**The server is now protected and watching. Leave this dashboard visible.**

---

## Running the ATTACK (Machine B)

Do this **on the attacker VM**. This is the "how to attack" part.

### Step 10 — Get the scripts and install hping3

```bash
sudo apt-get update && sudo apt-get install -y git hping3
git clone <your-repo-url> Research-project
cd Research-project
```

### Step 11 — Fire a SYN flood at the server

`hping3` is the tool that generates the flood. Our `attack_sim.sh` wraps it
safely. Run (replace with your real `SERVER_IP`):

```bash
sudo ./ddos-simulator/attack_sim.sh 192.168.56.10 syn 20
```

This means: flood `192.168.56.10` with **TCP SYN** packets for **20 seconds**,
using randomized (spoofed) source IPs. Other modes:

```bash
sudo ./ddos-simulator/attack_sim.sh <SERVER_IP> udp 20     # UDP flood
sudo ./ddos-simulator/attack_sim.sh <SERVER_IP> icmp 20    # ping flood
sudo ./ddos-simulator/attack_sim.sh <SERVER_IP> mixed 20   # all three at once
```

### What "attack" actually means here

`hping3 --flood --rand-source -S -p 80` sends TCP SYN packets **as fast as the
machine can**, each pretending to come from a different random IP. A real DDoS
does the same thing from thousands of machines; here one VM simulates it. The
`-S` means SYN (a "please open a connection" packet). Sending millions of these
without ever completing the connection is a classic **SYN flood** — cheap for
the attacker, expensive for an unprotected server.

### Step 12 — Watch detection happen (back on the SERVER dashboard)

While the attack runs, switch to the server's detector dashboard. Within a
second or two you'll see:

```
=== XDP DDoS Detector on enp0s8 ===   14:05:44   180000 pps   ← huge spike

 Total packets seen     : 3540221
 Passed (allowed)       : 21000
 Dropped (attack)       : 3330221     ← climbing fast
 TCP SYN packets        : 3500000
 IP block events        : 4127         ← sources getting blocked

 Currently blocked sources (src IP  ->  total pkts):
   57.10.3.44        2003 pkts (2003 SYN)
   190.22.9.1        2001 pkts (2001 SYN)
   ...
```

- **Dropped (attack)** rising = the kernel is discarding flood packets at the
  network card, before they reach your web server.
- **IP block events** = number of source IPs that crossed the threshold and got
  blocked.
- **Currently blocked sources** = who is being filtered right now.

That is your detection working. **This is the result to screenshot for your
research report.**

---

## Step 13 — Prove legitimate traffic still works

The point of detection is that *real* users get through while attackers are
blocked. From the **attacker VM (or a third machine)**, during or right after
the flood:

```bash
curl http://192.168.56.10:8080/
```

You should still get:

```
OK - target server alive
uptime: 300s
requests served: 42
```

To make the contrast obvious, run the experiment twice and compare:

1. **Without protection:** stop the detector (Ctrl-C), start the flood, then try
   `curl` — it will be slow or time out.
2. **With protection:** attach the detector again, start the flood, try `curl` —
   it stays responsive because the flood is dropped in-kernel.

That before/after comparison is the core experiment of your project.

---

## Tuning (so you don't block real users)

The thresholds decide when an IP is called an "attacker":

```bash
sudo ./build/xdp_ddos_loader -i enp0s8 \
    -p 2000 \      # packets per second per IP before blocking
    -s 200  \      # SYN packets per second per IP before blocking
    -w 1000 \      # measurement window in milliseconds
    -b 30          # how many seconds to block a flagged IP
```

- Set thresholds **above** your normal peak traffic but **below** attack levels.
- Too low → you block real users (false positives).
- Too high → floods leak through.
- Measure your normal traffic on the dashboard first, then set limits above it.

---

## Quick troubleshooting

| Problem | Fix |
|--------|-----|
| `make` fails, "clang not found" | Run `sudo ./scripts/setup.sh` first |
| "native XDP attach failed" | Normal on VMs — it auto-uses SKB mode, or add `-S` |
| Attacker can't reach server | Check both VMs share the Host-only/Internal network; `ping <SERVER_IP>` |
| Dashboard shows 0 packets during attack | Wrong interface — re-check Step 8, use the private-network `IFACE` |
| "Refusing non-private target" | The sim only allows 10.x / 192.168.x / 172.16-31.x IPs — use the private IP |
| Permission denied attaching XDP | Run the loader with `sudo` |

---

## Option 2: Two cloud servers (advanced)

If you prefer real Ubuntu servers instead of VMs, rent **two** small VMs from
one provider **in the same private network / VPC** (so traffic stays private and
you're not attacking across the public internet). Put the detector on one and
run `attack_sim.sh` from the other, using their **private** IPs. Everything else
is identical to Steps 5–13. Always confirm your provider allows load/stress
testing on your own instances first.
