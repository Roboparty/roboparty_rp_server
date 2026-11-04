# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Mapping between protobuf enums and the driver-facing string names.

The joy driver keys axes/buttons by short strings ("lx", "a", "btn_3"); the
wire uses ``roboparty.v1`` enums. This module is the single place that knows
both sides.
"""

from __future__ import annotations

from roboparty.v1 import commands_pb2

_Axis = commands_pb2.Axis
_Button = commands_pb2.Button
_ButtonState = commands_pb2.ButtonState

# Keep in sync with rp_server.drivers.joy AXIS_MAP / BTN_MAP.
_AXIS_BY_NAME = {
    "lx": _Axis.AXIS_LX, "ly": _Axis.AXIS_LY,
    "rx": _Axis.AXIS_RX, "ry": _Axis.AXIS_RY,
    "lt": _Axis.AXIS_LT, "rt": _Axis.AXIS_RT,
}
_BUTTON_BY_NAME = {
    "a": _Button.BUTTON_A, "b": _Button.BUTTON_B, "x": _Button.BUTTON_X, "y": _Button.BUTTON_Y,
    "lb": _Button.BUTTON_LB, "rb": _Button.BUTTON_RB,
    "ltb": _Button.BUTTON_LTB, "rtb": _Button.BUTTON_RTB,
    "ls": _Button.BUTTON_LS, "rs": _Button.BUTTON_RS,
    "du": _Button.BUTTON_DU, "dd": _Button.BUTTON_DD,
    "dl": _Button.BUTTON_DL, "dr": _Button.BUTTON_DR,
    "start": _Button.BUTTON_START, "select": _Button.BUTTON_SELECT, "mode": _Button.BUTTON_MODE,
}
for _i in range(16):
    _BUTTON_BY_NAME[f"btn_{_i}"] = _Button.BUTTON_NUM_0 + _i


def axis_name(value: int) -> str:
    """Enum value → driver axis name ("lx"); "" for unspecified/unknown."""
    if value == _Axis.AXIS_UNSPECIFIED:
        return ""
    name = _Axis.Name(value)  # AXIS_LX
    return name[len("AXIS_"):].lower()


def axis_value(name: str) -> int:
    return _AXIS_BY_NAME.get(name.lower(), _Axis.AXIS_UNSPECIFIED)


def button_name(value: int) -> str:
    """Enum value → driver button name ("a", "btn_3"); "" if unspecified."""
    if value == _Button.BUTTON_UNSPECIFIED:
        return ""
    if _Button.BUTTON_NUM_0 <= value <= _Button.BUTTON_NUM_15:
        return f"btn_{value - _Button.BUTTON_NUM_0}"
    name = _Button.Name(value)  # BUTTON_LB
    return name[len("BUTTON_"):].lower()


def button_value(name: str) -> int:
    return _BUTTON_BY_NAME.get(name.lower(), _Button.BUTTON_UNSPECIFIED)


def button_state_name(value: int) -> str:
    """Enum value → "up"/"down" (defaults to "up")."""
    return "down" if value == _ButtonState.BUTTON_STATE_DOWN else "up"
