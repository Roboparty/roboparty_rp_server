# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""UDP listener: receive App JSON → translate to AT commands → dispatch to robot.

Data format (App UDP joystick protocol):

    {"type":"control", "sequence":1, "timestamp":..., "token":"...",
     "left_stick_x":0.0, "left_stick_y":0.0,
     "right_stick_x":0.0, "right_stick_y":0.0,
     "btn_a":false, "btn_b":false, "btn_x":false, "btn_y":false,
     "dpad_up":false, "dpad_down":false, "dpad_left":false, "dpad_right":false}

Also accepts legacy format (without "type"/"token" fields).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from ..protocol.at_parser import AtCommand, CmdType

logger = logging.getLogger("rp_server.udp")

# Axis name mapping: JSON field → AT+JOY axis name
_AXIS_MAP: dict[str, str] = {
    "left_stick_x": "lx",
    "left_stick_y": "ly",
    "right_stick_x": "rx",
    "right_stick_y": "ry",
}

# Button name mapping: JSON field → AT+BTN button name
_BTN_MAP: dict[str, str] = {
    "btn_a": "a",
    "btn_b": "b",
    "btn_x": "x",
    "btn_y": "y",
    "dpad_up": "du",
    "dpad_down": "dd",
    "dpad_left": "dl",
    "dpad_right": "dr",
}

# Dead zone: joystick values within ±DEAD_ZONE are ignored
DEAD_ZONE = 0.01


class UDPJoyListener:
    """Async UDP listener that feeds joystick/button data into AtHandler."""

    def __init__(
        self,
        at_handler: Any,
        host: str = "0.0.0.0",
        port: int = 9000,
    ):
        self._handler = at_handler
        self._host = host
        self._port = port
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._btn_state: dict[str, bool] = {}  # track previous button state
        self._btn_seq: int = 0
        self._last_seq: int = 0  # for duplicate/replay detection

    # ------------------------------------------------------------------
    # Connection protocol (asyncio Datagram)
    # ------------------------------------------------------------------

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport
        logger.info("UDP listener ready on %s:%d", self._host, self._port)

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        """Called by asyncio on each incoming UDP packet."""
        try:
            self._process(data)
        except Exception:
            logger.debug("UDP packet dropped from %s", addr, exc_info=True)

    def error_received(self, exc: Exception) -> None:
        logger.warning("UDP error: %s", exc)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        logger.info("UDP listener stopped")
        self._transport = None

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(
            lambda: self,
            local_addr=(self._host, self._port),
        )

    def stop(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None

    # ------------------------------------------------------------------
    # Packet processing
    # ------------------------------------------------------------------

    def _process(self, data: bytes) -> None:
        text = data.decode("utf-8", errors="replace").strip()
        if not text:
            return

        try:
            pkt: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError:
            logger.debug("UDP: invalid JSON (%d bytes)", len(data))
            return

        msg_type = pkt.get("type", "")
        if msg_type and msg_type != "control":
            # Only process "control" messages; ignore auth/heartbeat/etc.
            return

        # -- Sequence validation (skip old / duplicate packets) --
        seq = pkt.get("sequence", 0)
        if isinstance(seq, (int, float)):
            seq = int(seq)
            if seq and seq <= self._last_seq:
                return
            if seq:
                self._last_seq = seq

        # -- Axes → AT+JOY --
        for json_key, at_axis in _AXIS_MAP.items():
            val = pkt.get(json_key, 0.0)
            if not isinstance(val, (int, float)):
                continue
            if -DEAD_ZONE < val < DEAD_ZONE:
                continue
            clamped = max(-1.0, min(1.0, float(val)))
            self._dispatch(f"AT+JOY={at_axis},{clamped:.3f}")

        # -- Buttons → AT+BTN (only on state change) --
        for json_key, at_name in _BTN_MAP.items():
            pressed = bool(pkt.get(json_key, False))
            prev = self._btn_state.get(at_name, False)
            if pressed == prev:
                continue
            self._btn_state[at_name] = pressed
            self._btn_seq += 1
            state = "down" if pressed else "up"
            self._dispatch(f"AT+BTN={at_name},{state},{self._btn_seq}")

    def _dispatch(self, raw: str) -> None:
        """Parse raw AT line and feed into the handler (fire-and-forget)."""
        cmd = AtCommand.parse(raw)
        if cmd is None:
            return
        try:
            # Dispatch synchronously — all AT handlers are synchronous
            for _ in self._handler.dispatch(cmd):
                pass  # UDP doesn't need to send responses back
        except Exception:
            logger.debug("AT dispatch failed for %r", raw, exc_info=True)
