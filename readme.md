# RoboParty RP Server

Unified backend on RK3588. AT protocol core; WebSocket / serial / Bluetooth / UDP transport; same-port REST for QR login.

---

## Architecture

```
transport/   WebSocket / Serial / Bluetooth / UDP     ← swappable transports
protocol/    AT parsing + AtHandler dispatch          ← core abstraction
drivers/     motors / imu / bms / joy / policy        ← hardware
auth/        QR login → JWT
gamepad/     DJI/G12/evdev → AT bridge
```

### Data Flow

```
App手柄 ──UDP:9000──┐
Web页面 ──WS:8765───┤
手机App ──WS:8765───┼──→ AtHandler ──→ 5 drivers ──→ Hardware
串口设备 ──UART─────┤
蓝牙设备 ──RFCOMM───┘
```

### Gamepad Pipeline

```
DJI/G12/evdev → gamepad bridge → AT+BTN/JOY → WS → JoyDriver(uinput) → inference/motors
```

---

## REST API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/status` | Hardware snapshot |
| GET | `/sysinfo` | CPU/memory/load |
| GET | `/auth/qr` | Create QR challenge |
| POST | `/auth/scan` | App scan confirm |
| GET | `/auth/poll` | Poll for JWT |
| WS | `/ws` | AT protocol |
| GET | `/` | Web console |
| GET | `/control` | Virtual gamepad |
| GET | `/demo` | Demo page |
| GET | `/full` | Full-page dashboard |

---

## AT Protocol

**Commands:**

| Command | Params | Description |
|---------|--------|-------------|
| `AT+CONN?` | none | Query connection status |
| `AT+BTN=<name>,<state>,<id>` | name:a/b/x/y/lb/rb, state:up/down, id:seq | Button event |
| `AT+JOY=<axis>,<value>` | axis:lx/ly/rx/ry, value:-1.0~1.0 | Joystick axis |
| `AT+SYSINFO?` | none | CPU/memory/load |
| `AT+POLICY?` | none | Inference policy status |
| `AT+POLICY=<name>,start\|stop` | name:policy name | Start/stop inference |
| `AT+ERR?` | none | Motor error codes |
| `AT+RESET` | none | Emergency stop: zero joystick + clear errors + stop policy |

**Pushes (server → client, auto-broadcast):**

| Format | Rate | Content |
|--------|------|---------|
| `@IMU w x y z gx gy gz ax ay az temp` | 100Hz | Attitude data |
| `@BAT V A SoC temp` | 1Hz | Battery data |
| `@ERR id code name` | 10Hz | Motor errors |

### Control Mapping

| Direction | AT Command | Joystick | Effect |
|-----------|-----------|----------|--------|
| Forward | `AT+JOY=ry,-1` | Right stick ↑ | Robot moves forward |
| Backward | `AT+JOY=ry,1` | Right stick ↓ | Robot moves backward |
| Left turn | `AT+JOY=rx,-1` | Right stick ← | Robot turns left |
| Right turn | `AT+JOY=rx,1` | Right stick → | Robot turns right |

### Operation Sequence

```
X key (enable) → A key (reset) → B key (inference start) → send joystick → robot moves
```

---

## Quick Start (dev / mock)

```bash
# Linux / macOS
PYTHONPATH=src python3 -m rp_server --mock --port 8765

# Windows PowerShell
$env:PYTHONPATH="src"
python -m rp_server --mock --port 8765
```

---

## Production Deployment

### Prerequisites

- Real robot config at `/opt/roboparty/share/roboto-inference/config/robot/robot.yaml`
- `motors_py`, `imu_py`, `bms_py` installed by RoboParty hardware package
- Board has `python3-pip` and can reach Python package sources
- `.env` contains a random `RP_JWT_SECRET`

### Install systemd from source

```bash
cd ~/roboparty_rp_server
sudo bash scripts/install_systemd.sh
```

With custom robot config:

```bash
sudo bash scripts/install_systemd.sh --robot-config /custom/path/robot.yaml
```

The installer will:
1. Validate real config and hardware pybind modules
2. Install code to `/opt/roboparty`
3. Pin `websockets` to `10.4`, isolated in `vendor-packages`
4. Install secrets to `/etc/rp-server/rp-server.env` (mode `0600`)
5. Install and enable `rp-server.service`
6. Check service and `/health`

### Service Management

```bash
systemctl status rp-server
journalctl -u rp-server -f
systemctl restart rp-server
```

### Environment Variables (`/etc/default/rp-server`)

| Variable | Meaning |
|----------|---------|
| `RP_HOST` / `RP_PORT` | Listen address, default `0.0.0.0:8765` |
| `RP_LOG_LEVEL` | Logging level (`INFO` / `DEBUG`) |
| `RP_MOCK` | Force mock mode (DO NOT set in production) |
| `RP_JWT_SECRET` | HS256 signing key |

### Config Notes (`config/server.yaml`)

- `server.mock`: must be `false` in production
- `hardware.required`: default `motors/imu/bms`
- `hardware.fail_startup_if_unavailable`: systemd enforces `true` via CLI
- `auth.require_token`: recommend `true` for release

### Self-Check

- [ ] WS receives `+CONN` and `@IMU`/`@BAT`
- [ ] Web UI still accessible after closing SSH
- [ ] After board reboot: `systemctl is-active rp-server` → `active`
- [ ] Production `RP_JWT_SECRET` is set

---

## RDK X5 (D-Robotics) Deployment

X5 does not have `roboparty-base/motors/imu/bms/inference` deb packages. The hardware stack is
a ROS 2 colcon workspace under `~/atom01_deploy`. **DO NOT use deb install** — use source install.

1. Symlink pybind modules:
   ```bash
   sudo ln -s ~/atom01_deploy/install/motors_py/lib/python3.*/site-packages/motors_py* \
              /usr/lib/python3/dist-packages/
   ```

2. Pass robot config explicitly:
   ```bash
   sudo bash scripts/install_systemd.sh \
        --robot-config ~/atom01_deploy/src/roboto-inference/config/robot/robot.yaml
   ```

3. X5 has no BMS — change `hardware.required` to `["motors", "imu"]`.

4. For `python3-evdev` use the official deb — do NOT pip install.

5. rp_server and `start_robot.sh` (inference_node) compete for the same CAN bus — only one at a time.

---

## Inference Node Config

```
joy_node:    device_id=1 (virtual gamepad js1)
Policy models:
  ├── policy.onnx       default walking
  ├── policy_wave.onnx  wave
  ├── policy_dance.onnx dance
  └── policy_punch.onnx punch

Controls: right stick for movement + LT/RT for turning
Keys: X=enable  A=reset  B=inference  Y=toggle mode  LB=switch policy  RB=switch action
```

---

## Board Info

| Item | Value |
|------|-------|
| IP | `10.43.19.133` |
| SSH | `ssh sunrise@10.43.19.133` |
| ROS2 workspace | `~/atom01_deploy` |
| Battery socket | `/tmp/gf_bms.sock` |
| Inference log | `/tmp/infer.log` |

---

## Install (deb)

```bash
dpkg-buildpackage -us -uc -b
sudo dpkg -i ../roboparty-rp-server_*.deb
systemctl status rp-server
```

---

## License

GPL-3.0 — Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman) / wentywenty (https://github.com/wentywenty)
