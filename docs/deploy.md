# Production Deployment

## Prerequisites

- Real robot config exists at
  `/opt/roboparty/share/roboto-inference/config/robot/robot.yaml`
- `motors_py`, `imu_py`, `bms_py` installed by RoboParty hardware package
- Board has `python3-pip` and can reach Python package sources
- `.env` contains a random `RP_JWT_SECRET`

Production service does NOT auto-fallback to mock. When motors, IMU, or BMS are disconnected,
the service still starts; `/health` returns `degraded` listing missing items. Reconnect hardware
and restart the service to re-initialize. For hardware acceptance, add `--require-hardware` to
block startup on any missing required device.

## One-shot systemd Install from Source

Stop any manually running service first, then:

```bash
cd ~/roboparty_rp_server
sudo bash scripts/install_systemd.sh
```

If real config is not at the default path:

```bash
sudo bash scripts/install_systemd.sh --robot-config /custom/path/robot.yaml
```

The installer will:

1. Validate real config and three hardware pybind modules
2. Install code to `/opt/roboparty`
3. Pin `websockets` to `10.4`, isolated in `vendor-packages`
4. Install secrets to `/etc/rp-server/rp-server.env` (mode `0600`)
5. Install and enable `rp-server.service`
6. Check service and `/health`

## Service Management

```bash
systemctl status rp-server
journalctl -u rp-server -f
systemctl restart rp-server
```

Once enabled, the service survives SSH/serial terminal close and auto-starts on boot.

## Environment Variables (`/etc/default/rp-server`)

| Variable | Meaning |
|----------|---------|
| `RP_HOST` / `RP_PORT` | Listen address, default `0.0.0.0:8765` |
| `RP_LOG_LEVEL` | Logging level (`INFO` / `DEBUG`) |
| `RP_MOCK` | Force mock mode (DO NOT set in production) |
| `RP_JWT_SECRET` | HS256 signing key |

Secrets go in `/etc/rp-server/rp-server.env` — never commit to Git. Production systemd unit
does NOT set `RP_MOCK`, so real drivers are used; when hardware is missing the service
continues in degraded state, still serving web UI and login services.

## Dev Startup

```bash
PYTHONPATH=src RP_MOCK=1 python3 -m rp_server --config config/dev_robot.yaml --mock
```

## Config Notes (`config/server.yaml`)

- `server.mock`: must be `false` in production
- `hardware.required`: default `motors/imu/bms`
- `hardware.fail_startup_if_unavailable`: systemd enforces `true` via CLI
- `auth.require_token`: recommend `true` for release

## Self-Check Checklist

- [ ] WS receives `+CONN` and `@IMU`/`@BAT`
- [ ] Web UI still accessible after closing SSH
- [ ] After board reboot: `systemctl is-active rp-server` → `active`
- [ ] Production `RP_JWT_SECRET` is set
- [ ] apt repo version matches docs (align with fanxiaobing's CI)

## RDK X5 (D-Robotics) Deployment Notes

X5 does not have `roboparty-base/motors/imu/bms/inference` deb packages. The hardware stack is
a ROS 2 colcon workspace under `~/atom01_deploy`, so **DO NOT use deb install**. Use
`scripts/install_systemd.sh` to install from source.

1. Pybind modules are not on system python path — symlink into `dist-packages`:
   ```bash
   sudo ln -s ~/atom01_deploy/install/motors_py/lib/python3.*/site-packages/motors_py* \
              /usr/lib/python3/dist-packages/
   ```

2. `robot.yaml` path differs — pass explicitly during install:
   ```bash
   sudo bash scripts/install_systemd.sh \
        --robot-config ~/atom01_deploy/src/roboto-inference/config/robot/robot.yaml
   ```

3. X5 has no BMS (no `bms_py` module, no BMS hardware). Change `config/server.yaml`
   `hardware.required` to `["motors", "imu"]`, otherwise preflight fails.
   `/health` will report `bms:false`, `battery` as `null`.

4. When board has no internet: fetch arm64 deps on a connected machine, then copy to
   board for offline install:
   ```bash
   # On connected machine
   apt download python3-fastapi python3-uvicorn python3-yaml python3-psutil
   # Copy .deb files to board, then:
   sudo dpkg -i *.deb
   ```

   For `python3-evdev` use the official deb — do NOT pip install the evdev source package.
   Ubuntu 22.04's setuptools cannot parse its pyproject metadata and will install it as an
   unimportable `UNKNOWN` package.

5. rp_server and `~/atom01_deploy/tools/start_robot.sh` (inference_node) compete for
   the same CAN bus — only one can run at a time.
