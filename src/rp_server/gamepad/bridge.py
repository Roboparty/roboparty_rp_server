# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""Gamepad → AT bridge (DJI / G12 / Linux evdev)."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Protocol

logger = logging.getLogger("rp_server.gamepad")

# Canonical AT button / axis names used by JoyDriver
BTN_NAMES = (
    "a", "b", "x", "y", "lb", "rb", "ltb", "rtb", "ls", "rs",
    "du", "dd", "dl", "dr", "start", "select", "mode",
)
AXIS_NAMES = ("lx", "ly", "rx", "ry", "lt", "rt")


class GamepadSource(Protocol):
    async def events(self):
        """Yield dicts: {type:'btn'|'axis', name:str, value:str|float}"""
        ...


class AtWsSink:
    """Send AT lines to rp_server WebSocket."""

    def __init__(self, ws_url: str = "ws://127.0.0.1:8765/ws"):
        self.ws_url = ws_url
        self._btn_id = 0
        self._ws = None

    async def connect(self):
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets package required for gamepad bridge") from exc
        self._ws = await websockets.connect(self.ws_url)
        hello = await self._ws.recv()
        logger.info("connected: %s (%s)", self.ws_url, hello)

    async def close(self):
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send_btn(self, name: str, state: str):
        self._btn_id += 1
        line = f"AT+BTN={name},{state},{self._btn_id}"
        await self._ws.send(line)
        logger.debug(">> %s", line)

    async def send_joy(self, axis: str, value: float):
        line = f"AT+JOY={axis},{value:.4f}"
        await self._ws.send(line)


# Vendor button maps → canonical AT names
DJI_BTN_MAP = {
    "A": "a", "B": "b", "X": "x", "Y": "y",
    "L1": "lb", "R1": "rb", "L2": "ltb", "R2": "rtb",
    "L3": "ls", "R3": "rs",
    "UP": "du", "DOWN": "dd", "LEFT": "dl", "RIGHT": "dr",
    "START": "start", "SELECT": "select", "HOME": "mode",
}
DJI_AXIS_MAP = {
    "LEFT_X": "lx", "LEFT_Y": "ly", "RIGHT_X": "rx", "RIGHT_Y": "ry",
    "L2": "lt", "R2": "rt",
}

G12_BTN_MAP = {
    "BTN_A": "a", "BTN_B": "b", "BTN_X": "x", "BTN_Y": "y",
    "BTN_L1": "lb", "BTN_R1": "rb", "BTN_L2": "ltb", "BTN_R2": "rtb",
    "BTN_THUMBL": "ls", "BTN_THUMBR": "rs",
    "BTN_DPAD_UP": "du", "BTN_DPAD_DOWN": "dd",
    "BTN_DPAD_LEFT": "dl", "BTN_DPAD_RIGHT": "dr",
    "BTN_START": "start", "BTN_SELECT": "select", "BTN_MODE": "mode",
}
G12_AXIS_MAP = {
    "ABS_X": "lx", "ABS_Y": "ly", "ABS_RX": "rx", "ABS_RY": "ry",
    "ABS_Z": "lt", "ABS_RZ": "rt",
}


def map_btn(vendor: str, raw: str) -> Optional[str]:
    table = DJI_BTN_MAP if vendor == "dji" else G12_BTN_MAP if vendor == "g12" else {}
    return table.get(raw) or (raw.lower() if raw.lower() in BTN_NAMES else None)


def map_axis(vendor: str, raw: str) -> Optional[str]:
    table = DJI_AXIS_MAP if vendor == "dji" else G12_AXIS_MAP if vendor == "g12" else {}
    return table.get(raw) or (raw.lower() if raw.lower() in AXIS_NAMES else None)


async def run_bridge(source: GamepadSource, sink: AtWsSink):
    await sink.connect()
    try:
        async for ev in source.events():
            if ev["type"] == "btn":
                await sink.send_btn(ev["name"], ev["value"])
            elif ev["type"] == "axis":
                await sink.send_joy(ev["name"], float(ev["value"]))
    finally:
        await sink.close()


class SimulatedSource:
    """Emit a few AT events for bring-up without hardware."""

    def __init__(self, vendor: str = "dji"):
        self.vendor = vendor

    async def events(self):
        seq = [
            ("btn", map_btn(self.vendor, "A") or "a", "down"),
            ("btn", "a", "up"),
            ("axis", "lx", 0.5),
            ("axis", "lx", 0.0),
        ]
        for typ, name, val in seq:
            yield {"type": typ, "name": name, "value": val}
            await asyncio.sleep(0.2)


class EvdevSource:
    """Read a Linux joystick and map to AT names (G12-style codes)."""

    def __init__(self, device_path: str = ""):
        self.device_path = device_path

    async def events(self):
        try:
            from evdev import InputDevice, categorize, ecodes, list_devices
        except ImportError as exc:
            raise RuntimeError("python3-evdev required") from exc

        path = self.device_path
        if not path:
            devices = list_devices()
            if not devices:
                raise RuntimeError("no input devices")
            path = devices[0]
        dev = InputDevice(path)
        logger.info("reading gamepad: %s (%s)", path, dev.name)
        loop = asyncio.get_running_loop()

        def _read():
            return next(dev.read_loop())

        while True:
            ev = await loop.run_in_executor(None, _read)
            if ev.type == ecodes.EV_KEY:
                key = ecodes.KEY.get(ev.code) or ecodes.BTN.get(ev.code) or f"BTN_{ev.code}"
                name = map_btn("g12", key) or map_btn("g12", f"BTN_{key}")
                if not name:
                    continue
                state = "down" if ev.value else "up"
                yield {"type": "btn", "name": name, "value": state}
            elif ev.type == ecodes.EV_ABS:
                absname = ecodes.ABS.get(ev.code, f"ABS_{ev.code}")
                axis = map_axis("g12", absname)
                if not axis:
                    continue
                # normalize typical 0..255 or -32768..32767
                val = float(ev.value)
                if abs(val) > 1.5:
                    val = max(-1.0, min(1.0, val / 32767.0))
                yield {"type": "axis", "name": axis, "value": val}


class DjiSdkSource:
    """Stub for DJI RC SDK — replace `_poll` with vendor SDK callbacks."""

    def __init__(self):
        logger.warning("DjiSdkSource is a stub; wire vendor SDK in _poll()")

    async def _poll(self):
        # Vendor integration point:
        # sdk = DJIRemoteController.open()
        # sdk.on_button(...)
        raise NotImplementedError(
            "Integrate DJI RC SDK here, then yield mapped events via map_btn/map_axis('dji', ...)"
        )

    async def events(self):
        await self._poll()
        return
        yield  # pragma: no cover


class G12SdkSource:
    """Stub for G12 proprietary SDK — prefer EvdevSource when G12 appears as HID."""

    def __init__(self):
        logger.warning("G12SdkSource stub; use EvdevSource if device is HID")

    async def events(self):
        raise NotImplementedError("Use EvdevSource for HID G12, or wire proprietary SDK")
        yield  # pragma: no cover
