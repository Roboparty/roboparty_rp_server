"""Mock-only HTTP/WS security and cross-protocol ownership regression tests."""

import base64
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from rp_server.auth.app_auth import issue_token
from rp_server.auth.device_key import load_or_create
from rp_server.protocol.codec import Envelope
from rp_server.transport.ws_server import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("RP_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("RP_DEVICE_KEY", raising=False)
    result = create_app({"server": {"mock": True}, "transports": {},
                         "tui": {"enabled": False},
                         "identity": {"device_key": str(tmp_path / "key"),
                                      "apps_path": str(tmp_path / "apps.json")}})
    result.state.test_key = load_or_create(tmp_path / "key")
    result.state.rp.joy.reset = Mock()
    result.state.rp.motors.clear_errors = Mock()
    result.state.rp.policy.stop = AsyncMock()
    return result


def identity(app, scopes=("read", "control"), ttl=900):
    key = ed25519.Ed25519PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    pairing = app.state.pairing
    entry = pairing.register(pairing.generate_code()["code"], pub)
    apps = pairing._load_apps()
    apps[entry["appKeyId"]]["scopes"] = list(scopes)
    pairing._save_apps(apps)
    token, _ = issue_token(app.state.test_key, entry["appKeyId"], list(scopes), ttl)
    return key, entry["appKeyId"], token


def headers(token):
    return {"Authorization": "Bearer " + token}


def text(ws):
    telemetry = {"battery", "imu", "motors", "motor_error_push"}
    for _ in range(100):
        message = ws.receive()
        if message.get("text"):
            import json
            payload = json.loads(message["text"])
            if payload.get("type") in telemetry:
                continue
            return payload
        if message["type"] == "websocket.close":
            raise WebSocketDisconnect(message["code"])
    raise AssertionError("no JSON response")


def authenticate_json(ws, key, subject):
    ws.send_json({"type": "auth_request", "device_id": subject})
    challenge = text(ws)
    signature = base64.b64encode(key.sign(f'{subject}:{challenge["challenge_code"]}'.encode())).decode()
    ws.send_json({"type": "challenge_response", "device_id": subject, "signature": signature})
    assert text(ws)["ok"] is True


def test_http_permissions_expiry_and_revocation(app):
    _, subject, token = identity(app)
    _, _, admin = identity(app, ("read", "control", "admin"))
    _, _, expired = identity(app, ttl=-1)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/tui/health").status_code == 401
        assert client.get("/tui/health", headers=headers(token)).status_code == 200
        assert client.post("/tui/jobs", headers=headers(token), json={"taskId": "can-check"}).status_code == 403
        response = client.post("/tui/jobs", headers=headers(admin), json={"taskId": "can-check"})
        assert response.json()["error"]["code"] == "DISABLED"
        assert client.get("/tui/health", headers=headers(expired)).status_code == 401
        app.state.pairing.revoke(subject)
        assert client.get("/tui/health", headers=headers(token)).status_code == 401


def test_native_ws_requires_auth_and_control_scope(app):
    _, _, token = identity(app, ("read",))
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass
        with client.websocket_connect("/ws", headers=headers(token),
                                     subprotocols=["roboparty.v2.proto"]) as ws:
            ws.receive_bytes()
            ws.send_json({"type": "lease.acquire"})
            assert text(ws)["code"] == "FORBIDDEN"


def test_json_and_native_share_lease_and_reconnect_is_unarmed(app):
    key, subject, token = identity(app)
    with TestClient(app) as client:
        with client.websocket_connect("/ws-json") as json_ws:
            authenticate_json(json_ws, key, subject)
            json_ws.send_json({"type": "lease.acquire"})
            assert text(json_ws)["status"] == "acquired"
            with client.websocket_connect("/ws", headers=headers(token),
                                     subprotocols=["roboparty.v2.proto"]) as ws:
                ws.receive_bytes()
                ws.send_json({"type": "lease.acquire"})
                assert text(ws)["code"] == "CONTROL_BUSY"
                json_ws.send_json({"type": "stop", "status": "request"})
                while text(json_ws).get("type") != "stop":
                    pass
                app.state.rp.motors.clear_errors.assert_not_called()
                json_ws.send_json({"type": "stop", "status": "clear"})
                assert text(json_ws)["status"] == "cleared"
                ws.send_json({"type": "lease.acquire"})
                assert text(ws)["status"] == "acquired"
        with client.websocket_connect("/ws", headers=headers(token),
                                     subprotocols=["roboparty.v2.proto"]) as ws:
            ws.receive_bytes()
            command = Envelope()
            command.joystick.axis = 1
            command.joystick.value = 0.5
            ws.send_bytes(command.SerializeToString())
            assert text(ws)["code"] == "LEASE_REQUIRED"


def test_revocation_closes_idle_session(app):
    _, subject, token = identity(app)
    with TestClient(app) as client:
        with client.websocket_connect("/ws", headers=headers(token),
                                     subprotocols=["roboparty.v2.proto"]) as ws:
            ws.receive_bytes()
            ws.send_json({"type": "lease.acquire"})
            assert text(ws)["status"] == "acquired"
            app.state.pairing.revoke(subject)
            with pytest.raises(WebSocketDisconnect):
                text(ws)
            assert app.state.control.owner is None


def test_unleased_legacy_transport_fails_closed():
    for transport in ("udp", "serial", "bluetooth"):
        with pytest.raises(ValueError, match="Unleased"):
            create_app({"transports": {transport: True}})
    with pytest.raises(ValueError, match="Unleased"):
        create_app({"can_gamepad": {"enabled": True}})
