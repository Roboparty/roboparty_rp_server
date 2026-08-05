# rp_server Architecture & Data Flow

## Three-Layer Architecture

```text
transport/   WebSocket / Serial / Bluetooth          ← swappable transports
protocol/    AT parsing + AtHandler dispatch         ← core abstraction
drivers/     motors / imu / bms / joy / policy       ← hardware
```

In-process REST extensions (same port):

| Module | Path | Purpose |
|--------|------|---------|
| auth | `/auth/*` | QR login → JWT |
| chat | `/chat` | DeepSeek multi-turn chat |
| mcp | `/mcp/*` | AT capabilities as MCP tools |

## Data Flow

```mermaid
flowchart TB
  subgraph clients [Clients]
    App[AndroidApp]
    Web[ChatWeb]
    Pad[GamepadBridge]
    McpClient[MCP_Client]
  end
  subgraph server [rp_server_8765]
    WS["/ws AT"]
    REST["/chat /auth /mcp"]
    AT[AtHandler]
    Tel[TelemetryMonitor]
    Drv[Drivers]
  end
  subgraph hw [Hardware]
    CAN[CAN_Motors]
    IMU[IMU]
    BMS[BMS]
    UInput[uinput_joy]
    ROS[ros2_policy]
  end
  App --> WS
  Pad --> WS
  Web --> REST
  McpClient --> REST
  WS --> AT
  REST --> AT
  AT --> Drv
  Drv --> CAN
  Drv --> IMU
  Drv --> BMS
  Drv --> UInput
  Drv --> ROS
  Tel --> WS
  IMU --> Tel
  BMS --> Tel
```

## Gamepad Pipeline

```text
DJI/G12/evdev → gamepad bridge → AT+BTN/JOY → WS → JoyDriver(uinput) → inference/motors
```

Simulation test: `python3 scripts/gamepad_bridge.py --mode sim`

## MCP Tools

Read-only (default on): `robot_conn` / `robot_sysinfo` / `robot_errors` / `robot_policy_status` / `robot_status`
Write ops require `mcp.readonly: false`: `robot_policy_control` / `robot_button`
