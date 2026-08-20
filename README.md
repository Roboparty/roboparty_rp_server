# RoboParty RP Server

AT protocol gateway for RK3588. WebSocket / UDP / Serial / Bluetooth transport.

> **Frontend UI moved to [Roboparty/roboparty_example](https://github.com/Roboparty/roboparty_example)**

---

## Architecture

```
transport/   WebSocket / Serial / Bluetooth / UDP     ← four transport channels
protocol/    AT parsing + dispatch                    ← core abstraction
drivers/     motors / imu / joy / policy              ← hardware drivers
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
| `@IMU w x y z gx gy gz ax ay az temp` | 50Hz | Attitude |
| `@BAT V A SoC temp` | 50Hz | Battery |
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

### Install

Install the deb package (see [Install (deb)](#install-deb) below). Its `postinst`
enables and starts `rp-server.service` and `rp-btwifi.service` automatically.

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

X5 uses ROS 2 colcon workspace under `~/atom01_deploy`. Point `RP_ROBOT_CONFIG`
(in `/etc/default/rp-server`) at the workspace config, then install the deb
package.

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

## Logging

The server writes both file logs and console output for production troubleshooting.

### Log files

| File | Purpose |
|------|---------|
| `rp_server.log` | Main log (system, errors, connection state) |
| `packets.log` | Packet log (raw data received over UDP/WebSocket) |

### Startup arguments

```bash
python3 -m rp_server --config config/server.yaml --mock --log-level DEBUG --log-dir logs
```

| Argument | Description | Default |
|----------|-------------|---------|
| `--log-level` | Log level | `INFO` |
| `--log-dir` | Log file directory | `logs` |

### Configuration

Configure logging in `config/server.yaml`:

```yaml
logging:
  level: "INFO"           # DEBUG/INFO/WARNING/ERROR/CRITICAL
  dir: "logs"             # log file directory
  file: "rp_server.log"   # main log file
  packet_file: "packets.log"  # packet log file
  max_size: 10485760      # max file size (bytes), 10MB
  backup_count: 5         # number of backups kept
```

**Priority**: command-line arguments > config file > defaults.

### Log levels

| Level | Use |
|-------|-----|
| `DEBUG` | Detailed debugging (AT commands, UDP packets) |
| `INFO` | Normal operation (connections, service status) |
| `WARNING` | Warnings (hardware anomalies, failed commands) |
| `ERROR` | Errors (hardware init failure, degraded service) |
| `CRITICAL` | Severe errors (service cannot start) |

### Sample output

System lifecycle:

```text
2026-08-08 10:00:00 [rp_server] INFO 日志系统初始化完成 level=INFO dir=logs file=rp_server.log
2026-08-08 10:00:01 [rp_server.transport] INFO mock: skipping hardware driver init
2026-08-08 10:00:01 [rp_server.transport] INFO rp_server ready mock=True port_cfg={'host': '0.0.0.0', 'port': 9000}
```

Connection management:

```text
2026-08-08 10:01:00 [rp_server.transport] INFO WebSocket 连接建立: 192.168.1.100
2026-08-08 10:01:05 [rp_server.transport] INFO WebSocket 连接断开: 192.168.1.100 (时长: 5.0s)
2026-08-08 10:02:00 [rp_server.udp] INFO UDP listener ready on 10.43.21.32:9000
```

AT commands (DEBUG level):

```text
2026-08-08 10:01:02 [rp_server.transport] DEBUG WebSocket 收到命令: AT+BTN=a,down,1 (来源: 192.168.1.100)
2026-08-08 10:01:02 [rp_server.protocol] DEBUG AT 命令分发: AT+BTN (参数: ['a', 'down', '1'])
2026-08-08 10:01:03 [rp_server.transport] DEBUG UDP 数据包接收: 128 字节 (来源: 192.168.1.100:54321)
```

Hardware status:

```text
2026-08-08 10:00:01 [rp_server.drivers.motors] INFO motors initialised: 4
2026-08-08 10:00:01 [rp_server.drivers.imu] INFO IMU initialised
2026-08-08 10:05:00 [rp_server.drivers.motors] WARNING motor_mit_cmd[0] failed: timeout
```

Packet log (`packets.log`):

```text
2026-08-08 10:01:02 [rp_server.packets] WS_RECV src=192.168.1.100 data=AT+BTN=a,down,1
2026-08-08 10:01:03 [rp_server.packets] WS_RECV src=192.168.1.100 data=AT+JOY=lx,0.500
2026-08-08 10:02:00 [rp_server.packets] UDP_RECV src=192.168.1.100:54321 size=128 data={"type":"control","sequence":1,"left_stick_x":0.5}
2026-08-08 10:02:01 [rp_server.packets] UDP_RECV src=192.168.1.100:54321 size=96 data={"type":"control","sequence":2,"btn_a":true}
```

### Viewing logs

Live tail:

```bash
tail -f logs/rp_server.log
```

Searching:

```bash
grep "ERROR" logs/rp_server.log
grep "192.168.1.100" logs/rp_server.log
grep "AT+BTN" logs/rp_server.log
```

### Rotation

Log files rotate automatically once they reach `max_size`:

```text
logs/
├── rp_server.log        # current
├── rp_server.log.1      # previous
├── rp_server.log.2      # older
├── ...
└── rp_server.log.5      # oldest backup
```

### systemd deployment

Under systemd, logs are also written to the journal:

```bash
journalctl -u rp-server -f
tail -f /opt/roboparty/share/roboparty-rp-server/logs/rp_server.log
```

---

## License

GPL-3.0 — Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman) / wentywenty (https://github.com/wentywenty)
