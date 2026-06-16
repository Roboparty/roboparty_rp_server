# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""Serial transport — AT protocol over UART."""

import asyncio
import logging

try:
    import serial_asyncio
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

from ..protocol.at_parser import AtCommand

logger = logging.getLogger("rp_server.serial")


class SerialATServer:
    """Async serial port server — one client per port, line-based AT protocol."""

    def __init__(self, port: str, baudrate: int, at_handler):
        self._port = port
        self._baudrate = baudrate
        self._handler = at_handler
        self._transport = None
        self._buffer = b""

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
    def __init__(self, at_handler):
        self._handler = at_handler
        self._buffer = b""

    def connection_made(self, transport):
        self._transport = transport
        logger.info("serial client connected")

    def data_received(self, data: bytes):
        self._buffer += data
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            self._handle_line(line.decode("utf-8", errors="replace").strip())

    def connection_lost(self, exc):
        logger.info("serial client disconnected")

    def _handle_line(self, line: str):
        cmd = AtCommand.parse(line)
        if cmd is None:
            return
        asyncio.ensure_future(self._dispatch(cmd))

    async def _dispatch(self, cmd: AtCommand):
        try:
            for resp in await self._handler.dispatch(cmd):
                self._transport.write((resp + "\r\n").encode())
        except Exception as exc:
            logger.warning("serial AT error: %s", exc)
