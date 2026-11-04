# RoboParty RP Server

Protobuf (`roboparty.v1`) gateway for RK3588 with authenticated WebSocket control.
Legacy UDP / Serial / Bluetooth and direct CAN gamepad implementations remain
in source but cannot be enabled until they support shared control ownership.

> **Frontend UI moved to [Roboparty/roboparty_example](https://github.com/Roboparty/roboparty_example)**

---

## Architecture

```
proto/       roboparty.v1 contract (source of truth)   ← IDL
protocol/    generated bindings + codec + handler      ← core abstraction
transport/   WebSocket / Serial / Bluetooth / UDP      ← four transport channels
drivers/     motors / imu / joy / policy               ← hardware drivers
```

### Data Flow

```
App / native clients -> WS authentication -> control lease -> CommandHandler -> drivers
```

Every message is a `roboparty.v1.Envelope`. Bindings are generated from
`proto/` via `scripts/gen_proto.sh` (requires `python3-protobuf` 4.21.12 on the
board, `grpcio-tools` on the build host). The generated bindings under
`src/rp_server/protocol/gen/` are committed; CI
(`.github/workflows/proto.yml`) regenerates them and fails on drift.

---

## REST API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check + hardware status |
| GET | `/identity` | Public robot identity: `serial`, `model`, `machineId` (SN/model from TUI), plus the Ed25519 device key's `spkiSha256`/`devicePublicKey` (cached 60s) |
| GET | `/api/status` | Full hardware snapshot |
| GET | `/sysinfo` | CPU / memory / load |
| WS | `/ws` | Bearer authentication; protobuf binary commands and JSON lease management |
| WS | `/ws-json` | App JSON control/telemetry; app-key challenge + JWT; v2 requires WSS |

### Pairing (v2 URI / TLS pin)

- On the robot: `rp-server-pair code` → 6-digit code plus a
  `roboparty://pair?data=...` URI containing `tlsSpkiSha256`,
  `deviceSpkiSha256`, SN and a device-key signature (TTL 5 min, localhost only).
- App: Settings → 授权与绑定 → paste the URI (or scan its QR) → save the TLS
  pin locally → `POST /pair/register` with `{code, appPublicKey, deviceName}`.
- v2 clients reject trust-all, skip-hostname-verification and plaintext control.
- Registered keys live in `/etc/rp-server/auth/apps.json` (0600):
  `rp-server-pair list` / `rp-server-pair revoke <appKeyId>`.
- `POST /pair/code`, `GET /pair/apps`, `POST /pair/revoke` are localhost-only;
  `POST /pair/register` is LAN-facing but requires the code and is rate-limited.

### WSS / JSON app gateway

- `/ws-json` keeps the app's existing JSON packet shapes and translates them to
  `Envelope` internally.
  `left_stick_x/y` is mirrored onto `AXIS_RX/RY` when the right stick is centered,
  so the app's primary touch stick drives translation.
- Auth: `auth_request` (`device_id` = paired `appKeyId`) → `challenge` →
  `challenge_response` (ECDSA/Ed25519 signature over `<appKeyId>:<challenge>`) →
  `auth_result` with a short-lived JWT (EdDSA, scopes `read control`).
- `tls.enabled: true` runs uvicorn with `ssl_certfile`/`ssl_keyfile`. Generate a
  self-signed cert with `rp-server-gen-tls` (installed from
  `scripts/rp-server-gen-tls`); `/identity.tlsSpkiSha256` is the pin value.
- Android and MCP clients support explicit lease acquisition. Old clients must
  migrate before sending commands. UDP is disabled, including telemetry.

### Shared access and control ownership

- HTTP routes require `Authorization: Bearer <token>`: `read` for GET/HEAD and
  `admin` for writes. `/health` and `/identity` are public; pairing endpoints
  retain their local-operator/one-time-code checks. Forwarded client addresses
  are disabled in the bundled server entrypoint.
- `/ws` requires the same Bearer header at connection time. Use a paired App JWT
  or configure a random `RP_SERVICE_TOKEN` of at least 32 characters in the
  protected service environment. Native clients use the same token. Default
  `auth.service_scopes` are `[read, control, admin]` so the local MCP service can
  use `reset`; drop `admin` when it is not needed. Never put tokens in URLs. Use
  TLS for network deployment.
- `/ws-json` retains its signed challenge. Tokens are session-bound; expiry,
  pairing revocation and reduced local permissions are rechecked during sessions.
- After authentication, send text JSON `{"type":"lease.acquire"}`. Both WS
  endpoints reply `{"type":"lease","status":"acquired","ttl_ms":3000,
  "input_timeout_ms":500}`. A competing session receives `CONTROL_BUSY`.
- Send `{"type":"heartbeat"}` to renew ownership TTL. Control/joystick/button
  frames must independently stay fresh once input starts. Heartbeats alone do
  not keep stale input active. Use `{"type":"lease.release"}` to release.
- Timeout, disconnect and credential loss revoke ownership, zero the virtual
  gamepad and stop only the policy process managed by this service. No motor
  error clearing occurs. Clients must explicitly acquire again; reconnect alone
  never resumes control. This is a software action, not proof of hardware stop.
- JSON `stop {status:"request"}` and protobuf `StopRequest` require `control`,
  may stop another owner, and latch the software stop. While latched, new leases
  are rejected with `CONTROL_STOPPED`; clear it with `stop {status:"clear"}`
  (or `StopRequest.status="clear"`) and acquire control again. Protobuf policy
  STOP is a policy-only stop and does not latch. Administrative protobuf `reset`
  still clears errors and requires `admin` plus ownership; it is not an
  emergency-stop command.
- Legacy `transports.udp/serial/bluetooth` and `can_gamepad.enabled` must be false.
  Enabling them fails startup rather than providing an unleased control bypass.

The changes have offline mock tests; they have not been deployed to a robot.

### Device identity key

`/identity` also exposes the robot's Ed25519 public key:

- `spkiSha256`: SHA-256 of the DER SubjectPublicKeyInfo (pin this in the app)
- `devicePublicKey`: base64 DER SPKI
- `deviceKeySource`: key path, or `unavailable`

The private key lives at `/etc/rp-server/auth/device.key` (0600), generated on
first start. Provision one key per board; never commit it. If the key cannot be
read/generated, the fields are `null` and clients should treat identity as
degraded.

### Board management backend (`robopi-tui`)

rp_server proxies the `robopi-tui` public JSON-RPC protocol
(`robopi-tui rpc --protocol 1`). Motion and telemetry remain in rp_server;
only board snapshots/tasks are delegated. The Debian package depends on
`robopi-tui (>= 1.1.2)`; since 1.1.2 the TUI is `Architecture: all`, so the
same package installs on arm64 boards and x86 hosts (only `generic` plugins
are listed on non-arm64).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/tui/health` | Backend availability and job policy |
| GET | `/tui/tasks` | `tasks.list` (packages-check / apt-upgrade / hpm-flash / can-check / pipeline) |
| GET | `/tui/tasks/{id}` | `tasks.describe` |
| GET | `/tui/snapshot` | `snapshot.get` (read-only board snapshot) |
| GET | `/tui/jobs` | `jobs.list` |
| GET | `/tui/jobs/active` | `jobs.active` |
| GET | `/tui/jobs/{id}` | `jobs.get` |
| POST | `/tui/jobs` | `jobs.start` (`{"taskId","requestId"?}`; needs `tui.allow_jobs: true`) |
| POST | `/tui/jobs/{id}/acknowledge` | `jobs.acknowledge` (needs `tui.allow_jobs: true`) |

Motor errors are also delegated: `Query(WHAT_ERRORS)` over WebSocket and
`/api/status.motor_errors` call TUI's read-only `motors.get` (create drivers +
read feedback; never enable or transmit). Results are cached for
`tui.motor_cache_s` (default 2s) so polling does not spawn a TUI process each
time. If the TUI backend is disabled or fails, rp_server falls back to its
direct motor driver.

Proxied results carry a `server` field (`tui.server`, default `rp_server`,
injected as `RP_TUI_SERVER`) so clients can tell which fronting server produced
them; calling `robopi-tui` directly reports `robopi-tui`.

`tui.enabled` defaults to `true`; `tui.allow_jobs` defaults to `false` because
`apt-upgrade` and `hpm-flash` are destructive. Set `RP_TUI_BIN` or
`tui.executable` if `robopi-tui` is not on `PATH`. Reading the proxy requires
`read`; job submission/acknowledgement additionally requires `admin` and the
existing `tui.allow_jobs` gate.

---

## Protocol (`roboparty.v1`, protocol_version = 2)

Wire format is Protocol Buffers; see `proto/roboparty/v1/*.proto`. Each
transport frames one `Envelope`:

| Transport | Framing |
|-----------|---------|
| WebSocket | one `Envelope` per binary frame |
| UDP | `0x52` + version `0x01` + `Envelope` |
| Serial / Bluetooth | varint length-delimited `Envelope` stream |

**Commands (`Envelope` body):**

| Body | Description |
|------|-------------|
| `query` (`WHAT_CONN/SYSINFO/POLICY/ERRORS`) | read-only queries |
| `button` / `joystick` / `control` | gamepad input |
| `policy_command` | start/stop inference |
| `reset` | administrative reset: zero joystick + clear errors + stop policy; admin + lease |
| `skill_action` | skill request (logged) |

**Responses:** `conn`, `button_ack`, `sysinfo`, `policy_response`,
`motor_errors`, `reset_response`, `error`.

**Telemetry (auto-broadcast):** `imu` (50Hz), `battery` (50Hz),
`motors` (1Hz), `motor_error_push` (10Hz).

### Python protocol wheel (`roboparty-proto`)

`scripts/build_proto_wheel.py` packages
`src/rp_server/protocol/gen/roboparty` as
`roboparty_proto-1.0.0-py3-none-any.whl`. CI attaches it to the GitHub release
(alongside the `.deb`) so downstream clients such as the MCP server can install
the published bindings instead of vendoring a copy. The wheel version tracks
`roboparty.v1`, not the rp_server package version, so the
`releases/latest/download/...` URL stays stable.

**Legacy session (UDP, currently disabled):** `auth_request` → `challenge` → `challenge_response` →
`auth_result`, plus `heartbeat` and token-authenticated `stop`/`stop_ack`
(`status=""` request, `"received"` ack confirmation, `"clear"` release latch).

---

## Control Mapping

| Direction | Joystick input | Effect |
|-----------|----------------|--------|
| Forward | Right stick ↑ (`AXIS_RY` = -1) | Move forward |
| Backward | Right stick ↓ (`AXIS_RY` = 1) | Move backward |
| Left turn | Right stick ← (`AXIS_RX` = -1) | Turn left |
| Right turn | Right stick → (`AXIS_RX` = 1) | Turn right |

### Operation Sequence

```
X (enable) → A (reset) → B (inference) → joystick → robot moves
```

---

## Quick Start (mock mode)

```bash
scripts/dev_run.sh --mock --port 9000
```

`scripts/dev_run.sh` uses the system fastapi/pydantic 1.x and only borrows
`google.protobuf` from the user site when needed. This avoids the common local
conflict where a pip-installed pydantic 2.x shadows the Debian fastapi 0.63.

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
| `RP_HOST` / `RP_PORT` | Listen address (default `0.0.0.0:9000`) |
| `RP_LOG_LEVEL` | Logging level (CLI > env > `server.yaml`) |
| `RP_UDP_SECRET` | UDP auth shared secret (required in production) |
| `RP_STOP_SCRIPT` | Software-stop script path |
| `RP_MOCK` | Force mock mode (DO NOT set in production) |

### Config Notes (`config/server.yaml`)

- `server.mock`: must be `false` in production
- `hardware.required`: default `["motors", "imu"]`
- `robot.launch_cmd`: inference launch command. The ROS package name is
  `roboparty_inference` (underscore, not the Debian package name); `{policy}`
  is replaced by the validated `PolicyCommand.name`.

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

### Python dependencies

The Debian package declares its Python dependencies in `debian/control`
(`Depends`/`Recommends`). pip and Debian names differ, so
`scripts/check_python_depends.py` scans the source imports and verifies each
third-party module is covered:

```bash
python3 scripts/check_python_depends.py          # fail if an import is missing
python3 scripts/check_python_depends.py --list   # show import -> Debian mapping
```

If a local `~/.local` pydantic 2.x shadows the Debian fastapi 0.63, use
`scripts/dev_run.sh` for mock/dev runs; it selects pydantic 1.x and the system
protobuf-compatible path. Production/board installs should use the Debian
package and its declared dependencies.

Core mapping: `fastapi`→`python3-fastapi`, `uvicorn`→`python3-uvicorn`,
`websockets`→`python3-websockets`, `google`→`python3-protobuf`,
`yaml`→`python3-yaml`, `psutil`→`python3-psutil`, `evdev`→`python3-evdev`,
`serial_asyncio`→`python3-serial-asyncio`, `bluetooth`→`python3-bluez`
(optional, in `Recommends`). Hardware pybind modules (`motors_py`, `imu_py`) come from the
`roboparty-*` packages, not PyPI. The check runs
before `dh_auto_configure` in `debian/rules`.

---

## Logging

The server writes both file logs and console output for production troubleshooting.

### Log files

| File | Purpose |
|------|---------|
| `rp_server.log` | Main log (system, errors, connection state) |
| `packets.log` | Packet log (raw data received over UDP/WebSocket) |
| `policy.log` | inference/ros2 subprocess stdout+stderr |
| `log-spool.sqlite3` | Durable structured-event spool for log_server upload |

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

### Structured log upload

`config/server.yaml` has a `log_server` section (enabled by default) that sends
`rp_server` logger records to the local `roboparty-log-server` at
`http://127.0.0.1:8092`. Events are first written to
`<log-dir>/log-spool.sqlite3`, so an offline or restarted log server does not
lose them. `RP_LOG_SERVER_URL`, `RP_LOG_TOKEN`, `RP_LOG_DEVICE_ID`,
`RP_DEVICE_MODEL` and `RP_FIRMWARE_VERSION` override the config.

Schema v1 fields: `schema_version`, `event_type`, `session_id`, `boot_id`,
`software_version`, `firmware_version`, `device_model`, plus the existing
`event_id/device_id/service/timestamp/level/message/fields`.

### Log levels

| Level | Use |
|-------|-----|
| `DEBUG` | Detailed debugging (protocol messages, UDP packets) |
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

Protocol messages (DEBUG level):

```text
2026-08-08 10:01:02 [rp_server.transport] INFO WS_RECV src=192.168.1.100 body=button size=12
2026-08-08 10:01:02 [rp_server.protocol] DEBUG unhandled command body: none
2026-08-08 10:01:03 [rp_server.udp] INFO UDP_RECV src=192.168.1.100:54321 size=40 body=control
```

Hardware status:

```text
2026-08-08 10:00:01 [rp_server.drivers.motors] INFO motors initialised: 4
2026-08-08 10:00:01 [rp_server.drivers.imu] INFO IMU initialised
2026-08-08 10:05:00 [rp_server.drivers.motors] WARNING motor_mit_cmd[0] failed: timeout
```

Packet log (`packets.log`) — message body + byte size:

```text
2026-08-08 10:01:02 [rp_server.packets] WS_RECV src=192.168.1.100 body=button size=12
2026-08-08 10:01:03 [rp_server.packets] WS_RECV src=192.168.1.100 body=joystick size=10
2026-08-08 10:02:00 [rp_server.packets] UDP_RECV src=192.168.1.100:54321 size=40 body=control
2026-08-08 10:02:01 [rp_server.packets] UDP_RECV src=192.168.1.100:54321 size=38 body=control
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
grep "WS_RECV" logs/packets.log
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
