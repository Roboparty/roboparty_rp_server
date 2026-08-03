# RoboParty RP Server — 产品说明

## 产品是什么

RK3588 上的统一后端：手柄、安卓 App、头部屏、大模型网页、MCP 客户端都通过它访问机器人。

默认端口 **8765**（WebSocket + REST 同端口）。

## 谁用

| 角色 | 怎么用 |
|------|--------|
| 安卓 App（fxl） | WS AT 控键/摇杆，收 `@IMU`/`@BAT` |
| 手柄 | SDK/evdev → `scripts/gamepad_bridge.py` → AT |
| 大模型网页 | `POST /chat` 连续对话，可带机器人状态 |
| 头显/网页登录 | 扫码 `/auth/qr` → poll JWT |
| AI Agent | `GET /mcp/tools` + `POST /mcp/call` |

## 功能清单

1. AT 协议硬件网关（CONN/BTN/JOY/SYSINFO/POLICY/ERR）  
2. 遥测推送 IMU 100Hz / 电池 1Hz / 错误 10Hz  
3. Policy（ros2 inference）启停  
4. DeepSeek 多轮对话（`RP_DEEPSEEK_API_KEY`）  
5. 二维码登录 JWT  
6. 板卡 MCP 工具  
7. mock 模式（无硬件本地开发：`--mock` / `RP_MOCK=1`）

## 非目标

- 不替代电机底层固件 / BMS 守护进程  
- 不内置安卓 UI / 手柄官方 SDK 二进制（提供桥接与 stub）  
- 不在本包编译 NDK 产物（提供 `tools/canutils-ndk` 脚本）

## 版本

当前服务版本字段：`1.1.0`（见 `/health`）。
