# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Serial transport — length-delimited protobuf frames over UART."""

import asyncio
import logging

try:
    import serial_asyncio
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

from ..protocol.codec import StreamDecoder, frame_stream

logger = logging.getLogger("rp_server.serial")


class SerialServer:
    """Async serial port server — one client per port, framed protobuf."""

    def __init__(self, port: str, baudrate: int, handler):
        self._port = port
        self._baudrate = baudrate
        self._handler = handler
        self._transport = None

    async def start(self):
        if not HAS_SERIAL:
            logger.warning("pyserial-asyncio not available — serial disabled")
            return
        try:
            loop = asyncio.get_running_loop()
            self._transport, _ = await serial_asyncio.create_serial_connection(
                loop, lambda: _SerialProtocol(self._handler),
                self._port, baudrate=self._baudrate,
            )
            logger.info("serial transport ready: %s @ %d", self._port, self._baudrate)
        except Exception as exc:
            logger.error("serial open failed %s: %s", self._port, exc)

    async def stop(self):
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None


class _SerialProtocol(asyncio.Protocol):
    def __init__(self, handler):
        self._handler = handler
        self._transport = None
        self._decoder = StreamDecoder()

    def connection_made(self, transport):
        self._transport = transport
        logger.info("serial client connected")

    def data_received(self, data: bytes):
        try:
            for env in self._decoder.feed(data):
                asyncio.ensure_future(self._dispatch(env))
        except ValueError as exc:
            logger.warning("serial framing error: %s", exc)

    def connection_lost(self, exc):
        logger.info("serial client disconnected")

    async def _dispatch(self, env):
        try:
            for resp in await self._handler.handle(env):
                self._transport.write(frame_stream(resp))
        except Exception as exc:
            logger.warning("serial command error: %s", exc)
