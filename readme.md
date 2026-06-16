# RoboParty RP Server

RK3588 统一后端服务。AT 协议核心，WebSocket / 串口 / 蓝牙三种传输，为手柄、App、头部显示屏等前端提供统一接口。

## 架构

三层设计，AT 协议是核心抽象面：

```
transport/     ── WebSocket / 串口 / 蓝牙         ← 传输层（随便换）
protocol/      ── AT 命令解析 + 分发               ← 协议层（核心，与传输无关）
drivers/       ── pybind / uinput / subprocess     ← 驱动层（5 个独立驱动）
```

```
 手柄 ──WebSocket──┐
 串口 ──UART───────┼──▶ AT handler ──┬── motors_py  ── CAN 总线
 蓝牙 ──RFCOMM─────┘                 ├── imu_py     ── 姿态传感器
                                      ├── bms_py     ── 电池
                                      ├── uinput     ── /dev/input/eventX
                                      └── subprocess ── ros2 inference_node
```

| 层级 | 文件 | 职责 |
|------|------|------|
| 传输 | `ws_server.py` / `serial_server.py` / `bt_server.py` | 收 AT 文本 → dispatch → 回响应 |
| 协议 | `at_parser.py` + `at_handler.py` | 解析/序列化 AT 帧，分发到对应驱动 |
| 驱动 | `motors.py` / `imu.py` / `bms.py` / `joy.py` / `policy.py` | 操作硬件，对协议层暴露统一接口 |

## 需求覆盖

| ID | FR | 需求 | 实现 |
|---|-----|------|------|
| 1 | FR-01 | 自动识别与连接 | AT+CONN? → +CONN |
| 2 | FR-02 | 断开检测 | 传输层自动感知 |
| 3 | FR-03 | 数字按键 | AT+BTN → uinput EV_KEY |
| 4 | FR-04 | 摇杆输入 | AT+JOY → uinput EV_ABS |
| 5 | FR-09 | 系统资源监控 | AT+SYSINFO? → CPU/内存/loadavg |
| 6 | FR-10 | 主控脚本管理 | AT+POLICY start/stop |
| 7 | FR-11 | Policy 状态 | AT+POLICY? → RUNNING/STOPPED |
| 8 | FR-12 | 电机错误码解析 | AT+ERR? + 10Hz push @ERR |
| 9 | FR-13 | IMU 数据可视化 | 100Hz push @IMU |

## 传输通道

| 通道 | 端点 | 配置 |
|------|------|------|
| WebSocket | `ws://<rk3588>:8765/ws` | 默认开 |
| 串口 | `/dev/ttyAMA0` @ 115200 | 默认关，改 `server.yaml` |
| 蓝牙 | RFCOMM channel 1 | 默认关，改 `server.yaml` |

```yaml
# server.yaml
transports:
  ws: true
  serial: false
  bluetooth: false
```

三个通道共享同一个 AT handler，行为完全一致。缺对应 Python 库时自动跳过。

### 连接流程

```
# WebSocket
client → ws://<rk3588>:8765/ws
server → +CONN: OK,CONNECTED        # 握手自动发送

# 串口
client → 打开 /dev/ttyAMA0 @ 115200
client → AT+CONN?
server → +CONN: OK,CONNECTED

# 蓝牙
client → RFCOMM connect channel 1
client → AT+CONN?
server → +CONN: OK,CONNECTED
```

## AT 协议

### 命令（Client → Server）

| ID | 命令 | 说明 |
|---|------|------|
| 1 | `AT+CONN?` | 查询连接状态 |
| 2 | `AT+CONN?` | 同上（传输层断连自动检测） |
| 3 | `AT+BTN=<name>,<state>,<id>` | 按键（state=`up`/`down`） |
| 4 | `AT+JOY=<axis>,<value>` | 摇杆（value=`-1.0~1.0`） |
| 5 | `AT+SYSINFO?` | 系统资源（CPU/内存/loadavg） |
| 6 | `AT+POLICY=<name>,<action>` | action=`start`/`stop` |
| 7 | `AT+POLICY?` | 查询推理状态 |
| 8 | `AT+ERR?` | 查询电机错误码 |

### 响应

| 命令 | 响应 |
|------|------|
| `AT+CONN?` | `+CONN: <OK\|FAIL>,<CONNECTED>` |
| `AT+BTN` | `+BTN_RSP=<id>,<status>[,<ts>]` |
| `AT+SYSINFO?` | `+SYSINFO: <cpu%>,<mem%>,load=<loadavg>` |
| `AT+POLICY <action>` | `+POLICY: <name>,<RUNNING\|STOPPED\|FAIL>` |
| `AT+ERR?` | `+ERR: <id>,0x<code>,<DM_...\|EVO_...>`，无错误 `+ERR: none` |

### 推送（Server → Client，自动广播）

| 格式 | 频率 | 内容 |
|------|:--:|------|
| `@IMU <w> <x> <y> <z> <gx> <gy> <gz> <ax> <ay> <az> <t>` | 100 Hz | 四元数、角速度、线加速度、温度 |
| `@BAT <V> <A> <SoC> <temp>` | 1 Hz | 电压 V、电流 A、电量 %、温度 °C |
| `@ERR <id> 0x<code> <name>` | 10 Hz | 电机错误实时告警 |

### 错误码

前缀区分品牌：`DM_` / `EVO_` / `LRO_` / `XYN_`。

| 前缀 | 关键错误 |
|------|---------|
| `DM_` | OVER_VOLT, UNDER_VOLT, OVER_CURRENT, MOS_OVER_TEMP, COIL_OVER_TEMP, LOST_CONN, OVER_LOAD |
| `EVO_` | OVER_VOLTAGE, UNDER_VOLTAGE, PHASE_X_OVER_CURRENT, PCB_OVER_TEMP, COIL_OVER_TEMP, ENCODER_ERROR, STALL_PROTECTION, CAN_COMM_LOST |
| `LRO_` | MOTOR_OVERHEAT, OVER_CURRENT, UNDER_VOLTAGE, ENCODER_ERROR, BRAKE_OVERVOLT, DRV_ERROR |
| `XYN_` | OVER_VOLTAGE, OVER_CURRENT, MOTOR_OVER_TEMP, BOARD_OVER_TEMP, UNDER_VOLTAGE, ENCODER_FAULT, COMM_FAULT |

完整列表见 `error_codes.py`。

### 按键 / 摇杆映射

| 按键 | uinput |
|------|--------|
| `a` `b` `x` `y` | BTN_SOUTH / EAST / NORTH / WEST |
| `lb` `rb` `ltb` `rtb` | BTN_TL / TR / TL2 / TR2 |
| `du` `dd` `dl` `dr` | BTN_DPAD_* |
| `start` `select` `mode` | BTN_START / SELECT / MODE |
| `btn_0` … `btn_15` | BTN_TRIGGER_HAPPY1 … |

| 轴 | uinput |
|------|--------|
| `lx` `ly` | ABS_X / ABS_Y |
| `rx` `ry` | ABS_RX / ABS_RY |
| `lt` `rt` | ABS_Z / ABS_RZ |

## REST API

| 方法 | 路径 | 返回 |
|------|------|------|
| `GET` | `/health` | `{"status":"ok","hw_ready":true}` |
| `GET` | `/sysinfo` | `{"cpu":...,"mem":...}` |
| `GET` | `/api/status` | 电机/IMU/BMS/Policy/手柄 完整快照 |

## 配置

| 文件 | 路径 | 来源 |
|------|------|------|
| 机器人 | `/opt/roboparty/share/roboparty-inference/config/robot/robot.yaml` | roboparty-inference |
| 推理 | `/opt/roboparty/share/roboparty-inference/config/inference/` | roboparty-inference |
| 服务器 | `/opt/roboparty/share/roboparty-rp-server/config/server.yaml` | roboparty-rp-server |

```yaml
# server.yaml — 仅服务器特有配置
transports:
  ws: true
  serial: false
  bluetooth: false

server:
  host: "0.0.0.0"
  port: 8765

serial:
  port: "/dev/ttyAMA0"
  baudrate: 115200

bluetooth:
  channel: 1

bms:
  bms_type: "TWS"
  socket_path: "/tmp/bms.sock"

telemetry:
  imu_hz: 100
  battery_hz: 1
  error_hz: 10
```

环境变量 `/etc/default/rp-server`：`RP_HOST` / `RP_PORT` / `RP_LOG_LEVEL`

## 文件结构

```
roboparty_rp_server/
├── etc/
│   ├── default/rp-server                   → /etc/default/rp-server
│   └── systemd/system/rp-server.service    → /etc/systemd/system/
├── config/server.yaml                      → /opt/roboparty/share/roboparty-rp-server/config/
├── src/rp_server/
│   ├── transport/
│   │   ├── ws_server.py                    # FastAPI + WebSocket
│   │   ├── serial_server.py                # 串口 AT 传输
│   │   └── bt_server.py                    # 蓝牙 AT 传输
│   ├── protocol/
│   │   ├── at_parser.py                    # AT 帧解析/序列化
│   │   └── at_handler.py                   # AT 命令分发
│   ├── drivers/
│   │   ├── motors.py                       # pybind → motors_py
│   │   ├── imu.py                          # pybind → imu_py
│   │   ├── bms.py                          # pybind → bms_py
│   │   ├── joy.py                          # uinput → /dev/input/eventX
│   │   └── policy.py                       # subprocess → ros2 launch
│   ├── error_codes.py                      # 四品牌错误码表
│   ├── monitors.py                         # 后台遥测推送
│   └── __main__.py                         # 入口
├── debian/
└── .github/
```

## 安装

```bash
dpkg-buildpackage -us -uc -b
sudo dpkg -i ../roboparty-rp-server_*.deb

# 自动 systemctl enable + start
systemctl status rp-server
journalctl -u rp-server -f

# 维护
systemctl stop rp-server       # 停服
systemctl disable rp-server    # 取消开机启动
systemctl enable rp-server     # 恢复开机启动

# 开发模式
python3 -m rp_server --config ../roboparty_inference/config/robot.yaml --port 8765 --log-level debug
```

## 依赖

| 类型 | 包名 |
|------|------|
| RoboParty | roboparty-base, roboparty-motors, roboparty-imu, roboparty-bms, roboparty-inference |
| 系统 | python3, python3-fastapi, python3-uvicorn, python3-websockets, python3-yaml, python3-psutil, python3-evdev, python3-serial |

## License

GPL-3.0 — Copyright (C) 2026 wentywenty
