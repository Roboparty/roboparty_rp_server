# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""uinput → /dev/input/eventX virtual gamepad."""

import logging
from typing import Optional

try:
    from evdev import UInput, ecodes, AbsInfo
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

logger = logging.getLogger("rp_server.joy")

AXIS_MAP = {"lx": ecodes.ABS_X, "ly": ecodes.ABS_Y, "rx": ecodes.ABS_RX, "ry": ecodes.ABS_RY,
            "lt": ecodes.ABS_Z, "rt": ecodes.ABS_RZ}

BTN_MAP = {
    "a": ecodes.BTN_SOUTH, "b": ecodes.BTN_EAST, "x": ecodes.BTN_NORTH, "y": ecodes.BTN_WEST,
    "lb": ecodes.BTN_TL, "rb": ecodes.BTN_TR, "ltb": ecodes.BTN_TL2, "rtb": ecodes.BTN_TR2,
    "ls": ecodes.BTN_THUMBL, "rs": ecodes.BTN_THUMBR,
    "du": ecodes.BTN_DPAD_UP, "dd": ecodes.BTN_DPAD_DOWN, "dl": ecodes.BTN_DPAD_LEFT, "dr": ecodes.BTN_DPAD_RIGHT,
    "start": ecodes.BTN_START, "select": ecodes.BTN_SELECT, "mode": ecodes.BTN_MODE,
}
_BTN_NUM_BASE = ecodes.BTN_TRIGGER_HAPPY


class JoyDriver:
    """Virtual gamepad via Linux uinput."""

    def __init__(self):
        self._ui: Optional[UInput] = None
        self._axis_state: dict[int, float] = {}
        self._btn_state: dict[int, int] = {}

    def init(self) -> bool:
        if not HAS_EVDEV:
            return False
        try:
            caps = {c: AbsInfo(value=0, min=-32767, max=32767, fuzz=0, flat=0, resolution=0)
                    for c in AXIS_MAP.values()}
            btn_codes = list(BTN_MAP.values()) + [_BTN_NUM_BASE + i + 1 for i in range(16)]
            self._ui = UInput(
                events={ecodes.EV_ABS: list(caps.keys()), ecodes.EV_KEY: btn_codes},
                name="rp-virtual-joy", vendor=0x1209, product=0x0001, version=0x0001,
            )
            for c in AXIS_MAP.values():
                self._ui.write(ecodes.EV_ABS, c, 0)
                self._axis_state[c] = 0.0
            self._ui.syn()
            logger.info("virtual joystick: %s", self._ui.device.path)
            return True
        except Exception as exc:
            logger.error("uinput failed: %s", exc)
            return False

    def deinit(self):
        if self._ui:
            try:
                self._ui.close()
            except Exception:
                pass
            self._ui = None

    @property
    def ready(self) -> bool:
        return self._ui is not None

    @property
    def device_path(self) -> str:
        return self._ui.device.path if self._ui else ""

    def set_button(self, name: str, state: str):
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
            logger.warning("joy btn failed: %s", exc)

    def set_axis(self, name: str, value: float):
        code = AXIS_MAP.get(name.lower())
        if code is None:
            return
        clamped = max(-1.0, min(1.0, float(value)))
        if self._axis_state.get(code) == clamped:
            return
        self._axis_state[code] = clamped
        try:
            self._ui.write(ecodes.EV_ABS, code, int(clamped * 32767))
            self._ui.syn()
        except Exception as exc:
            logger.warning("joy axis failed: %s", exc)

    def _resolve_btn(self, name: str) -> Optional[int]:
        n = name.lower().strip()
        if n in BTN_MAP:
            return BTN_MAP[n]
        if n.startswith("btn_"):
            try:
                i = int(n[4:])
                if 0 <= i < 16:
                    return _BTN_NUM_BASE + i + 1
            except ValueError:
                pass
        try:
            i = int(n)
            if 0 <= i < 16:
                return _BTN_NUM_BASE + i + 1
        except ValueError:
            pass
        return None
