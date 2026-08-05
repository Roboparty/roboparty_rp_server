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

## Data Flow

```mermaid
flowchart TB
  subgraph clients [Clients]
    App[AndroidApp]
    Web[WebConsole]
    Pad[GamepadBridge]
  end
  subgraph server [rp_server_8765]
    WS["/ws AT"]
    REST["/auth"]
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
