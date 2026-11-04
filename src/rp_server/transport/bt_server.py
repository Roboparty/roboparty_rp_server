# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Bluetooth transport — length-delimited protobuf frames over RFCOMM."""

import asyncio
import logging
import socket

from ..protocol.codec import StreamDecoder, frame_stream

logger = logging.getLogger("rp_server.bluetooth")

try:
    import bluetooth as _bt  # noqa — check availability
    HAS_BT = True
except ImportError:
    HAS_BT = False


class BTServer:
    """Async Bluetooth RFCOMM server — one client at a time, framed protobuf."""

    def __init__(self, handler, channel: int = 1):
        self._handler = handler
        self._channel = channel
        self._server: asyncio.AbstractServer | None = None

    async def start(self):
        if not HAS_BT:
            logger.warning("pybluez not available — Bluetooth disabled")
            return
        try:
            self._server = await asyncio.start_server(
                self._handle_client, "00:00:00:00:00:00", self._channel,
            )
            logger.info("Bluetooth transport ready: RFCOMM channel %d", self._channel)
        except Exception as exc:
            logger.error("Bluetooth open failed: %s", exc)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        logger.info("Bluetooth client connected: %s", addr)
        decoder = StreamDecoder()
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                for env in decoder.feed(chunk):
                    for resp in await self._handler.handle(env):
                        writer.write(frame_stream(resp))
                        await writer.drain()
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        except ValueError as exc:
            logger.warning("Bluetooth framing error: %s", exc)
        except Exception as exc:
            logger.warning("Bluetooth client error: %s", exc)
        finally:
            logger.info("Bluetooth client disconnected: %s", addr)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
