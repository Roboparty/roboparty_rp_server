# RoboParty RP Server — Product Overview

## What It Is

Unified backend on RK3588: gamepad, Android App, head display, LLM web UI, and MCP clients all access the robot through this service.

Default port **8765** (WebSocket + REST, same port).

## Who Uses It

| Role | How |
|------|-----|
| Android App | WS AT for keys/joystick, receives `@IMU`/`@BAT` |
| Gamepad | SDK/evdev → `scripts/gamepad_bridge.py` → AT |
| Head display / Web login | Scan QR `/auth/qr` → poll JWT |

## Feature List

1. AT protocol hardware gateway (CONN/BTN/JOY/SYSINFO/POLICY/ERR)
2. Telemetry push: IMU 100Hz / battery 1Hz / errors 10Hz
3. Policy (ros2 inference) start/stop
4. QR code login with JWT
5. Mock mode (local dev without hardware: `--mock` / `RP_MOCK=1`)

## Non-Goals

- Does not replace motor firmware / BMS daemon
- Does not bundle Android UI / gamepad SDK binaries (provides bridge & stub)
- Does not compile NDK artifacts in this package (provides `tools/canutils-ndk` scripts)

## Version

Current service version: `1.1.0` (see `/health`).
