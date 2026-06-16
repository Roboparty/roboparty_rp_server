# RoboParty RP Server

RK3588 统一后端服务。WebSocket AT 协议 + REST API，为手柄、Android App、头部显示屏、MCP、算力背包等前端提供统一接口。

## 技术栈

| 层级 | 选型 |
|------|------|
| Web 框架 | FastAPI + uvicorn（asyncio） |
| 通信 | WebSocket（AT 协议） + REST |
| 硬件绑定 | motors_py / imu_py / bms_py（pybind11） |
| 虚拟手柄 | evdev uinput（`/dev/input/eventX`） |
| 策略管理 | subprocess → ros2 launch inference_node |
| 平台 | RK3588 / Ubuntu 22.04 arm64 |

## 架构

```
 手柄 / App / MCP ──WebSocket──▶ rp_server ◀── pybind ── motors / IMU / BMS
                                      │
                                      ├─ uinput ──▶ /dev/input/eventX ──▶ ROS joy node
                                      │
                                      └─ subprocess ──▶ ros2 inference_node
```

- **遥测**：服务端直接通过 pybind 读电机/IMU/BMS，WebSocket 推送
- **控制**：AT 命令 → uinput 虚拟手柄 → ROS 节点标准输入路径
- **策略**：服务端管理 ros2 推理进程的生命周期，不做内嵌推理

## 需求矩阵

| ID | FR | 需求 | 状态 |
|---|-----|------|:--:|
| 1 | FR-01 | 自动识别与连接 | ✅ |
| 2 | FR-02 | 断开检测 | ✅ |
| 3 | FR-03 | 数字按键 | ✅ |
| 4 | FR-04 | 摇杆输入 | ✅ |
| 5 | FR-09 | 系统资源监控 | ✅ |
| 6 | FR-10 | 机器人主控脚本管理 | ✅ |
| 7 | FR-11 | Policy 状态显示 | ✅ |
| 8 | FR-12 | 电机错误码解析 | ✅ |
| 9 | FR-13 | IMU 数据可视化 | ✅ |

## AT 协议

WebSocket 端点：`ws://<rk3588>:8765/ws`

### 命令（Client → Server）

| ID | 命令 | 说明 |
|---|------|------|
| 1 | `AT+CONN?` | 查询连接状态 |
| 2 | `AT+CONN?` | 同上（WebSocket 断连自动检测） |
| 3 | `AT+BTN=<name>,<state>,<id>` | 按键：name 见下表，state=`up`/`down` |
| 4 | `AT+JOY=<axis>,<value>` | 摇杆：axis=`lx`/`ly`/`rx`/`ry`/`lt`/`rt`，value=`-1.0~1.0` |
| 5 | `AT+SYSINFO?` | 查询系统资源（CPU/内存/loadavg） |
| 6 | `AT+POLICY=<name>,<action>` | action=`start` 启动推理，`stop` 停止 |
| 7 | `AT+POLICY?` | 查询推理状态 |
| 8 | `AT+ERR?` | 查询所有电机错误码 |

### 按键映射（FR-03）

| 名称 | uinput 事件 | 说明 |
|------|------------|------|
| `a` / `b` / `x` / `y` | `BTN_SOUTH` / `EAST` / `NORTH` / `WEST` | 面板键 |
| `lb` / `rb` | `BTN_TL` / `BTN_TR` | 肩键 |
| `ltb` / `rtb` | `BTN_TL2` / `BTN_TR2` | 扳机键 |
| `ls` / `rs` | `BTN_THUMBL` / `BTN_THUMBR` | 摇杆按下 |
| `du` / `dd` / `dl` / `dr` | `BTN_DPAD_*` | 方向键 |
| `start` / `select` / `mode` | `BTN_START` / `BTN_SELECT` / `BTN_MODE` | 功能键 |
| `btn_0` … `btn_15` | `BTN_TRIGGER_HAPPY1` … | 通用数字按键 |

### 摇杆映射（FR-04）

| axis | uinput 轴 |
|------|----------|
| `lx` / `ly` | `ABS_X` / `ABS_Y`（左摇杆） |
| `rx` / `ry` | `ABS_RX` / `ABS_RY`（右摇杆） |
| `lt` / `rt` | `ABS_Z` / `ABS_RZ`（扳机轴） |

### 响应（Server → Client）

| 命令 | 响应格式 |
|------|---------|
| `AT+CONN?` | `+CONN: <hw>,<state>` |
| `AT+BTN` | `+BTN_RSP=<id>,<status>[,<ts>]` |
| `AT+SYSINFO?` | `+SYSINFO: <cpu%>,<mem%>,load=<loadavg>` |
| `AT+POLICY=<name>,<action>` | `+POLICY: <name>,<state>` |
| `AT+POLICY?` | `+POLICY: <name>,<state>` |
| `AT+ERR?` | `+ERR: <id>,0x<code>,<name>`（无错误时 `+ERR: none`） |

### 推送（Server → Client，无需请求）

| 格式 | 频率 | 内容 |
|------|:--:|------|
| `@IMU <w> <x> <y> <z> <gx> <gy> <gz> <ax> <ay> <az> <t>` | 100 Hz | 四元数、角速度(rad/s)、线加速度(m/s²)、温度(°C) |
| `@BAT <V> <A> <SoC> <temp>` | 1 Hz | 电压(V)、电流(A)、电量(%)、温度(°C) |
| `@ERR <id> 0x<code> <name>` | 10 Hz | 电机错误实时告警（有错误时才推） |

### 连接流程

```
client → ws://<rk3588>:8765/ws
server → +CONN: OK,CONNECTED          # 握手自动发送
client → AT+CONN?                      # 可选确认
server → +CONN: OK,CONNECTED
# 服务端开始自动推送 @IMU @BAT @ERR
```

## REST API

| 方法 | 路径 | 返回 |
|------|------|------|
| `GET` | `/health` | `{"status":"ok","hw_ready":true}` |
| `GET` | `/sysinfo` | `{"cpu":12.3,"mem":45.6}` |
| `GET` | `/api/status` | 机器人完整快照：电机错误、BMS、IMU、Policy 状态、虚拟手柄路径 |

## 配置

rp_server 不维护独立的机器人配置文件，直接复用 `roboparty-inference` 的配置。

| 配置文件 | 路径 | 来源 |
|---------|------|------|
| 机器人（电机/IMU） | `/opt/roboparty/share/roboparty-inference/config/robot/robot.yaml` | `roboparty-inference` |
| 推理参数 | `/opt/roboparty/share/roboparty-inference/config/inference/` | `roboparty-inference` |
| 服务器 | `/opt/roboparty/share/roboparty-rp-server/config/server.yaml` | `roboparty-rp-server` |

`server.yaml` 只包含服务器特有项：

```yaml
server:
  host: "0.0.0.0"
  port: 8765

bms:
  bms_type: "TWS"
  socket_path: "/tmp/bms.sock"

telemetry:
  imu_hz: 100
  battery_hz: 1
  error_hz: 10
```

环境变量可覆盖：
- `RP_ROBOT_CONFIG` — 机器人配置文件路径
- `RP_SERVER_CONFIG` — 服务器配置文件路径
- `RP_HOST` / `RP_PORT` / `RP_LOG_LEVEL` — 运行时参数

## 安装

```bash
# 构建 deb
dpkg-buildpackage -us -uc -b
sudo dpkg -i ../roboparty-rp-server_*.deb

# 安装后自动 pip install -r requirements.txt（由 postinst 执行）
```

### 启动

deb 安装后自动 enable + start，无需手动操作。

```bash
# 手动管理
systemctl status rp-server
systemctl restart rp-server

# 查看日志
journalctl -u rp-server -f

# 开发模式（从源码目录）
python3 -m rp_server --config ../roboparty_inference/config/robot.yaml --port 8765
```

## 文件结构

```
roboparty_rp_server/
├── config/robot.yaml              # 机器人配置
├── rp-server-start.sh             # 启动脚本 → /opt/roboparty/bin/
├── requirements.txt               # Python 依赖
├── src/rp_server/
│   ├── app.py                     # FastAPI + WebSocket + AT 分发
│   ├── at_parser.py               # AT 协议解析/序列化
│   ├── error_codes.py             # DM/EVO/LRO/XYN 错误码表
│   ├── joy_bridge.py              # uinput 虚拟手柄
│   ├── monitors.py                # 后台推送：IMU/BMS/错误
│   └── robot.py                   # 硬件管理（motors/imu/bms）
├── debian/                        # Debian 打包
└── .github/                       # CI/CD（build-deb.yml）
```

## 依赖

| 类型 | 包名 |
|------|------|
| RoboParty | roboparty-base, roboparty-motors, roboparty-imu, roboparty-bms, roboparty-inference |
| 系统 | python3, python3-pip, python3-yaml, python3-psutil |
| PyPI | fastapi, uvicorn, websockets, PyYAML, psutil, evdev |

## License

GPL-3.0 — Copyright (C) 2026 wentywenty
