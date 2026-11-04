# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Battery telemetry source (``@BAT`` → ``BatteryState``)."""

from __future__ import annotations

import asyncio
from typing import Optional

from ..protocol.codec import Envelope
from .common import now_ms

DEFAULT_HZ = 50


class BatterySource:
    def __init__(self, bms, mock: bool = False, hz: int = DEFAULT_HZ):
        self._bms = bms
        self._mock = mock
        self.interval = 1.0 / max(hz, 1)
        self.last_message: Optional[Envelope] = None

    @staticmethod
    def _mock_data() -> dict:
        return {"voltage": 48.2, "current": -1.5, "soc": 87.0, "temp": 32.0}

    @staticmethod
    def _message(data: dict) -> Envelope:
        env = Envelope()
        env.header.timestamp_ms = now_ms()
        bat = env.battery
        bat.voltage = data["voltage"]
        bat.current = data["current"]
        bat.soc = data["soc"]
        bat.temp = data["temp"]
        for src, dst in (("capacity", "capacity"), ("soh", "soh"),
                         ("cycles", "cycles"), ("state", "state"),
                         ("protect", "protect"), ("io_state", "io_state"),
                         ("power_on", "power_on")):
            if src in data:
                setattr(bat, dst, data[src])
        return env

    async def run(self, broadcast):
        while True:
            data = self._mock_data() if self._mock else self._bms.read()
            if data:
                self.last_message = self._message(data)
                await broadcast(self.last_message)
            await asyncio.sleep(self.interval)
