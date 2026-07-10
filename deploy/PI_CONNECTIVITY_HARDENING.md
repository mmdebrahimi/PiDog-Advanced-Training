# Pi Connectivity Hardening (do this once — it's the meta-blocker)

The Pi keeps dropping off the network (`192.168.2.26` unreachable, `raspberrypi.local`
unresolved), which kills every remote diagnosis attempt. Two fixes: a **static IP** (so
it's always at a known address) and **disable WiFi power-save** (so it doesn't nap off
the network when idle). ~10 minutes at the Pi keyboard/HDMI or over a working SSH.

Run on the Pi. Find the WiFi interface name first: `ip link` (usually `wlan0`).

---

## 1. Static IP

### Raspberry Pi OS Bookworm (NetworkManager — most likely)
```bash
# Replace SSID, the .26 address, and the router/.1 to match your LAN.
nmcli connection show                          # find your wifi connection name
nmcli connection modify "<wifi-conn-name>" \
    ipv4.method manual \
    ipv4.addresses 192.168.2.26/24 \
    ipv4.gateway 192.168.2.1 \
    ipv4.dns "192.168.2.1 8.8.8.8"
nmcli connection up "<wifi-conn-name>"
```

### Older Bullseye/Buster (dhcpcd)
```bash
sudo tee -a /etc/dhcpcd.conf >/dev/null <<'EOF'

interface wlan0
static ip_address=192.168.2.26/24
static routers=192.168.2.1
static domain_name_servers=192.168.2.1 8.8.8.8
EOF
sudo systemctl restart dhcpcd
```

> Better still: set a **DHCP reservation** for the Pi's MAC in the router admin — survives
> OS reinstalls. Get the MAC with `cat /sys/class/net/wlan0/address`.

---

## 2. Disable WiFi power-save (stops the idle drop-offs)

Check current state:
```bash
iw dev wlan0 get power_save        # likely says: Power save: on
```

### Persist OFF — NetworkManager (Bookworm)
```bash
sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null <<'EOF'
[connection]
wifi.powersave = 2
EOF
sudo systemctl restart NetworkManager
```
(`2` = disabled.)

### Persist OFF — systemd one-shot (works on any setup)
```bash
sudo tee /etc/systemd/system/wifi-powersave-off.service >/dev/null <<'EOF'
[Unit]
Description=Disable wifi power save
After=network.target
[Service]
Type=oneshot
ExecStart=/sbin/iw dev wlan0 set power_save off
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now wifi-powersave-off.service
```

Verify after reboot:
```bash
iw dev wlan0 get power_save        # should say: Power save: off
```

---

## 3. Verify it's reachable + stays up
```bash
hostname -I                        # confirm 192.168.2.26
ping -c 4 192.168.2.1              # gateway reachable
# from the laptop, after this is set:
#   ssh <user>@192.168.2.26
```

Optional keep-alive (only if drops persist) — a tiny cron ping to the router every minute
keeps the link warm:
```bash
( crontab -l 2>/dev/null; echo "* * * * * ping -c1 192.168.2.1 >/dev/null 2>&1" ) | crontab -
```

---

Once this is done, the Pi is reliably at `192.168.2.26` and three blocked threads unblock:
**stand diagnosis** (`stand_doctor.py`), **speaker swap test**, and **walking-policy deploy**.
