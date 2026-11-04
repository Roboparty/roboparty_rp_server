# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""UDP auth + software-stop security tests."""

import asyncio
import hashlib
import hmac

from roboparty.v1 import envelope_pb2

from rp_server.transport.udp_listener import UDPJoyListener
from rp_server.auth.udp_auth import UDPAuthenticator
from rp_server.auth.udp_session import SessionState, UDPSession


class FakeJoy:
    def __init__(self):
        self.reset_count = 0

    def reset(self):
        self.reset_count += 1


class FakeHandler:
    def __init__(self):
        self.joy = FakeJoy()


class FakeTransport:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))


def _sign(secret: str, device_id: str, challenge: str) -> str:
    return hmac.new(
        secret.encode(), f"{device_id}:{challenge}".encode(), hashlib.sha256
    ).hexdigest()


def test_placeholder_secret_is_replaced():
    auth = UDPAuthenticator("your-pre-shared-secret-key")
    assert auth._secret_key != "your-pre-shared-secret-key"
    assert len(auth._secret_key) == 64


def test_auth_flow_does_not_log_secret_or_signature(caplog):
    secret = "top-secret-value"
    auth = UDPAuthenticator(secret)
    addr = ("127.0.0.1", 1234)
    challenge = auth.generate_challenge(addr, "dev")

    with caplog.at_level("DEBUG", logger="rp_server.udp.auth"):
        assert auth.verify_signature(addr, "dev", "deadbeef") is None
        challenge = auth.generate_challenge(addr, "dev")
        token = auth.verify_signature(
            addr, "dev", _sign(secret, "dev", challenge)
        )

    assert token
    assert secret not in caplog.text
    assert "deadbeef" not in caplog.text
    assert auth.verify_token(token) == {"sub": "dev"}


def _listener():
    handler = FakeHandler()
    listener = UDPJoyListener(handler, secret_key="test-secret", session_timeout=60)
    listener._transport = FakeTransport()

    async def _noop():
        return None

    listener._run_software_stop = _noop
    addr = ("127.0.0.1", 5555)
    listener._sessions.add_session(UDPSession(
        addr=addr, device_id="dev", state=SessionState.CONNECTED,
    ))
    token = listener._auth._generate_token("dev")
    return listener, addr, token


def test_stop_requires_token_and_does_not_latch():
    listener, addr, _token = _listener()
    env = envelope_pb2.Envelope()
    env.stop.SetInParent()

    async def scenario():
        listener._process(env, addr)
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert listener._stop_latched is False
    assert listener._stop_ack_tasks == {}
    assert listener._handler.joy.reset_count == 0


def test_authorized_stop_latches_and_can_be_cleared():
    listener, addr, token = _listener()

    async def scenario():
        stop = envelope_pb2.Envelope()
        stop.stop.token = token
        listener._process(stop, addr)
        assert listener._stop_latched is True
        assert listener._stop_ack_tasks

        clear = envelope_pb2.Envelope()
        clear.stop.token = token
        clear.stop.status = "clear"
        listener._process(clear, addr)
        assert listener._stop_latched is False

    asyncio.run(scenario())
    assert listener._handler.joy.reset_count == 1


def test_stop_ack_can_be_confirmed():
    listener, addr, token = _listener()

    async def scenario():
        stop = envelope_pb2.Envelope()
        stop.stop.token = token
        listener._process(stop, addr)
        assert listener._stop_ack_tasks

        ack = envelope_pb2.Envelope()
        ack.stop.status = "received"
        listener._process(ack, addr)
        assert listener._stop_ack_tasks == {}

    asyncio.run(scenario())
