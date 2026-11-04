# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Transport gateway: bridge a framed protobuf link to rp_server ``/ws``.

The gateway owns one rp_server control lease and relays length-delimited
``roboparty.v1.Envelope`` frames between the link (TCP, Unix socket or serial)
and rp_server. It is intentionally small: authentication, lease, stop and
telemetry stay in rp_server; the link only carries bytes.

Example:
    python3 -m rp_server.gateway --link tcp://127.0.0.1:9100 \
        --rp-url ws://127.0.0.1:9000/ws --token "$RP_SERVICE_TOKEN"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import ssl
from urllib.parse import parse_qs, urlsplit

from .protocol.codec import CODEC, StreamDecoder, frame_stream

logger = logging.getLogger("rp_server.gateway")


def parse_link(link: str) -> tuple[str, str, int]:
    parsed = urlsplit(link)
    if parsed.scheme == "tcp":
        return "tcp", parsed.hostname or "127.0.0.1", parsed.port or 9100
    if parsed.scheme == "unix":
        return "unix", parsed.path, 0
    if parsed.scheme == "serial":
        port = parsed.path or "/dev/ttyAMA0"
        baud = int(parse_qs(parsed.query).get("baud", ["115200"])[0])
        return "serial", port, baud
    raise ValueError(f"unsupported link: {link}")


class Gateway:
    def __init__(self, link: str, rp_url: str, token: str = "",
                 tls_ca: str = "", tls_insecure: bool = False):
        self.link = link
        self.rp_url = rp_url
        self.token = token or os.environ.get("RP_SERVICE_TOKEN", "")
        self.tls_ca = tls_ca
        self.tls_insecure = tls_insecure
        self._busy = False
        self._lease = asyncio.Event()
        self._ws = None

    async def run(self) -> None:
        if not self.token:
            raise SystemExit("RP_SERVICE_TOKEN is required for the gateway")
        if self.link.startswith("ble://"):
            await self._run_ble()
            return
        if self.link.startswith("nearlink://"):
            raise SystemExit("NearLink adapter is not implemented; "
                             "expose a tcp:// or unix:// link instead")
        kind, target, number = parse_link(self.link)
        logger.info("gateway link=%s target=%s", kind, target,
                    extra={"event_type": "gateway"})
        if kind == "tcp":
            server = await asyncio.start_server(self._accept, target, number)
            async with server:
                await server.serve_forever()
        elif kind == "unix":
            server = await asyncio.start_unix_server(self._accept, target)
            async with server:
                await server.serve_forever()
        else:
            try:
                import serial_asyncio
            except ImportError as exc:
                raise SystemExit("pyserial-asyncio is required for serial links") from exc
            reader, writer = await serial_asyncio.open_serial_connection(
                url=target, baudrate=number)
            await self._serve(reader, writer)

    async def _run_ble(self) -> None:
        from .ble_gatt import BleLink, DEFAULT_RX, DEFAULT_SERVICE, DEFAULT_TX
        parsed = urlsplit(self.link)
        adapter = parsed.netloc or parsed.path.lstrip("/") or "hci0"
        query = parse_qs(parsed.query)
        link = BleLink(
            adapter=adapter,
            local_name=query.get("name", ["RoboParty"])[0],
            service_uuid=query.get("service", [DEFAULT_SERVICE])[0],
            tx_uuid=query.get("tx", [DEFAULT_TX])[0],
            rx_uuid=query.get("rx", [DEFAULT_RX])[0],
            mtu=int(query.get("mtu", ["20"])[0]),
        )
        await link.start()
        try:
            await self._serve(link.reader, link.writer)
        finally:
            await link.stop()

    async def _accept(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        if self._busy:
            logger.warning("gateway link busy; rejecting connection",
                           extra={"event_type": "gateway"})
            writer.close()
            return
        self._busy = True
        asyncio.create_task(self._serve(reader, writer))

    async def _serve(self, reader, writer) -> None:
        try:
            try:
                from websockets.legacy.client import connect
            except ImportError as exc:
                raise SystemExit("websockets is required for the gateway") from exc
            headers = {"Authorization": f"Bearer {self.token}"}
            ssl_arg = None
            if self.tls_insecure:
                ssl_arg = ssl._create_unverified_context()
            elif self.tls_ca:
                ssl_arg = ssl.create_default_context(cafile=self.tls_ca)
            ws = await connect(self.rp_url, extra_headers=headers,
                               subprotocols=["roboparty.v2.proto"], open_timeout=8,
                               ssl=ssl_arg)
            self._ws = ws
            self._lease.clear()
            recv_task = asyncio.create_task(self._recv(ws, writer))
            heartbeat_task = asyncio.create_task(self._heartbeat(ws))
            try:
                await self._acquire(ws)
                await self._send(reader, ws)
            except Exception as exc:
                logger.warning("gateway link ended: %s", exc,
                               extra={"event_type": "gateway"})
            finally:
                for task in (recv_task, heartbeat_task):
                    task.cancel()
                await asyncio.gather(recv_task, heartbeat_task, return_exceptions=True)
                try:
                    if self._lease.is_set():
                        await ws.send(json.dumps({"type": "lease.release"}))
                except Exception:
                    pass
                await ws.close()
                self._ws = None
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            self._busy = False

    async def _acquire(self, ws) -> None:
        if self._lease.is_set():
            return
        await ws.send(json.dumps({"type": "lease.acquire"}))
        await asyncio.wait_for(self._lease.wait(), timeout=3)

    async def _send(self, reader, ws) -> None:
        decoder = StreamDecoder()
        while True:
            data = await reader.read(4096)
            if not data:
                return
            for envelope in decoder.feed(data):
                if not self._lease.is_set():
                    await self._acquire(ws)
                await ws.send(envelope.SerializeToString())

    async def _recv(self, ws, writer) -> None:
        async for message in ws:
            if isinstance(message, bytes):
                try:
                    envelope = CODEC.decode(message)
                except Exception:
                    continue
                writer.write(frame_stream(envelope))
                await writer.drain()
                continue
            try:
                payload = json.loads(message)
            except ValueError:
                continue
            kind = payload.get("type")
            if kind == "lease" and payload.get("status") == "acquired":
                self._lease.set()
                logger.info("gateway lease acquired", extra={"event_type": "gateway"})
            elif kind in ("error", "lease"):
                self._lease.clear()
                logger.warning("gateway lease lost: %s", payload,
                               extra={"event_type": "gateway"})

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(0.5)
            if self._lease.is_set():
                await ws.send(json.dumps({"type": "heartbeat"}))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--link", default="tcp://127.0.0.1:9100",
                        help="tcp://host:port, unix:///path, serial:///dev/ttyAMA0?baud=115200 "
                             "or ble://hci0?name=RoboParty&mtu=20")
    parser.add_argument("--rp-url", default="ws://127.0.0.1:9000/ws")
    parser.add_argument("--token", default=os.environ.get("RP_SERVICE_TOKEN", ""))
    parser.add_argument("--tls-ca", default="", help="CA/cert file for wss")
    parser.add_argument("--tls-insecure", action="store_true",
                        help="disable wss certificate verification (local dev only)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    try:
        asyncio.run(Gateway(args.link, args.rp_url, args.token,
                            tls_ca=args.tls_ca,
                            tls_insecure=args.tls_insecure).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
