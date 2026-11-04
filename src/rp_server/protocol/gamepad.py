# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Physical gamepad → protobuf Envelope bridge (Linux evdev)."""

from __future__ import annotations

import asyncio
import logging
import json
import os
import ssl
import time
from typing import Optional, Protocol

from roboparty.v1 import commands_pb2, envelope_pb2

from .enums import axis_value, button_value

logger = logging.getLogger("rp_server.gamepad")

# Canonical driver button / axis names used by JoyDriver
BTN_NAMES = (
    "a", "b", "x", "y", "lb", "rb", "ltb", "rtb", "ls", "rs",
    "du", "dd", "dl", "dr", "start", "select", "mode",
)
AXIS_NAMES = ("lx", "ly", "rx", "ry", "lt", "rt")


def map_btn(raw: str) -> Optional[str]:
    """Map raw button name to canonical name, or None if unmapped."""
    return raw.lower() if raw.lower() in BTN_NAMES else None


def map_axis(raw: str) -> Optional[str]:
    """Map raw axis name to canonical name, or None if unmapped."""
    return raw.lower() if raw.lower() in AXIS_NAMES else None


class GamepadSource(Protocol):
    async def events(self):
        """Yield dicts: {type:'btn'|'axis', name:str, value:str|float}"""
        ...


class WsEnvelopeSink:
    """Send protobuf Envelopes to rp_server over WebSocket (binary frames)."""

    def __init__(self, ws_url: str = "wss://127.0.0.1:9000/ws", token: str | None = None):
        self.ws_url = ws_url
        self.token = token if token is not None else os.environ.get("RP_SERVICE_TOKEN")
        self._ws = None
        self._tasks = []
        self._axes = dict.fromkeys(AXIS_NAMES, 0.0)
        self._buttons = dict.fromkeys(BTN_NAMES, "up")
        self._active = False

    async def connect(self):
        try:
            # Available in both distribution websockets 10.x and modern 16.x.
            from websockets.legacy.client import connect
        except ImportError as exc:
            raise RuntimeError("websockets package required for gamepad bridge") from exc
        await self.close()
        if not self.token or any(c in self.token for c in "\r\n"):
            raise RuntimeError("RP_SERVICE_TOKEN is required for the gamepad bridge")
        self._axes = dict.fromkeys(AXIS_NAMES, 0.0)
        self._buttons = dict.fromkeys(BTN_NAMES, "up")
        ssl_context = None
        if self.ws_url.startswith("wss://"):
            cert = os.environ.get("RP_TLS_CERT", "/etc/rp-server/auth/tls.crt")
            if not os.path.isfile(cert):
                raise RuntimeError(f"wss requires a trusted certificate: {cert}")
            ssl_context = ssl.create_default_context(cafile=cert)
        self._ws = await connect(
            self.ws_url, extra_headers={"Authorization": f"Bearer {self.token}"},
            subprotocols=["roboparty.v2.proto"], open_timeout=8, ssl=ssl_context)
        try:
            await self._ws.send(json.dumps({"type": "lease.acquire"}))
            await asyncio.wait_for(self._wait_for_lease(), 3)
        except BaseException:
            await self.close()
            raise
        self._active = True
        self._tasks = [asyncio.create_task(self._receive()), asyncio.create_task(self._stream())]
        logger.info("connected with control lease: %s", self.ws_url)

    async def _wait_for_lease(self):
        while True:
            raw = await self._ws.recv()
            if isinstance(raw, bytes):
                continue
            message = json.loads(raw)
            if message.get("type") == "error":
                raise RuntimeError(f"control lease rejected: {message.get('code')}")
            if message.get("type") == "lease" and message.get("status") == "acquired":
                return

    async def _receive(self):
        try:
            while self._active:
                raw = await self._ws.recv()
                if isinstance(raw, bytes):
                    continue
                message = json.loads(raw)
                if message.get("type") == "error" or (
                    message.get("type") == "lease" and message.get("status") not in
                    ("acquired", "renewed", "active")
                ):
                    raise RuntimeError("gamepad control lease lost")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("gamepad disconnected: %s", exc)
            await self.close()

    async def _stream(self):
        try:
            next_heartbeat = 0.0
            while self._active:
                await self._snapshot()
                now = asyncio.get_running_loop().time()
                if now >= next_heartbeat:
                    await self._ws.send(json.dumps({"type": "heartbeat"}))
                    next_heartbeat = now + 0.5
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("gamepad output stopped: %s", exc)
            await self.close()

    async def close(self):
        self._active = False
        socket, self._ws = self._ws, None
        tasks, self._tasks = self._tasks, []
        others = [task for task in tasks if task is not asyncio.current_task()]
        for task in others:
            task.cancel()
        if others:
            await asyncio.gather(*others, return_exceptions=True)
        if socket:
            await socket.close()

    async def _snapshot(self):
        if not self._active or self._ws is None:
            raise RuntimeError("gamepad disconnected; reconnect explicitly")
        env = envelope_pb2.Envelope()
        env.header.timestamp_ms = time.time_ns() // 1_000_000
        for name, value in self._axes.items():
            env.control.axes.add(axis=axis_value(name), value=value)
        for name, state in self._buttons.items():
            env.control.buttons.add(button=button_value(name), state=(
                commands_pb2.ButtonState.BUTTON_STATE_DOWN if state == "down"
                else commands_pb2.ButtonState.BUTTON_STATE_UP))
        await self._ws.send(env.SerializeToString())

    async def send_btn(self, name: str, state: str):
        if name not in self._buttons:
            raise ValueError(f"unknown button: {name}")
        self._buttons[name] = state
        await self._snapshot()
        logger.debug(">> button %s %s", name, state)

    async def send_joy(self, axis: str, value: float):
        if axis not in self._axes:
            raise ValueError(f"unknown axis: {axis}")
        self._axes[axis] = value
        await self._snapshot()


async def run_bridge(source: GamepadSource, sink: WsEnvelopeSink):
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
    """Emit a few events for bring-up without hardware."""

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
    """Read a Linux joystick and map to canonical names."""

    def __init__(self, device_path: str = ""):
        self.device_path = device_path

    async def events(self):
        try:
            from evdev import InputDevice, ecodes, list_devices
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
