# RoboParty RP Server

RK3588 统一后端。AT 协议核心；WebSocket / 串口 / 蓝牙传输；同端口 REST 提供 chat、扫码登录、MCP。

完整文档见 [`docs/`](docs/)：

- [架构与数据流](docs/architecture.md)
- [产品说明](docs/product.md)
- [部署](docs/deploy.md)
- [安卓联调清单](docs/android_integration.md)
- [canutils NDK](tools/canutils-ndk/README.md)

## 快速启动（开发 / mock）

```bash
# Linux / macOS
PYTHONPATH=src python3 -m rp_server --config config/dev_robot.yaml --mock --port 8765

# Windows PowerShell
$env:PYTHONPATH="src"
python -m rp_server --config config/dev_robot.yaml --mock --port 8765

python scripts/ws_selftest.py --url http://127.0.0.1:8765
```

## 架构

```
transport/   WebSocket / 串口 / 蓝牙
protocol/    AT 解析 + 分发
drivers/     motors / imu / bms / joy / policy
auth/        二维码登录 → JWT
chat/        DeepSeek 连续对话
mcp/         板卡工具（HTTP + 可选 stdio）
gamepad/     大疆/G12/evdev → AT 桥
```

## REST 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/status` | 硬件快照 |
| GET | `/auth/qr` | 创建扫码 challenge |
| POST | `/auth/scan` | App 扫码确认 |
| GET | `/auth/poll` | 轮询换 JWT |
| POST | `/chat` | 多轮对话 |
| GET/DELETE | `/chat/{id}` | 会话查询/清空 |
| GET | `/mcp/tools` | MCP 工具列表 |
| POST | `/mcp/call` | 调用工具 |
| WS | `/ws` | AT 协议 |

## AT 协议

见原 README 表格；命令：`AT+CONN?` / `AT+BTN` / `AT+JOY` / `AT+SYSINFO?` / `AT+POLICY` / `AT+ERR?`；推送：`@IMU` `@BAT` `@ERR`。

## 安装（deb）

```bash
dpkg-buildpackage -us -uc -b
sudo dpkg -i ../roboparty-rp-server_*.deb
systemctl status rp-server
```

## 环境变量

`RP_HOST` `RP_PORT` `RP_LOG_LEVEL` `RP_MOCK` `RP_JWT_SECRET` `RP_DEEPSEEK_API_KEY`

## License

GPL-3.0 — Copyright (C) 2026 wentywenty / RoboParty
