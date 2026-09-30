# Bluetooth ESP32 Interface

Surface control station for an ESP32-WROOM-32 payload release unit, over Bluetooth Low Energy (BLE).

- **Unlatch · pay out to depth**: upload the release depth at the surface. The unit unlatches by itself when its sensor reaches that depth, then comes back up. (Bluetooth doesn't work underwater, so the depth has to be uploaded before the unit goes down.)
- **Winch**: pay out, stop, pay in.
- **Latch / Unlatch**: manual latch control. Unlatch is press-and-hold so it can't be triggered by accident.

For now, latch turns the onboard LED (GPIO 2) **on** and unlatch turns it **off**. The winch and depth commands are received and reported back but don't drive any hardware yet.

## Folder layout

| Folder | What it is |
|---|---|
| `esp32/esp32_payload_ble/` | ESP32 firmware. Upload this. |
| `raspberry-pi/` | `payload_server.py` + `index.html`. Holds the Bluetooth link and serves the control page on the network. Also runs on a PC. |
| `docs/` | The same page, for use on a phone directly over Web Bluetooth (served by GitHub Pages). |
| `examples/` | Simple starter sketches (Classic Bluetooth serial, BLE UART echo). |

The page detects where it's running. If it was served by `payload_server.py`, it goes through the server. Anywhere else, it shows a **Connect** button and talks to the ESP32 directly over Web Bluetooth.

## 1. Flash the ESP32

1. Arduino IDE → **Tools → Board → esp32 → ESP32 Dev Module**
2. Open `esp32/esp32_payload_ble/esp32_payload_ble.ino` and upload.
3. If the sketch is too big: **Tools → Partition Scheme → Huge APP (3MB No OTA)**.
4. Serial Monitor (115200) should show `BLE advertising as 'ESP32-BLE'`.

Only **one** device can be connected to the ESP32 at a time. Close Bluefruit, Bluefy etc. before the PC or Pi connects.

### Commands (plain text over the Nordic UART Service)

| Send | Does | Replies |
|---|---|---|
| `depth:12.5` | Set release depth (`depth:0` clears it) | `DEPTH 12.5` / `DEPTH NONE` |
| `payout` / `payin` / `stop` | Winch control | `WINCH OUT` / `WINCH IN` / `WINCH STOP` |
| `latch` / `unlatch` | Latch control (LED on / off) | `LATCHED` / `UNLATCHED` |
| `status` | Report everything | all three lines |

## 2. Test on a PC first

Needs Python 3.9+ and a PC with Bluetooth (Windows 10/11, macOS or Linux).

```bash
cd raspberry-pi
pip install -r requirements.txt

# No ESP32? Try the page against a fake one:
python payload_server.py --port 8080 --sim

# With the ESP32 powered on:
python payload_server.py --port 8080
```

Open **http://localhost:8080**. Other devices on the same network can use `http://<your-PC's-IP>:8080`. Windows may ask to allow Python through the firewall. Allow it for private networks.

## 3. Run it on the Raspberry Pi

Built-in Bluetooth works on Pi 3B/3B+/4/5/400/Zero W/Zero 2 W. Older models need a USB Bluetooth 4.0+ dongle.

```bash
sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/LukeGrif/Bluetooth-ESP32-Interface.git
cd Bluetooth-ESP32-Interface/raspberry-pi
python3 -m venv venv
venv/bin/pip install -r requirements.txt
sudo venv/bin/python payload_server.py        # serves on port 80
```

Then open **http://192.168.2.71** from any device on the network.

**Fixed IP 192.168.2.71** (Raspberry Pi OS Bookworm):
```bash
nmcli con show                                  # find your connection name, e.g. "Wired connection 1"
sudo nmcli con mod "Wired connection 1" ipv4.method manual \
  ipv4.addresses 192.168.2.71/24 ipv4.gateway 192.168.2.1 ipv4.dns 192.168.2.1
sudo nmcli con up "Wired connection 1"
```
Alternatively, reserve the address for the Pi in your router's DHCP settings.

**Start automatically on boot**: create `/etc/systemd/system/payload.service`:
```ini
[Unit]
Description=Payload release control server
After=bluetooth.target network-online.target
Wants=bluetooth.target network-online.target

[Service]
WorkingDirectory=/home/pi/Bluetooth-ESP32-Interface/raspberry-pi
ExecStart=/home/pi/Bluetooth-ESP32-Interface/raspberry-pi/venv/bin/python payload_server.py
Restart=always

[Install]
WantedBy=multi-user.target
```
Change `/home/pi` if your username isn't `pi`. Then run:
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now payload
journalctl -u payload -f        # watch the log
```

## 4. Or control from a phone directly

iPhone needs the free **Bluefy** browser. Safari and Chrome on iOS have no Web Bluetooth. Android works in Chrome.
Web Bluetooth needs HTTPS, so turn on GitHub Pages: **Settings → Pages → Deploy from a branch → `main` / `/docs`**, then open
`https://lukegrif.github.io/Bluetooth-ESP32-Interface/` in Bluefy and tap **Connect**.

## Next steps

- Winch: drive a motor driver from `setWinch()`.
- Latch: replace the LED with a servo (`ESP32Servo`) in `doLatch()` / `doUnlatch()`.
- Depth: add a pressure sensor (e.g. MS5837) and enable the auto-release block in `loop()`.
