# RoboParty RP Server

Unified backend on RK3588. AT protocol core; WebSocket / serial / Bluetooth transport; same-port REST for chat, QR login, MCP.

Full docs in [`docs/`](docs/):

- [Architecture & Data Flow](docs/architecture.md)
- [Product Overview](docs/product.md)
- [Deployment](docs/deploy.md)
- [Android Integration](docs/android_integration.md)
- [canutils NDK](tools/canutils-ndk/README.md)

## Quick Start (dev / mock)

```bash
# Linux / macOS
PYTHONPATH=src python3 -m rp_server --config config/dev_robot.yaml --mock --port 8765

# Windows PowerShell
$env:PYTHONPATH="src"
python -m rp_server --config config/dev_robot.yaml --mock --port 8765

python scripts/ws_selftest.py --url http://127.0.0.1:8765
```

## Architecture

```
transport/   WebSocket / Serial / Bluetooth
protocol/    AT parsing + dispatch
drivers/     motors / imu / bms / joy / policy
auth/        QR login → JWT
chat/        DeepSeek multi-turn chat
mcp/         On-board MCP tools (HTTP + optional stdio)
gamepad/     DJI/G12/evdev → AT bridge
```

## REST Overview

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/status` | Hardware snapshot |
| GET | `/auth/qr` | Create QR challenge |
| POST | `/auth/scan` | App scan confirm |
| GET | `/auth/poll` | Poll for JWT |
| POST | `/chat` | Multi-turn chat |
| GET/DELETE | `/chat/{id}` | Session query/clear |
| GET | `/mcp/tools` | MCP tool list |
| POST | `/mcp/call` | Call tool |
| WS | `/ws` | AT protocol |

## AT Protocol

Commands: `AT+CONN?` / `AT+BTN` / `AT+JOY` / `AT+SYSINFO?` / `AT+POLICY` / `AT+ERR?`
Pushes: `@IMU` `@BAT` `@ERR`

## Install (deb)

```bash
dpkg-buildpackage -us -uc -b
sudo dpkg -i ../roboparty-rp-server_*.deb
systemctl status rp-server
```

## Environment Variables

`RP_HOST` `RP_PORT` `RP_LOG_LEVEL` `RP_MOCK` `RP_JWT_SECRET` `RP_DEEPSEEK_API_KEY`

## License

GPL-3.0 — Copyright (C) 2026 wentywenty / RoboParty
