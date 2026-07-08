# Setting up Ubuntu in Oracle VirtualBox — simple config

You will make **two** virtual machines with the **same steps**:

- `target-server`  → the machine you attack + protect
- `attacker`       → the machine that runs the DDoS simulator

Do every step below once for `target-server`, then repeat for `attacker`.

---

## Why Ubuntu Server (and not Desktop)?

- **Server = command line only, no desktop GUI.** It uses much less RAM/CPU,
  which matters because you run **two** VMs at once.
- Everything in this project runs with **commands**, so you never need a mouse.
- If a black command-line screen feels scary, **Ubuntu Desktop works exactly the
  same** for this project — it just adds a clickable GUI and uses more memory.
  Either one is fine. Server is the lighter, standard lab choice.

---

## Step 1 — Download Ubuntu (one file)

Download **Ubuntu Server 24.04 LTS**:
👉 https://ubuntu.com/download/server

You get one file, e.g. `ubuntu-24.04-live-server-amd64.iso`. Save it somewhere
easy to find. You use the **same** file for both VMs.

---

## Step 2 — Create the VM in VirtualBox

Open VirtualBox → click **New**. Use exactly these settings:

| Setting | Value (target-server) | Value (attacker) |
|---------|----------------------|------------------|
| Name | `target-server` | `attacker` |
| Type | Linux | Linux |
| Version | Ubuntu (64-bit) | Ubuntu (64-bit) |
| Memory (RAM) | 2048 MB | 1024 MB |
| Processors (CPU) | 2 | 1 |
| Hard disk | Create new, **15 GB**, VDI, dynamically allocated | same |

> If it asks for "Unattended Install", tick **"Skip Unattended Installation"** —
> that gives you the normal Ubuntu installer, which is easier to follow.

Click **Create**.

---

## Step 3 — Attach the Ubuntu ISO

Select the VM → **Settings** → **Storage**:

1. Under the storage tree, click the disc icon that says **Empty**.
2. On the right, click the little blue disc icon → **Choose a disk file...**
3. Pick your `ubuntu-...iso` file.
4. Click **OK**.

---

## Step 4 — Network config ⭐ (the most important part)

The two VMs must be able to talk to each other. You give each VM **two**
network adapters. Select the VM → **Settings** → **Network**:

**Adapter 1** (gives the VM internet, to install software)
- ✅ Enable Network Adapter
- Attached to: **NAT**

**Adapter 2** (the private lab network — how the two VMs reach each other)
- Click the **Adapter 2** tab
- ✅ Enable Network Adapter
- Attached to: **Host-only Adapter**
- Name: **VirtualBox Host-Only Ethernet Adapter** (see note below if empty)

Click **OK**. Do this for **both** VMs, exactly the same.

> **If the "Name" dropdown for Host-only is empty:** create the network once.
> In VirtualBox go to **File → Tools → Network Manager → Host-only Networks →
> Create**. It makes `192.168.56.0/24` by default. Then come back to Adapter 2
> and pick it. (In some versions this menu is called **Host Network Manager**.)

---

## Step 5 — Install Ubuntu

Start the VM (green **Start** arrow). The Ubuntu installer boots. Accept the
defaults, and when asked:

- Language / keyboard → English (or your choice)
- Network → leave as is (it auto-detects both adapters)
- Storage → "Use an entire disk" → Done → Continue
- **Profile**: set a name and password you will remember, e.g.
  - your name: `student`
  - username: `student`
  - password: `student123`
- **"Install OpenSSH server"** → ✅ tick this (useful later)
- Skip the "featured snaps" screen

Wait for it to finish, then choose **Reboot Now**. If it says "remove the
installation medium", just press **Enter**. Log in with your username/password.

Repeat Steps 2–5 for the second VM (`attacker`).

---

## Step 6 — The IP addresses (automatic vs manual)

Each VM has **two** adapters, so it has **two** IPs — and they do different jobs:

| Adapter | Job | IP | Do you set it? |
|---------|-----|----|----------------|
| Adapter 1 · NAT | internet, for `apt install` | automatic, like `10.0.2.15` | ❌ leave it alone |
| Adapter 2 · Host-only | the lab network (VM ↔ VM) | this is the one that matters | ✅ set this |

First, just look at what you have. Log into each VM and run:

```bash
ip -4 addr show
```

The **Host-only** adapter (usually `enp0s8`) shows an address like
`192.168.56.x`. That is your lab IP.

### Automatic or manual?

- **Automatic (DHCP)** — VirtualBox may hand out an IP by itself (e.g.
  `192.168.56.101`). Easy, but it can **change** when you reboot, which breaks
  your commands.
- **Manual (static)** — you pin a fixed IP. **Recommended**, so `target-server`
  is *always* `192.168.56.10` and `attacker` is *always* `192.168.56.11`.

### How to set a manual (static) IP

Ubuntu uses a config file called **netplan**. On the VM:

```bash
ls /etc/netplan/                            # find the file name
sudo nano /etc/netplan/50-cloud-init.yaml   # open it (use the name you saw)
```

Make the file look like this — on **target-server**:

```yaml
network:
  version: 2
  ethernets:
    enp0s3:
      dhcp4: true
    enp0s8:
      dhcp4: false
      addresses: [192.168.56.10/24]
```

On the **attacker** VM, change the last line to `[192.168.56.11/24]`.

Save the file (`Ctrl+O`, Enter, then `Ctrl+X`), then apply it:

```bash
sudo netplan apply
ip -4 addr show enp0s8      # confirm your fixed IP is there
```

> ⚠️ YAML is picky: use **spaces, never tabs**, and keep the indentation exactly
> as shown. `enp0s3` = Adapter 1 (NAT), `enp0s8` = Adapter 2 (Host-only) — check
> your real names with `ip a` first and use those.

### Test the connection

On the `attacker` VM run:

```bash
ping -c 3 192.168.56.10
```

If you get replies, the two VMs can talk. ✅ Setup done.

---

## Step 7 — Put the project on both VMs

On **each** VM:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone <your-repo-url> Research-project
cd Research-project
```

- On `target-server` also run: `sudo ./scripts/setup.sh` then `make`
  (installs the eBPF tools and builds the detector).
- On `attacker` also run: `sudo apt-get install -y python3 hping3`

---

## Step 8 — How the simulator makes the attack

Now the part you asked about. On the **target-server**:

```bash
# terminal 1: start the website (the victim)
python3 server/target_server.py 0.0.0.0 8080
# terminal 2: start the detector
sudo ./build/xdp_ddos_loader -i enp0s8
```

On the **attacker**, use the web control panel you already have working:

```bash
sudo python3 ddos-simulator/webui/server.py 0.0.0.0 5000
# open http://192.168.56.11:5000/ in a browser
```

…or the command line:

```bash
sudo python3 ddos-simulator/ddos_simulator.py 192.168.56.10 --mode syn --port 8080 --duration 20
```

**What actually happens:** the simulator opens a network socket and sends
*thousands of packets per second* to the target's IP (`192.168.56.10`), each
with a fake random source address. That massive burst of packets **is** the
DDoS flood. On the target, your XDP/eBPF program sees them arrive on the network
card, counts them per source, and **drops** the flood — while real requests
still get through. You watch that on the detector dashboard.

That is your whole research experiment. 🎓

---

## Quick recovery if something breaks

| Problem | Fix |
|--------|-----|
| VMs can't ping each other | Both must have **Adapter 2 = Host-only** on the **same** host-only network |
| No internet in VM (apt fails) | **Adapter 1** must be **NAT** and enabled |
| Host-only name is empty | File → Tools → Network Manager → create a Host-only network |
| Don't know the interface name | `ip -4 addr show` — use the one with the 192.168.56.x address |
| Detector says "native XDP failed" | Normal on VMs — it switches to SKB mode automatically |
