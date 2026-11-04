# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Telemetry coordinator: owns clients and schedules the four sources.

Each source lives in its own module:
  * ``imu.py``          — 50Hz IMU samples
  * ``battery.py``      — 50Hz battery samples
  * ``motors.py``       — motor state sampling / 1Hz broadcasts
  * ``motor_errors.py`` — 10Hz error pushes derived from the same snapshot
"""

from __future__ import annotations

import asyncio
from typing import Optional

from ..protocol.codec import Envelope
from .battery import BatterySource
from .imu import ImuSource
from .motor_errors import MotorErrorSource
from .motors import MotorStateSource


class TelemetryMonitor:

    def __init__(self, imu, bms, motors, config: dict, mock: bool = False):
        tcfg = config.get("telemetry", {})
        self.clients: set[asyncio.Queue] = set()
        self._imu_source = ImuSource(imu, mock, tcfg.get("imu_hz", 50))
        self._battery_source = BatterySource(bms, mock, tcfg.get("battery_hz", 50))
        self._motor_source = MotorStateSource(
            motors, mock, tcfg.get("motor_hz", 1), tcfg.get("error_hz", 10))
        self._error_source = MotorErrorSource(
            self._motor_source, tcfg.get("error_hz", 10))
        self._tasks: list[asyncio.Task] = []

    @property
    def last_imu(self) -> Optional[Envelope]:
        return self._imu_source.last_message

    @property
    def last_battery(self) -> Optional[Envelope]:
        return self._battery_source.last_message

    @property
    def last_motors(self) -> Optional[Envelope]:
        return self._motor_source.last_message

    @property
    def last_errors(self) -> list[Envelope]:
        return list(self._error_source.last_messages)

    def add_client(self, q: asyncio.Queue):
        self.clients.add(q)

    def remove_client(self, q: asyncio.Queue):
        self.clients.discard(q)

    async def broadcast(self, msg: Envelope):
        dead = []
        for q in self.clients:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # Slow client: drop the oldest telemetry sample, keep the
                # connection alive. Only give up if the queue is still full.
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    dead.append(q)
        for q in dead:
            self.clients.discard(q)

    async def start(self):
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(source.run(self.broadcast))
            for source in (self._imu_source, self._battery_source,
                           self._motor_source, self._error_source)
        ]

    async def stop(self):
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
