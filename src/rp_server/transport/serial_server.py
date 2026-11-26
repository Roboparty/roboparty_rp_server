# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Serial transport — length-delimited protobuf frames over UART.

Serial is a trusted, point-to-point link. It participates in the same control
lease as WebSocket clients: read-only queries pass through, while motion,
policy and reset commands require an explicit ``LeaseCommand`` handshake.
"""

import asyncio
import logging
import time

try:
    import serial_asyncio
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

from roboparty.v1 import auth_pb2, commands_pb2, responses_pb2
from ..protocol.codec import Envelope, StreamDecoder, frame_stream
from ..protocol.control_lease import ControlError

logger = logging.getLogger("rp_server.serial")

_LeaseStatus = responses_pb2.LeaseResponse.Status
_StopAck = auth_pb2.StopAck


class SerialServer:
    """Async serial port server — one client per port, framed protobuf."""

    def __init__(self, port: str, baudrate: int, handler, lease):
        self._port = port
        self._baudrate = baudrate
        self._handler = handler
        self._lease = lease
        self._transport = None
        self._watchdog_task = None

    async def start(self):
        if not HAS_SERIAL:
            logger.warning("pyserial-asyncio not available — serial disabled")
            return
        try:
            loop = asyncio.get_running_loop()
            self._transport, _ = await serial_asyncio.create_serial_connection(
                loop, lambda: _SerialProtocol(self._handler, self._lease, self._port),
                self._port, baudrate=self._baudrate,
            )
            self._watchdog_task = asyncio.create_task(self._lease_watchdog())
            logger.info("serial transport ready: %s @ %d", self._port, self._baudrate)
        except Exception as exc:
            logger.error("serial open failed %s: %s", self._port, exc)

    async def _lease_watchdog(self):
        try:
            while True:
                await asyncio.sleep(0.1)
                await self._lease.expire()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("serial lease watchdog: %s", exc)

    async def stop(self):
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None


class _SerialProtocol(asyncio.Protocol):
    def __init__(self, handler, lease, port):
        self._handler = handler
        self._lease = lease
        self._session = f"serial:{port}:{id(self):x}"
        self._transport = None
        self._decoder = StreamDecoder()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker = None

    def connection_made(self, transport):
        self._transport = transport
        self._worker = asyncio.create_task(self._run())
        logger.info("serial client connected")

    def data_received(self, data: bytes):
        try:
            for env in self._decoder.feed(data):
                self._queue.put_nowait(env)
        except ValueError as exc:
            logger.warning("serial framing error: %s", exc)

    def connection_lost(self, exc):
        logger.info("serial client disconnected")
        self._queue.put_nowait(None)
        self._transport = None
        try:
            asyncio.ensure_future(self._release())
        except RuntimeError:
            pass

    async def _run(self):
        while True:
            env = await self._queue.get()
            if env is None:
                return
            await self._dispatch(env)

    async def _release(self):
        try:
            if self._lease.owner == self._session:
                await self._lease.release(self._session, "disconnect")
        except Exception as exc:
            logger.warning("serial lease release failed: %s", exc)

    async def _dispatch(self, env):
        body = env.WhichOneof("body")
        try:
            if body == "lease_command":
                await self._handle_lease(env.lease_command)
                return
            if body == "query":
                responses = await self._handler.handle(env)
            elif body == "stop":
                responses = await self._handle_stop(env.stop)
            else:
                responses = await self._lease.dispatch(self._session, env)
            for response in responses:
                self._send(response)
        except ControlError as exc:
            self._send_error(exc.code, str(exc))
        except Exception as exc:
            logger.warning("serial command error: %s", exc)
            self._send_error("INTERNAL", str(exc))

    async def _handle_lease(self, cmd):
        request_id = cmd.request_id
        try:
            if cmd.action == commands_pb2.LeaseCommand.ACTION_ACQUIRE:
                status = await self._lease.acquire(self._session)
                self._send_lease(_LeaseStatus.STATUS_ACQUIRED, request_id, status, "acquired")
            elif cmd.action == commands_pb2.LeaseCommand.ACTION_RELEASE:
                status = await self._lease.release(self._session)
                self._send_lease(_LeaseStatus.STATUS_RELEASED, request_id, status, "released")
            elif cmd.action == commands_pb2.LeaseCommand.ACTION_HEARTBEAT:
                await self._lease.heartbeat(self._session)
                self._send_lease(_LeaseStatus.STATUS_HEARTBEAT, request_id,
                                 self._lease.status("active"), "")
            elif cmd.action == commands_pb2.LeaseCommand.ACTION_STOP:
                await self._lease.stop(latch=True)
                self._send_lease(_LeaseStatus.STATUS_STOPPED, request_id,
                                 self._lease.status("stopped"), "software stop latched")
            elif cmd.action == commands_pb2.LeaseCommand.ACTION_CLEAR_STOP:
                status = await self._lease.clear_stop()
                self._send_lease(_LeaseStatus.STATUS_CLEARED, request_id,
                                 status, "software stop cleared")
            else:
                self._send_lease(_LeaseStatus.STATUS_ERROR, request_id, {},
                                 f"unknown lease action: {cmd.action}")
        except ControlError as exc:
            status = (_LeaseStatus.STATUS_BUSY if exc.code == "CONTROL_BUSY"
                      else _LeaseStatus.STATUS_ERROR)
            self._send_lease(status, request_id, {}, f"{exc.code}: {exc}")

    async def _handle_stop(self, stop):
        try:
            if stop.status == "clear":
                await self._lease.clear_stop()
                ack = _StopAck(
                    status="cleared",
                    request_id=stop.request_id,
                    state=_StopAck.STATE_STOPPED,
                    confirmed=True,
                    reason="software stop latch cleared",
                    software_stopped=False,
                    motor_state="unknown",
                    estop_state="unknown",
                )
            else:
                await self._lease.stop(latch=True)
                ack = _StopAck(
                    status="stopped",
                    request_id=stop.request_id,
                    state=_StopAck.STATE_STOPPED,
                    confirmed=True,
                    reason="software stop confirmed; motor/e-stop state not verified",
                    software_stopped=True,
                    motor_state="unknown",
                    estop_state="unknown",
                )
        except ControlError as exc:
            ack = _StopAck(
                status="failed",
                request_id=stop.request_id,
                state=_StopAck.STATE_FAILED,
                confirmed=False,
                reason=str(exc),
                motor_state="unknown",
                estop_state="unknown",
            )
        ack.confirmed_at_ms = int(time.time() * 1000)
        env = Envelope()
        env.header.timestamp_ms = ack.confirmed_at_ms
        env.stop_ack.CopyFrom(ack)
        self._send(env)
        return []

    def _send_lease(self, status, request_id, lease_status, message):
        env = Envelope()
        env.header.timestamp_ms = int(time.time() * 1000)
        env.lease_response.CopyFrom(responses_pb2.LeaseResponse(
            status=status,
            request_id=request_id,
            ttl_ms=int(lease_status.get("ttl_ms", 0)),
            input_timeout_ms=int(lease_status.get("input_timeout_ms", 0)),
            message=message,
        ))
        self._send(env)

    def _send_error(self, code, message):
        env = Envelope()
        env.header.timestamp_ms = int(time.time() * 1000)
        env.error.code = 1
        env.error.message = f"{code}: {message}"
        self._send(env)

    def _send(self, env):
        if not self._transport:
            return
        try:
            self._transport.write(frame_stream(env))
        except Exception as exc:
            logger.warning("serial write failed: %s", exc)
