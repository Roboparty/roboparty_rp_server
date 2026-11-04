# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Motor error push source (``MotorErrorPush``).

Reads the latest snapshot produced by :class:`MotorStateSource` instead of
calling ``get_errors()`` again.
"""

from __future__ import annotations

import asyncio

from ..protocol.codec import Envelope

from roboparty.v1 import responses_pb2

from .common import now_ms
from .motors import MotorStateSource

DEFAULT_HZ = 10


class MotorErrorSource:
    def __init__(self, state_source: MotorStateSource, hz: int = DEFAULT_HZ):
        self._state_source = state_source
        self.period = 1.0 / max(hz, 1)
        self.last_messages: list[Envelope] = []

    @staticmethod
    def _message(state: dict) -> Envelope:
        env = Envelope()
        env.header.timestamp_ms = now_ms()
        env.motor_error_push.error.CopyFrom(responses_pb2.MotorError(
            motor_id=state["id"], code=state["error"],
            name=state.get("name", ""), type=state.get("type", "")))
        return env

    async def run(self, broadcast):
        while True:
            errors = [state for state in self._state_source.last_states
                      if state.get("error")]
            self.last_messages = [self._message(state) for state in errors]
            for msg in self.last_messages:
                await broadcast(msg)
            await asyncio.sleep(self.period)
