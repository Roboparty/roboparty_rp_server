# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Motor state telemetry source (``MotorStates``).

Samples ``motors.get_states()`` once per tick; ``MotorErrorSource`` derives
error pushes from :attr:`last_states` so the driver is not polled twice.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from ..protocol.codec import Envelope
from .common import now_ms

DEFAULT_STATE_HZ = 1
DEFAULT_ERROR_HZ = 10


class MotorStateSource:
    def __init__(self, motors, mock: bool = False,
                 state_hz: int = DEFAULT_STATE_HZ, error_hz: int = DEFAULT_ERROR_HZ):
        self._motors = motors
        self._mock = mock
        self.state_period = 1.0 / max(state_hz, 1)
        self.sample_period = min(self.state_period, 1.0 / max(error_hz, 1))
        self.last_states: list[dict] = []
        self.last_message: Optional[Envelope] = None

    def sample(self) -> list[dict]:
        self.last_states = [] if self._mock else self._motors.get_states()
        return self.last_states

    @staticmethod
    def _message(states: list[dict]) -> Envelope:
        env = Envelope()
        env.header.timestamp_ms = now_ms()
        for state in states:
            motor = env.motors.motors.add()
            motor.id = state["id"]
            motor.position = state["position"]
            motor.speed = state["speed"]
            motor.torque = state["torque"]
            motor.temperature = state["temperature"]
            motor.error = state["error"]
            motor.mode = state["mode"]
            motor.response_count = state["response_count"]
        return env

    async def run(self, broadcast):
        next_state = 0.0
        while True:
            states = self.sample()
            now = time.monotonic()
            if now >= next_state:
                self.last_message = self._message(states)
                await broadcast(self.last_message)
                next_state = now + self.state_period
            await asyncio.sleep(self.sample_period)
