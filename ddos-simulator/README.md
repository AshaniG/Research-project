# ddos-simulator

All the DDoS attack tools for the lab, in one folder. Run these on the
**attacker** machine, aimed at the **target server** (e.g. `192.168.56.10`).

> **Authorized lab use only.** Point these at a machine you own on an isolated
> private network. Flooding hosts you don't control is illegal.

## Files

| File | What it is |
|------|-----------|
| `ddos_simulator.py` | Command-line simulator (pure Python). Modes: `syn`, `udp`, `icmp`, `http`. |
| `webui/server.py`   | Web control panel — drive the simulator from a browser. |
| `webui/index.html`  | The control-panel page (served by `webui/server.py`). |
| `attack_sim.sh`     | Simpler shell version built on `hping3`. |

## Run it

**Command line:**
```bash
sudo python3 ddos_simulator.py 192.168.56.10 --mode syn --port 8080 --duration 20
# modes: syn | udp | icmp | http    (http needs no sudo)
```

**Web control panel (browser):**
```bash
sudo python3 webui/server.py 0.0.0.0 5000
# then open http://<attacker-ip>:5000/ in a browser
```

**hping3 wrapper:**
```bash
sudo ./attack_sim.sh 192.168.56.10 syn 20
```

`sudo` is required for `syn`/`udp`/`icmp` (raw sockets); `http` mode works without
it. All tools refuse non-private targets unless you explicitly force it.

See the project root `README.md` and `START_HERE.md` for the full lab setup.
