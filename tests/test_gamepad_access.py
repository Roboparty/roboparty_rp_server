import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from roboparty.v1 import envelope_pb2
from rp_server.protocol.gamepad import AXIS_NAMES, BTN_NAMES, WsEnvelopeSink


@pytest.mark.asyncio
async def test_gamepad_auth_and_continuous_full_snapshot():
    sink = WsEnvelopeSink(ws_url="ws://127.0.0.1:9000/ws", token="x" * 32)
    queue = asyncio.Queue()
    await queue.put(json.dumps({"type": "lease", "status": "acquired"}))
    socket = AsyncMock()
    socket.recv.side_effect = queue.get
    with patch("websockets.legacy.client.connect", AsyncMock(return_value=socket)) as connect:
        await sink.connect()
        await sink.send_joy("lx", 0.5)
        await asyncio.sleep(0.065)
        connect.assert_awaited_once()
        assert connect.call_args.kwargs["extra_headers"]["Authorization"] == "Bearer " + "x" * 32
        frames = [call.args[0] for call in socket.send.await_args_list if isinstance(call.args[0], bytes)]
        assert len(frames) >= 4
        envelope = envelope_pb2.Envelope.FromString(frames[-1])
        assert len(envelope.control.axes) == len(AXIS_NAMES)
        assert len(envelope.control.buttons) == len(BTN_NAMES)
        assert envelope.control.axes[0].value == 0.5
        await queue.put(json.dumps({"type": "error", "code": "LEASE_REQUIRED"}))
        await asyncio.sleep(0.03)
        assert not sink._active
        calls = socket.send.await_count
        await asyncio.sleep(0.03)
        assert socket.send.await_count == calls
        with pytest.raises(RuntimeError, match="reconnect explicitly"):
            await sink.send_joy("lx", 1)
        assert connect.await_count == 1
        await sink.close()


@pytest.mark.asyncio
async def test_gamepad_busy_does_not_send_inputs():
    sink = WsEnvelopeSink(ws_url="ws://127.0.0.1:9000/ws", token="x" * 32)
    socket = AsyncMock()
    socket.recv.return_value = json.dumps({"type": "error", "code": "CONTROL_BUSY"})
    with patch("websockets.legacy.client.connect", AsyncMock(return_value=socket)):
        with pytest.raises(RuntimeError, match="CONTROL_BUSY"):
            await sink.connect()
        assert all(isinstance(call.args[0], str) for call in socket.send.await_args_list)
        socket.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_gamepad_requires_credentials_before_network():
    sink = WsEnvelopeSink(ws_url="ws://127.0.0.1:9000/ws", token="")
    with patch("websockets.legacy.client.connect", AsyncMock()) as connect:
        with pytest.raises(RuntimeError, match="RP_SERVICE_TOKEN"):
            await sink.connect()
        connect.assert_not_awaited()
