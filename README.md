# RoboParty RP Server

AT protocol gateway for RK3588. WebSocket / UDP / Serial / Bluetooth transport.

> **Frontend UI moved to [Roboparty/roboparty_example](https://github.com/Roboparty/roboparty_example)**

---

## Architecture

```
transport/   WebSocket / Serial / Bluetooth / UDP     ← four transport channels
protocol/    AT parsing + dispatch                    ← core abstraction
drivers/     motors / imu / joy / policy              ← hardware drivers
gamepad/     DJI/G12/evdev → AT bridge
```

### Data Flow

```
App手柄 ──UDP:9000──┐
App ──WS:8765──────┼──→ AtHandler ──→ drivers ──→ Hardware
串口 ──UART───────┤
蓝牙 ──RFCOMM─────┘
```

---

## REST API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check + hardware status |
| GET | `/api/status` | Full hardware snapshot |
| GET | `/sysinfo` | CPU / memory / load |
| WS | `/ws` | AT protocol |

---

## AT Protocol

**Commands:**

| Command | Params | Description |
|---------|--------|-------------|
| `AT+CONN?` | none | Connection status |
| `AT+BTN=<name>,<state>,<id>` | name:a/b/x/y/lb/rb, state:up/down, id:seq | Button event |
| `AT+JOY=<axis>,<value>` | axis:lx/ly/rx/ry, value:-1~1 | Joystick axis |
| `AT+SYSINFO?` | none | CPU / memory / load |
| `AT+POLICY?` | none | Policy status |
| `AT+POLICY=<name>,start\|stop` | name:policy name | Start/stop inference |
| `AT+ERR?` | none | Motor error codes |
| `AT+RESET` | none | Emergency stop: zero joystick + clear errors + stop policy |

**Pushes (auto-broadcast):**

| Format | Rate | Content |
|--------|------|---------|
| `@IMU w x y z gx gy gz ax ay az temp` | 100Hz | Attitude |
| `@BAT V A SoC temp` | 1Hz | Battery |
| `@ERR id code name` | 10Hz | Motor errors |

---

## Control Mapping

| Direction | AT Command | Joystick | Effect |
|-----------|-----------|----------|--------|
| Forward | `AT+JOY=ry,-1` | Right stick ↑ | Move forward |
| Backward | `AT+JOY=ry,1` | Right stick ↓ | Move backward |
| Left turn | `AT+JOY=rx,-1` | Right stick ← | Turn left |
| Right turn | `AT+JOY=rx,1` | Right stick → | Turn right |

### Operation Sequence

```
X (enable) → A (reset) → B (inference) → joystick → robot moves
```

---

## Quick Start (mock mode)

```bash
PYTHONPATH=src python3 -m rp_server --mock --port 8765
```

---

## Production Deployment

### One-shot systemd install

```bash
cd ~/roboparty_rp_server
sudo bash scripts/install_systemd.sh
```

### Service Management

```bash
systemctl status rp-server
journalctl -u rp-server -f
systemctl restart rp-server
```

### Environment Variables (`/etc/default/rp-server`)

| Variable | Meaning |
|----------|---------|
| `RP_HOST` / `RP_PORT` | Listen address (default `0.0.0.0:8765`) |
| `RP_LOG_LEVEL` | Logging level |
| `RP_MOCK` | Force mock mode (DO NOT set in production) |

### Config Notes (`config/server.yaml`)

- `server.mock`: must be `false` in production
- `hardware.required`: default `["motors", "imu"]`

### Self-Check

- [ ] WS receives `+CONN` and `@IMU`/`@BAT`
- [ ] After reboot: `systemctl is-active rp-server` → `active`

---

## RDK X5 (D-Robotics) Deployment

X5 uses ROS 2 colcon workspace under `~/atom01_deploy`. Use source install:

```bash
sudo bash scripts/install_systemd.sh \
     --robot-config ~/atom01_deploy/src/roboto-inference/config/robot/robot.yaml
```

- Symlink pybind modules into `dist-packages`
- X5 has no BMS — `hardware.required: ["motors", "imu"]`
- For `python3-evdev` use the official deb — do NOT pip install
- rp_server and `start_robot.sh` compete for CAN bus — only one at a time

---

## Install (deb)

```bash
dpkg-buildpackage -us -uc -b
sudo dpkg -i ../roboparty-rp-server_*.deb
```

---

## License

GPL-3.0 — Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman) / wentywenty (https://github.com/wentywenty)
