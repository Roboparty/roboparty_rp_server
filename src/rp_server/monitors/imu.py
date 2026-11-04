# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""IMU telemetry source (``@IMU`` → ``ImuSample``)."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Optional

from ..protocol.codec import Envelope
from .common import now_ms

DEFAULT_HZ = 50


class ImuSource:
    def __init__(self, imu, mock: bool = False, hz: int = DEFAULT_HZ):
        self._imu = imu
        self._mock = mock
        self.interval = 1.0 / max(hz, 1)
        self.last_message: Optional[Envelope] = None

    def _mock_data(self) -> dict:
        t = time.time()
        return {
            "quat": [1.0, 0.0, 0.0, 0.0],
            "ang_vel": [0.0, 0.0, math.sin(t) * 0.01],
            "lin_acc": [0.0, 0.0, 9.8],
            "temp": 36.5,
        }

    @staticmethod
    def _message(data: dict) -> Envelope:
        env = Envelope()
        env.header.timestamp_ms = now_ms()
        sample = env.imu
        q, av, la = data["quat"], data["ang_vel"], data["lin_acc"]
        sample.w, sample.x, sample.y, sample.z = q[0], q[1], q[2], q[3]
        sample.gx, sample.gy, sample.gz = av[0], av[1], av[2]
        sample.ax, sample.ay, sample.az = la[0], la[1], la[2]
        sample.temperature = data["temp"]
        return env

    async def run(self, broadcast):
        while True:
            data = self._mock_data() if self._mock else self._imu.read()
            if data:
                self.last_message = self._message(data)
                await broadcast(self.last_message)
            await asyncio.sleep(self.interval)
