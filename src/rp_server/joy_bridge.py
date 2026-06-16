# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""Virtual joystick via Linux uinput.

Creates /dev/input/eventX that any ROS node or userspace app can read
as a standard gamepad.  AT+BTN and AT+JOY from WebSocket are translated
directly into kernel input events.
"""

import logging
import os
import time
from typing import Optional

try:
    import evdev
    from evdev import UInput, ecodes, AbsInfo
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

logger = logging.getLogger("rp_server.joy_bridge")

# Virtual device capabilities (PS4-style gamepad layout)
JOY_AXES = {
    "lx":  ecodes.ABS_X,
    "ly":  ecodes.ABS_Y,
    "rx":  ecodes.ABS_RX,
    "ry":  ecodes.ABS_RY,
    "lt":  ecodes.ABS_Z,
    "rt":  ecodes.ABS_RZ,
}

JOY_BTNS = {
    # Face buttons — name → BTN code
    "a": ecodes.BTN_SOUTH,
    "b": ecodes.BTN_EAST,
    "x": ecodes.BTN_NORTH,
    "y": ecodes.BTN_WEST,
    # Shoulder / trigger buttons
    "lb": ecodes.BTN_TL,
    "rb": ecodes.BTN_TR,
    "ltb": ecodes.BTN_TL2,
    "rtb": ecodes.BTN_TR2,
    # Stick clicks
    "ls": ecodes.BTN_THUMBL,
    "rs": ecodes.BTN_THUMBR,
    # D-pad
    "du": ecodes.BTN_DPAD_UP,
    "dd": ecodes.BTN_DPAD_DOWN,
    "dl": ecodes.BTN_DPAD_LEFT,
    "dr": ecodes.BTN_DPAD_RIGHT,
    # Center buttons
    "start":   ecodes.BTN_START,
    "select":  ecodes.BTN_SELECT,
    "mode":    ecodes.BTN_MODE,
    # Numeric fallback (btn_0 .. btn_15 mapping for generic use)
}

# Numeric fallback mapping: btn_N → BTN_TRIGGER_HAPPY + N
_BTN_NUM_BASE = ecodes.BTN_TRIGGER_HAPPY


class JoyBridge:
    """Virtual gamepad device via Linux uinput.

    Usage:
        bridge = JoyBridge()
        bridge.connect()
        bridge.set_button("a", "down")
        bridge.set_axis("lx", -0.5)
        bridge.disconnect()
    """

    def __init__(self):
        self._ui: Optional[UInput] = None
        self._axis_state: dict[int, float] = {}   # abs_code → current value
        self._btn_state: dict[int, int] = {}       # btn_code → 0|1

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        if not HAS_EVDEV:
            logger.warning("evdev not available — virtual joystick disabled")
            return False
        try:
            # Axis config: all axes range [-32767, 32767] with flat=0, fuzz=0
            caps = {}
            for abs_code in JOY_AXES.values():
                caps[abs_code] = AbsInfo(
                    value=0, min=-32767, max=32767, fuzz=0, flat=0, resolution=0)

            btn_codes = list(JOY_BTNS.values())
            # Also register generic BTN_TRIGGER_HAPPY1..16 for numeric fallback
            for i in range(16):
                btn_codes.append(_BTN_NUM_BASE + i + 1)

            self._ui = UInput(
                events={ecodes.EV_ABS: list(caps.keys()), ecodes.EV_KEY: btn_codes},
                name="rp-virtual-joy",
                vendor=0x1209, product=0x0001, version=0x0001,
            )
            # Sync initial axis positions
            for abs_code in JOY_AXES.values():
                self._ui.write(ecodes.EV_ABS, abs_code, 0)
                self._axis_state[abs_code] = 0.0
            self._ui.syn()

            logger.info("virtual joystick device created: %s", self._ui.device.path)
            return True
        except Exception as exc:
            logger.error("virtual joystick create failed: %s", exc)
            return False

    def disconnect(self):
        if self._ui:
            try:
                self._ui.close()
            except Exception:
                pass
            self._ui = None

    @property
    def connected(self) -> bool:
        return self._ui is not None

    @property
    def device_path(self) -> str:
        if self._ui:
            return self._ui.device.path
        return ""

    # ------------------------------------------------------------------
    # Input handlers
    # ------------------------------------------------------------------

    def set_button(self, name: str, state: str):
        """state = 'up' or 'down'.  name can be 'a','b','start', or 'btn_3'."""
        code = self._resolve_btn(name)
        if code is None:
            return
        value = 1 if state.lower() == "down" else 0
        if self._btn_state.get(code) == value:
            return
        self._btn_state[code] = value
        try:
            self._ui.write(ecodes.EV_KEY, code, value)
            self._ui.syn()
        except Exception as exc:
            logger.warning("joy btn write failed: %s", exc)

    def set_axis(self, name: str, value: float):
        """value in [-1.0, 1.0], name: 'lx','ly','rx','ry','lt','rt'."""
        code = JOY_AXES.get(name.lower())
        if code is None:
            return
        clamped = max(-1.0, min(1.0, float(value)))
        raw = int(clamped * 32767)
        if self._axis_state.get(code) == clamped:
            return
        self._axis_state[code] = clamped
        try:
            self._ui.write(ecodes.EV_ABS, code, raw)
            self._ui.syn()
        except Exception as exc:
            logger.warning("joy axis write failed: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_btn(self, name: str) -> Optional[int]:
        """name → Linux BTN code."""
        name_lower = name.lower().strip()
        # Named buttons
        if name_lower in JOY_BTNS:
            return JOY_BTNS[name_lower]
        # Numeric: btn_0 .. btn_15
        if name_lower.startswith("btn_"):
            try:
                n = int(name_lower[4:])
                if 0 <= n < 16:
                    return _BTN_NUM_BASE + n + 1
            except ValueError:
                pass
        # Raw numeric string
        try:
            n = int(name_lower)
            if 0 <= n < 16:
                return _BTN_NUM_BASE + n + 1
        except ValueError:
            pass
        return None
