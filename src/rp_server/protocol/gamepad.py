# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Physical gamepad → AT bridge (Linux evdev)."""

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


def map_btn(raw: str) -> Optional[str]:
    """Map raw button name to canonical AT name, or None if unmapped."""
    return raw.lower() if raw.lower() in BTN_NAMES else None


def map_axis(raw: str) -> Optional[str]:
    """Map raw axis name to canonical AT name, or None if unmapped."""
    return raw.lower() if raw.lower() in AXIS_NAMES else None


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

    async def events(self):
        seq = [
            ("btn", "a", "down"),
            ("btn", "a", "up"),
            ("axis", "lx", 0.5),
            ("axis", "lx", 0.0),
        ]
        for typ, name, val in seq:
            yield {"type": typ, "name": name, "value": val}
            await asyncio.sleep(0.2)


class EvdevSource:
    """Read a Linux joystick and map to AT names."""

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
                name = map_btn(key) or map_btn(f"BTN_{key}")
                if not name:
                    continue
                state = "down" if ev.value else "up"
                yield {"type": "btn", "name": name, "value": state}
            elif ev.type == ecodes.EV_ABS:
                absname = ecodes.ABS.get(ev.code, f"ABS_{ev.code}")
                axis = map_axis(absname)
                if not axis:
                    continue
                val = float(ev.value)
                if abs(val) > 1.5:
                    val = max(-1.0, min(1.0, val / 32767.0))
                yield {"type": "axis", "name": axis, "value": val}
