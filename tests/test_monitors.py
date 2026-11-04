# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Telemetry monitor tests (queue backpressure + motor broadcast)."""

import asyncio

from rp_server.monitors import TelemetryMonitor
from rp_server.protocol.codec import Envelope


class FakeMotors:
    def get_states(self):
        return [{
            "id": 1,
            "position": 0.5,
            "speed": 0.0,
            "torque": 0.0,
            "temperature": 30.0,
            "error": 0,
            "mode": 1,
            "response_count": 10,
        }]


def test_broadcast_drops_oldest_and_keeps_slow_client():
    monitor = TelemetryMonitor(None, None, None, {})
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    monitor.add_client(q)

    old, new = Envelope(), Envelope()
    old.conn.connected = False
    new.conn.connected = True

    async def scenario():
        await monitor.broadcast(old)
        await monitor.broadcast(new)
        return q.get_nowait()

    assert asyncio.run(scenario()).conn.connected is True
    assert monitor.clients == {q}


def test_motor_loop_broadcasts_to_ws_clients():
    monitor = TelemetryMonitor(None, None, FakeMotors(), {})
    q: asyncio.Queue = asyncio.Queue()
    monitor.add_client(q)

    async def scenario():
        task = asyncio.create_task(monitor._motor_source.run(monitor.broadcast))
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return q.get_nowait()

    msg = asyncio.run(scenario())
    assert msg.WhichOneof("body") == "motors"
    assert msg.motors.motors[0].id == 1


def test_motor_loop_derives_error_push_from_same_snapshot():
    class ErrorMotors(FakeMotors):
        def get_states(self):
            return [{
                "id": 2, "position": 0.0, "speed": 0.0, "torque": 0.0,
                "temperature": 40.0, "error": 3, "name": "LRO_UNDER_VOLTAGE",
                "type": "LRO", "mode": 1, "response_count": 5,
            }]

    monitor = TelemetryMonitor(None, None, ErrorMotors(), {})
    q: asyncio.Queue = asyncio.Queue()
    monitor.add_client(q)

    async def scenario():
        tasks = [
            asyncio.create_task(monitor._motor_source.run(monitor.broadcast)),
            asyncio.create_task(monitor._error_source.run(monitor.broadcast)),
        ]
        await asyncio.sleep(0.01)
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        bodies = []
        while not q.empty():
            bodies.append(q.get_nowait().WhichOneof("body"))
        return bodies

    bodies = asyncio.run(scenario())
    assert "motors" in bodies
    assert "motor_error_push" in bodies
