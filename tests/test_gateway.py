# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

import asyncio
import json
import socket
import unittest

try:
    import websockets
except ImportError:  # optional local dev dependency
    websockets = None

from rp_server.gateway import Gateway
from rp_server.protocol.codec import Envelope, StreamDecoder, frame_stream


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(websockets is not None, "websockets is not installed")
class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def test_ble_writer_chunks_by_mtu(self):
        from rp_server.ble_gatt import BleLink
        link = BleLink(mtu=20)
        link.writer.write(b"x" * 45)
        sizes = []
        while not link._outgoing.empty():
            sizes.append(len(link._outgoing.get_nowait()))
        self.assertEqual(sizes, [20, 20, 5])

    async def test_tcp_link_relays_envelope_and_lease(self):
        received = {}

        async def handler(connection):
            async for message in connection:
                if isinstance(message, str):
                    if json.loads(message).get("type") == "lease.acquire":
                        await connection.send(json.dumps(
                            {"type": "lease", "status": "acquired"}))
                    continue
                received["bytes"] = message
                await connection.send(message)

        server = await websockets.serve(handler, "127.0.0.1", 0)
        ws_port = server.sockets[0].getsockname()[1]
        link_port = free_port()
        gateway = Gateway(f"tcp://127.0.0.1:{link_port}",
                          f"ws://127.0.0.1:{ws_port}/ws", "x" * 32)
        task = asyncio.create_task(gateway.run())
        try:
            await asyncio.sleep(0.2)
            reader, writer = await asyncio.open_connection("127.0.0.1", link_port)
            envelope = Envelope()
            envelope.joystick.axis = 1
            envelope.joystick.value = 0.5
            writer.write(frame_stream(envelope))
            await writer.drain()

            decoder = StreamDecoder()
            reply = None
            for _ in range(20):
                data = await asyncio.wait_for(reader.read(4096), timeout=1)
                for item in decoder.feed(data):
                    reply = item
                    break
                if reply is not None:
                    break
            self.assertIsNotNone(reply)
            self.assertEqual(reply.joystick.axis, 1)
            self.assertEqual(reply.joystick.value, 0.5)
            self.assertIn("bytes", received)
            writer.close()
            await writer.wait_closed()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
