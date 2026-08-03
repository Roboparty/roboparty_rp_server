# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""Background telemetry push — reads from drivers, broadcasts to transport."""

import asyncio
import logging
import math
import time

from .protocol.at_parser import push_imu, push_bat, push_err

logger = logging.getLogger("rp_server.monitors")


class TelemetryMonitor:

    def __init__(self, imu, bms, motors, config: dict, mock: bool = False):
        self._imu = imu
        self._bms = bms
        self._motors = motors
        self._config = config
        self._mock = mock
        self.clients: set[asyncio.Queue] = set()
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self.last_imu: dict | None = None
        self.last_battery: dict | None = None
        self.last_errors: list[dict] = []

    def add_client(self, q: asyncio.Queue):
        self.clients.add(q)

    def remove_client(self, q: asyncio.Queue):
        self.clients.discard(q)

    async def broadcast(self, msg: str):
        dead = []
        for q in self.clients:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.clients.discard(q)

    async def start(self):
        if self._running:
            return
        self._running = True
        tcfg = self._config.get("telemetry", {})
        self._tasks = [
            asyncio.create_task(self._imu_loop(tcfg.get("imu_hz", 100))),
            asyncio.create_task(self._battery_loop(tcfg.get("battery_hz", 1))),
            asyncio.create_task(self._error_loop(tcfg.get("error_hz", 10))),
        ]

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()

    def _mock_imu(self) -> dict:
        t = time.time()
        return {
            "quat": [1.0, 0.0, 0.0, 0.0],
            "ang_vel": [0.0, 0.0, math.sin(t) * 0.01],
            "lin_acc": [0.0, 0.0, 9.8],
            "temp": 36.5,
        }

    def _mock_bat(self) -> dict:
        return {"voltage": 48.2, "current": -1.5, "soc": 87.0, "temp": 32.0}

    async def _imu_loop(self, hz: int):
        interval = 1.0 / max(hz, 1)
        while self._running:
            data = self._mock_imu() if self._mock else self._imu.read()
            if data:
                self.last_imu = data
                msg = push_imu(
                    data["quat"][0], data["quat"][1], data["quat"][2], data["quat"][3],
                    data["ang_vel"][0], data["ang_vel"][1], data["ang_vel"][2],
                    data["lin_acc"][0], data["lin_acc"][1], data["lin_acc"][2],
                    data["temp"],
                )
                await self.broadcast(msg)
            await asyncio.sleep(interval)

    async def _battery_loop(self, hz: int):
        interval = 1.0 / max(hz, 1)
        while self._running:
            data = self._mock_bat() if self._mock else self._bms.read()
            if data:
                self.last_battery = data
                msg = push_bat(data["voltage"], data["current"], data["soc"], data["temp"])
                await self.broadcast(msg)
            await asyncio.sleep(interval)

    async def _error_loop(self, hz: int):
        interval = 1.0 / max(hz, 1)
        while self._running:
            errors = [] if self._mock else self._motors.get_errors()
            self.last_errors = errors
            for e in errors:
                await self.broadcast(push_err(e["id"], e["code"], e["name"]))
            await asyncio.sleep(interval)
