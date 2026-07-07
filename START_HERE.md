# START HERE — The whole project, step by step, from zero

If everything else confused you, ignore it and follow only this file.

---

## 1. The idea (the "map")

Think of it like **two houses on the same street**:

```
        SAME PRIVATE NETWORK (like one street)
   ┌──────────────────────────┬──────────────────────────┐
   │                          │                          │
   ▼                          │                          ▼
┌─────────────────────────┐   │   ┌─────────────────────────┐
│  MACHINE 1: THE SERVER  │   │   │ MACHINE 2: THE ATTACKER │
│  (we protect this one)  │   │   │  (this floods the       │
│                         │   │   │   server = "DDoS")      │
│  address: 192.168.56.10 │◄──┼───│  address: 192.168.56.11 │
│                         │   │   │                         │
│  runs:                  │  sends │  runs:                  │
│  • a small website      │ flood  │  • the DDoS simulator   │
│  • the XDP detector     │───────►│    (attacks .10)        │
│    (blocks the flood)   │        │                         │
└─────────────────────────┘        └─────────────────────────┘
```

Two computers. Both on the same private network. The **attacker (.11)** sends a
flood of packets **to the server (.10)**. The server's **XDP detector** watches
its network card and drops the flood. That is the whole experiment.

You cannot do this on one computer alone, because the detector only sees
traffic **arriving from the network** — so you need a second machine to send it.

The two computers will be **virtual machines** on your laptop (free, safe,
private). One command builds both.

---

## 2. What you install ONCE on your laptop

You only need two free programs on your own laptop:

1. **VirtualBox** → https://www.virtualbox.org/  (runs the virtual machines)
2. **Vagrant** → https://www.vagrantup.com/  (builds them automatically)

Install both, then **restart your laptop** so they load properly.

To check they installed, open a terminal / command prompt and run:

```bash
vagrant --version
VBoxManage --version
```

If both print a version number, you are ready.

> Terminal = Command Prompt / PowerShell on Windows, or the "Terminal" app on
> Mac/Linux.

---

## 3. Get the project onto your laptop

In the terminal:

```bash
git clone <your-repo-url> Research-project
cd Research-project
```

(Replace `<your-repo-url>` with your GitHub project's clone link. You must stay
inside this `Research-project` folder for the next commands.)

---

## 4. Build BOTH machines with ONE command

Still inside the `Research-project` folder:

```bash
vagrant up
```

**This one command does everything:** it downloads Ubuntu, creates the two
virtual machines, puts them on the same private network, installs all the
software, and builds the detector. The first time it takes ~5–15 minutes
(it downloads Ubuntu). Let it finish.

When it's done you have your two servers:

| Machine name    | Address        | Job                         |
|-----------------|----------------|-----------------------------|
| `target-server` | 192.168.56.10  | the website + XDP detector  |
| `attacker`      | 192.168.56.11  | sends the DDoS attack       |

---

## 5. THE SERVER — turn on the website + the detector

You need **two terminals into the server**. Open a terminal, go to the
`Research-project` folder, and do the following.

**Terminal A — log into the server and start the website:**

```bash
vagrant ssh target-server
python3 /vagrant/server/target_server.py 0.0.0.0 8080
```

Leave it running. It says: `Target server listening on http://0.0.0.0:8080/`.

**Terminal B — open a NEW terminal, log into the server again, start the detector:**

```bash
cd Research-project
vagrant ssh target-server
sudo /vagrant/build/xdp_ddos_loader -i enp0s8
```

Now you see a live dashboard that updates every second. It shows
`Dropped (attack): 0` and `blocked sources: (none)` — because no attack yet.

> If it says *"native XDP attach failed, retrying in SKB mode"* that is normal
> and fine on a virtual machine.

**Leave both of these running.** The server is now on and protected.

---

## 6. THE ATTACKER — send the DDoS

Open a **third** terminal, go to the `Research-project` folder, and log into the
attacker machine:

```bash
cd Research-project
vagrant ssh attacker
```

Now run the attack against the server's address (192.168.56.10):

```bash
sudo python3 /vagrant/attacker/ddos_simulator.py 192.168.56.10 --mode syn --port 8080 --duration 20
```

The attacker prints how many packets it is sending:

```
 sent: 50582     rate: 25240 pkts/s
```

---

## 7. See the result (this is your experiment)

While the attack runs, look back at **Terminal B** (the detector on the server).
You will see the numbers jump:

```
 Dropped (attack)   : 3330221     ← the flood being blocked
 IP block events    : 4127        ← attackers getting blocked
 Currently blocked sources:
    57.10.3.44   2003 pkts
    ...
```

**That is kernel-level DDoS detection working.** Take a screenshot for your
report.

---

## 8. Prefer a web page instead of commands for the attack?

Instead of step 6, on the attacker run the browser control panel:

```bash
vagrant ssh attacker
sudo python3 /vagrant/attacker/webui/server.py 0.0.0.0 5000
```

Then on your laptop open a browser at **http://192.168.56.11:5000/**, set
target `192.168.56.10`, choose an attack, and click **Launch attack**.

---

## 9. When you are finished

```bash
vagrant halt        # turn both machines off (keeps them for next time)
vagrant destroy -f  # delete both machines completely
```

---

## Cheat-sheet: which command runs WHERE

| Where            | Command                                                            |
|------------------|-------------------------------------------------------------------|
| your laptop      | `vagrant up`  (build both machines)                               |
| server, term A   | `python3 /vagrant/server/target_server.py 0.0.0.0 8080`          |
| server, term B   | `sudo /vagrant/build/xdp_ddos_loader -i enp0s8`                  |
| attacker         | `sudo python3 /vagrant/attacker/ddos_simulator.py 192.168.56.10 --mode syn --port 8080 --duration 20` |

Remember the map: **attacker (.11) → floods → server (.10) → detector blocks it.**
