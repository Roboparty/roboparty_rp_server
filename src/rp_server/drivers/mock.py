# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""In-memory hardware backend for ``server.mock`` / ``RP_MOCK``.

The classes here satisfy the Protocols in :mod:`rp_server.drivers.base` so the
protocol handler, telemetry monitors and HTTP endpoints can run end to end
without motors_py, imu_py, evdev, a BMS socket or a ROS 2 installation.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

logger = logging.getLogger("rp_server.mock")

_DEFAULT_MOTOR_IDS = list(range(1, 13))
_DEFAULT_ERROR_NAMES = {
    0x1: "OVER_VOLTAGE",
    0x2: "UNDER_VOLTAGE",
    0x3: "OVER_CURRENT",
    0x4: "OVER_TEMPERATURE",
    0x5: "MOTOR_OFFLINE",
}


@dataclass
class _MockMotor:
    motor_id: int
    motor_type: str = "DM"
    position: float = 0.0
    speed: float = 0.0
    torque: float = 0.0
    temperature: float = 32.0
    error: int = 0
    error_name: str = ""
    mode: int = 0
    response_count: int = 0
    target: float = 0.0
    enabled: bool = False


class MockMotorsDriver:
    """Synthetic motor bus with the same surface as ``MotorDriver``."""

    def __init__(self) -> None:
        self._motors: list[_MockMotor] = []
        self._enabled = False

    def init(self, config: dict) -> bool:
        mc = (config or {}).get("motors", {})
        mock_cfg = (config or {}).get("mock", {})
        ids = list(mc.get("motor_id") or mock_cfg.get("motor_id") or _DEFAULT_MOTOR_IDS)
        if not ids:
            ids = list(_DEFAULT_MOTOR_IDS)
        mtypes = mc.get("motor_type") or ["DM"]
        if not isinstance(mtypes, (list, tuple)):
            mtypes = [mtypes]
        errors = {
            int(item["id"]): item
            for item in mock_cfg.get("motor_errors", [])
            if "id" in item
        }
        self._motors = []
        for index, motor_id in enumerate(ids):
            motor = _MockMotor(
                motor_id=int(motor_id),
                motor_type=str(mtypes[index % len(mtypes)]),
            )
            injected = errors.get(int(motor_id))
            if injected:
                motor.error = int(injected.get("code", 1))
                motor.error_name = str(
                    injected.get("name")
                    or _DEFAULT_ERROR_NAMES.get(motor.error, "UNKNOWN")
                )
            self._motors.append(motor)
        self._enabled = False
        logger.info("mock motors initialised: %d", len(self._motors))
        return True

    def deinit(self) -> None:
        self._enabled = False
        for motor in self._motors:
            motor.enabled = False
        self._motors.clear()

    def enable(self) -> bool:
        if not self._motors:
            return False
        self._enabled = True
        for motor in self._motors:
            motor.enabled = True
        return True

    def disable(self) -> None:
        self._enabled = False
        for motor in self._motors:
            motor.enabled = False

    @property
    def ready(self) -> bool:
        return bool(self._motors)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get_errors(self) -> list[dict]:
        return [
            {"id": motor.motor_id, "code": motor.error,
             "name": motor.error_name or "UNKNOWN", "type": motor.motor_type}
            for motor in self._motors
            if motor.error
        ]

    def get_states(self) -> list[dict]:
        states = []
        for motor in self._motors:
            if motor.enabled:
                motor.response_count += 1
            states.append({
                "id": motor.motor_id,
                "position": round(motor.position, 4),
                "speed": round(motor.speed, 4),
                "torque": round(motor.torque, 4),
                "temperature": round(motor.temperature, 1),
                "error": int(motor.error),
                "name": motor.error_name or "UNKNOWN",
                "type": motor.motor_type,
                "mode": int(motor.mode),
                "response_count": int(motor.response_count),
            })
        return states

    def clear_errors(self) -> None:
        for motor in self._motors:
            motor.error = 0
            motor.error_name = ""

    def set_mit(self, index: int, pos: float, vel: float,
                kp: float, kd: float, torque: float) -> None:
        if index < 0 or index >= len(self._motors):
            return
        motor = self._motors[index]
        motor.mode = 1
        motor.target = float(pos)
        if not motor.enabled:
            return
        previous = motor.position
        motor.position = float(pos)
        motor.speed = (motor.position - previous) / 0.01
        motor.torque = kp * (motor.position - previous) + torque

    def set_all_mit(self, pos: float, vel: float,
                    kp: float, kd: float, torque: float) -> None:
        for index in range(len(self._motors)):
            self.set_mit(index, pos, vel, kp, kd, torque)


class MockImuDriver:
    """Deterministic synthetic IMU."""

    def __init__(self) -> None:
        self._ready = False
        self._started = time.monotonic()

    def init(self, config: dict) -> bool:
        self._started = time.monotonic()
        self._ready = True
        return True

    def deinit(self) -> None:
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def read(self) -> dict | None:
        if not self._ready:
            return None
        elapsed = time.monotonic() - self._started
        return {
            "quat": [1.0, 0.0, 0.0, 0.0],
            "ang_vel": [0.0, 0.0, math.sin(elapsed) * 0.01],
            "lin_acc": [0.0, 0.0, 9.8],
            "temp": 36.5,
        }


class MockBmsDriver:
    """Synthetic 48 V battery pack."""

    def __init__(self) -> None:
        self._ready = False

    def init(self, config: dict) -> bool:
        self._ready = True
        return True

    def deinit(self) -> None:
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def read(self) -> dict | None:
        if not self._ready:
            return None
        return {
            "voltage": 48.2,
            "current": -1.5,
            "soc": 87.0,
            "temp": 32.0,
            "capacity": 20.0,
            "soh": 100.0,
            "cycles": 3,
            "state": "2",
            "protect": 0,
            "io_state": 1,
            "power_on": True,
        }


class MockJoyDriver:
    """Virtual gamepad that records input instead of emitting uinput events."""

    DEVICE_PATH = "mock://rp-virtual-joy"

    def __init__(self) -> None:
        self._ready = False
        self.buttons: dict[str, str] = {}
        self.axes: dict[str, float] = {}

    def init(self) -> bool:
        self._ready = True
        self.buttons.clear()
        self.axes.clear()
        return True

    def deinit(self) -> None:
        self._ready = False
        self.buttons.clear()
        self.axes.clear()

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def device_path(self) -> str:
        return self.DEVICE_PATH if self._ready else ""

    def set_button(self, name: str, state: str) -> None:
        self.buttons[name.lower()] = state.lower()

    def set_axis(self, name: str, value: float) -> None:
        self.axes[name.lower()] = max(-1.0, min(1.0, float(value)))

    def reset(self) -> None:
        self.buttons.clear()
        self.axes.clear()


class MockPolicyDriver:
    """Policy lifecycle stub; never spawns a ROS 2 process."""

    def __init__(self) -> None:
        self._running = False
        self._name = "none"
        self.state = "STOPPED"
        self.pid = 0
        self.exit_code = -1
        self.message = "mock policy backend"
        self.updated_at_ms = int(time.time() * 1000)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def name(self) -> str:
        return self._name

    async def start(self, name: str = "default") -> bool:
        self._name = name or "default"
        self._running = True
        self.state = "RUNNING"
        self.pid = 0
        self.exit_code = 0
        self.message = "mock policy running"
        self.updated_at_ms = int(time.time() * 1000)
        return True

    async def stop(self) -> bool:
        self._running = False
        self.state = "STOPPED"
        self.exit_code = 0
        self.message = "mock policy stopped"
        self.updated_at_ms = int(time.time() * 1000)
        return True
