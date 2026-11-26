# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Serial transport lease handshake tests (no real UART)."""

import asyncio

from roboparty.v1 import commands_pb2, envelope_pb2, responses_pb2

from rp_server.protocol.codec import StreamDecoder
from rp_server.protocol.control_lease import ControlLease
from rp_server.transport.serial_server import _SerialProtocol


class FakeJoy:
    def __init__(self):
        self.reset_count = 0

    def reset(self):
        self.reset_count += 1


class FakePolicy:
    def __init__(self):
        self.running = False
        self.stop_count = 0

    async def stop(self):
        self.stop_count += 1
        self.running = False
        return True


class FakeHandler:
    def __init__(self):
        self.joy = FakeJoy()
        self.policy = FakePolicy()
        self.handled = []

    async def handle(self, env):
        self.handled.append(env.WhichOneof("body"))
        return []


class FakeTransport:
    def __init__(self):
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data)


def _responses(protocol):
    return list(StreamDecoder().feed(bytes(protocol._transport.data)))


def _run(protocol, env):
    asyncio.run(protocol._dispatch(env))


def _lease(action, request_id="r1"):
    env = envelope_pb2.Envelope()
    env.lease_command.action = action
    env.lease_command.request_id = request_id
    return env


def test_serial_control_requires_lease_then_dispatches():
    handler = FakeHandler()
    lease = ControlLease(handler)
    protocol = _SerialProtocol(handler, lease, "tty-test")
    protocol._transport = FakeTransport()

    joystick = envelope_pb2.Envelope()
    joystick.joystick.axis = 1
    joystick.joystick.value = 0.5
    _run(protocol, joystick)
    response = _responses(protocol)[-1]
    assert response.WhichOneof("body") == "error"
    assert "LEASE_REQUIRED" in response.error.message

    _run(protocol, _lease(commands_pb2.LeaseCommand.ACTION_ACQUIRE))
    response = _responses(protocol)[-1]
    assert response.lease_response.status == responses_pb2.LeaseResponse.STATUS_ACQUIRED
    assert lease.owner == protocol._session

    _run(protocol, joystick)
    assert handler.handled == ["joystick"]

    _run(protocol, _lease(commands_pb2.LeaseCommand.ACTION_HEARTBEAT))
    response = _responses(protocol)[-1]
    assert response.lease_response.status == responses_pb2.LeaseResponse.STATUS_HEARTBEAT

    _run(protocol, _lease(commands_pb2.LeaseCommand.ACTION_RELEASE))
    response = _responses(protocol)[-1]
    assert response.lease_response.status == responses_pb2.LeaseResponse.STATUS_RELEASED
    assert lease.owner is None


def test_serial_stop_latches_and_clear_releases_latch():
    handler = FakeHandler()
    lease = ControlLease(handler)
    protocol = _SerialProtocol(handler, lease, "tty-test")
    protocol._transport = FakeTransport()

    _run(protocol, _lease(commands_pb2.LeaseCommand.ACTION_ACQUIRE))
    _run(protocol, _lease(commands_pb2.LeaseCommand.ACTION_STOP))
    response = _responses(protocol)[-1]
    assert response.lease_response.status == responses_pb2.LeaseResponse.STATUS_STOPPED
    assert lease.stopped is True

    _run(protocol, _lease(commands_pb2.LeaseCommand.ACTION_CLEAR_STOP))
    response = _responses(protocol)[-1]
    assert response.lease_response.status == responses_pb2.LeaseResponse.STATUS_CLEARED
    assert lease.stopped is False


def test_serial_stop_request_returns_stop_ack():
    handler = FakeHandler()
    lease = ControlLease(handler)
    protocol = _SerialProtocol(handler, lease, "tty-test")
    protocol._transport = FakeTransport()

    stop = envelope_pb2.Envelope()
    stop.stop.status = "request"
    stop.stop.request_id = "stop-1"
    _run(protocol, stop)
    response = _responses(protocol)[-1]
    assert response.WhichOneof("body") == "stop_ack"
    assert response.stop_ack.status == "stopped"
    assert response.stop_ack.software_stopped is True
    assert lease.stopped is True
