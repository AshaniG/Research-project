# Vagrantfile - Automatically creates the whole DDoS-detection lab.
#
# One command builds TWO Ubuntu 24.04 virtual machines, wired onto the same
# private network, with all software installed and the detector pre-built:
#
#     vagrant up
#
#   ddos-server    192.168.56.10   ← the protected "victim" + XDP detector
#   ddos-attacker  192.168.56.11   ← runs the flood against the server
#
# Requires (on your laptop): VirtualBox + Vagrant.
#   https://www.virtualbox.org/   https://www.vagrantup.com/
#
# Everyday use after `vagrant up`:
#   vagrant ssh ddos-server      # then run the target server + detector
#   vagrant ssh ddos-attacker    # then run scripts/attack_sim.sh
#   vagrant halt                 # power both off
#   vagrant destroy -f           # delete both VMs
#
# This project folder is auto-mounted inside each VM at /vagrant.

Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # Keep both VMs on the same private (host-only) network so they can flood
  # each other safely, isolated from the internet and your real LAN.

  # ---- The SERVER (victim + detector) ----------------------------------
  config.vm.define "ddos-server" do |srv|
    srv.vm.hostname = "ddos-server"
    srv.vm.network "private_network", ip: "192.168.56.10"
    srv.vm.provider "virtualbox" do |vb|
      vb.name = "ddos-server"
      vb.memory = 2048
      vb.cpus = 2
    end
    srv.vm.provision "shell", path: "vagrant/provision_server.sh"
  end

  # ---- The ATTACKER -----------------------------------------------------
  config.vm.define "ddos-attacker" do |atk|
    atk.vm.hostname = "ddos-attacker"
    atk.vm.network "private_network", ip: "192.168.56.11"
    atk.vm.provider "virtualbox" do |vb|
      vb.name = "ddos-attacker"
      vb.memory = 1024
      vb.cpus = 1
    end
    atk.vm.provision "shell", path: "vagrant/provision_attacker.sh"
  end
end
