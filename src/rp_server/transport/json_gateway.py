# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""JSON <-> Envelope mapping for the legacy-style app control gateway.

The app speaks the old JSON packet shapes. The gateway translates them to the
protobuf ``Envelope`` used by ``CommandHandler`` and translates telemetry back.
Transport security (TLS) and auth (registered app key + JWT) are handled by the
WebSocket endpoint; nothing here invents crypto.
"""

from __future__ import annotations

import time
from typing import Optional

from ..protocol.codec import Envelope

from roboparty.v1 import commands_pb2

Axis = commands_pb2.Axis
Button = commands_pb2.Button
ButtonState = commands_pb2.ButtonState

_AXES = (
    ("left_stick_x", Axis.AXIS_LX),
    ("left_stick_y", Axis.AXIS_LY),
    ("right_stick_x", Axis.AXIS_RX),
    ("right_stick_y", Axis.AXIS_RY),
)

_BUTTONS = (
    ("btn_a", Button.BUTTON_A),
    ("btn_b", Button.BUTTON_B),
    ("btn_x", Button.BUTTON_X),
    ("btn_y", Button.BUTTON_Y),
    ("btn_lb", Button.BUTTON_LB),
    ("btn_rb", Button.BUTTON_RB),
    ("dpad_up", Button.BUTTON_DU),
    ("dpad_down", Button.BUTTON_DD),
    ("dpad_left", Button.BUTTON_DL),
    ("dpad_right", Button.BUTTON_DR),
)


def _timestamp(msg: dict) -> int:
    try:
        return int(msg.get("timestamp") or 0) or time.time_ns() // 1_000_000
    except (TypeError, ValueError):
        return time.time_ns() // 1_000_000


def _trigger(msg: dict, key: str, button: str) -> float:
    """Return LT/RT in [-1, 0]; analog `lt`/`rt` wins, else the button bit."""
    if key in msg:
        try:
            value = -abs(float(msg[key]))
        except (TypeError, ValueError):
            value = 0.0
        value = max(-1.0, min(0.0, value))
        if value == 0.0 and msg.get(button):
            return -1.0
        return value
    return -1.0 if msg.get(button) else 0.0


def control_envelope(msg: dict) -> Envelope:
    env = Envelope()
    env.header.timestamp_ms = _timestamp(msg)
    try:
        env.header.sequence = int(msg.get("sequence") or 0) & 0xFFFFFFFF
    except (TypeError, ValueError):
        pass
    frame = env.control
    for key, axis in _AXES:
        if key in msg:
            try:
                frame.axes.add(axis=axis, value=max(-1.0, min(1.0, float(msg[key]))))
            except (TypeError, ValueError):
                pass
    # The larger touch stick is the app's primary "left" stick, while the
    # inference node consumes RX/RY for translation. Mirror a neutral left
    # stick onto RX/RY so both the touch and physical sticks work.
    for src, dst, other in (("left_stick_x", Axis.AXIS_RX, "right_stick_x"),
                            ("left_stick_y", Axis.AXIS_RY, "right_stick_y")):
        try:
            if float(msg.get(other) or 0.0) != 0.0:
                continue
        except (TypeError, ValueError):
            pass
        if src not in msg:
            continue
        try:
            frame.axes.add(axis=dst, value=max(-1.0, min(1.0, float(msg[src]))))
        except (TypeError, ValueError):
            pass
    # Inference treats LT/RT as yaw; accept analog values or button bits.
    frame.axes.add(axis=Axis.AXIS_LT, value=_trigger(msg, "lt", "btn_lt"))
    frame.axes.add(axis=Axis.AXIS_RT, value=_trigger(msg, "rt", "btn_rt"))
    for key, button in _BUTTONS:
        frame.buttons.add(
            button=button,
            state=ButtonState.BUTTON_STATE_DOWN if msg.get(key)
            else ButtonState.BUTTON_STATE_UP,
        )
    return env


def skill_envelope(msg: dict) -> Envelope:
    env = Envelope()
    env.header.timestamp_ms = _timestamp(msg)
    env.skill_action.action_id = str(msg.get("action_id", ""))
    env.skill_action.request_id = str(msg.get("request_id", ""))
    try:
        env.skill_action.sequence = int(msg.get("sequence") or 0) & 0xFFFFFFFF
    except (TypeError, ValueError):
        pass
    return env


def telemetry_json(env: Envelope) -> Optional[dict]:
    body = env.WhichOneof("body")
    stamp = env.header.timestamp_ms or time.time_ns() // 1_000_000
    if body == "battery":
        bat = env.battery
        return {"type": "battery", "timestamp": stamp,
                "voltage": bat.voltage, "current": bat.current,
                "soc": bat.soc, "temp": bat.temp}
    if body == "imu":
        imu = env.imu
        return {"type": "imu", "timestamp": stamp,
                "quat": [imu.w, imu.x, imu.y, imu.z],
                "ang_vel": [imu.gx, imu.gy, imu.gz],
                "lin_acc": [imu.ax, imu.ay, imu.az],
                "temp": imu.temperature}
    if body == "motors":
        motors = list(env.motors.motors)
        return {
            "type": "motors", "timestamp": stamp,
            "id": [m.id for m in motors],
            "position": [m.position for m in motors],
            "speed": [m.speed for m in motors],
            "torque": [m.torque for m in motors],
            "temperature": [m.temperature for m in motors],
            "error": [m.error for m in motors],
            "mode": [m.mode for m in motors],
            "response_count": [m.response_count for m in motors],
        }
    return None
