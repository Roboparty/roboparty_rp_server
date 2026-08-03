# SPDX-License-Identifier: GPL-3.0

"""Unit tests — run: PYTHONPATH=src python3 -m pytest tests/ -q"""

from rp_server.protocol.at_parser import AtCommand, CmdType
from rp_server.auth.jwt_util import encode_jwt, decode_jwt
from rp_server.auth.store import AuthStore
from rp_server.chat.session import ChatStore
from rp_server.gamepad.bridge import map_btn, map_axis
from rp_server.mcp.tools import tool_is_readonly
from rp_server.transport.ws_server import _missing_hardware


def test_parse_btn():
    cmd = AtCommand.parse("AT+BTN=a,down,3")
    assert cmd is not None
    assert cmd.cmd == CmdType.BTN
    assert cmd.args == ["a", "down", "3"]


def test_parse_joy():
    cmd = AtCommand.parse("AT+JOY=lx,-0.25")
    assert cmd is not None
    assert cmd.cmd == CmdType.JOY


def test_jwt_roundtrip():
    tok = encode_jwt({"sub": "u1"}, "secret", ttl_sec=60)
    payload = decode_jwt(tok, "secret")
    assert payload["sub"] == "u1"


def test_auth_qr_flow():
    store = AuthStore(qr_ttl_sec=60, jwt_secret="s", jwt_ttl_sec=60)
    ch = store.create_challenge()
    store.mark_scanned(ch.challenge_id, "user", "tok")
    got = store.consume(ch.challenge_id)
    assert got.token == "tok"
    assert got.status == "consumed"


def test_chat_session():
    store = ChatStore(max_history=4)
    s = store.get_or_create()
    store.append(s, "system", "ctx")
    store.append(s, "user", "hi")
    store.append(s, "assistant", "hello")
    assert store.get(s.session_id) is not None
    assert len(s.messages) == 3


def test_gamepad_maps():
    assert map_btn("dji", "A") == "a"
    assert map_axis("g12", "ABS_X") == "lx"


def test_mcp_readonly_flags():
    assert tool_is_readonly("robot_sysinfo") is True
    assert tool_is_readonly("robot_button") is False


def test_required_hardware_status():
    required = ("motors", "imu", "bms")
    assert _missing_hardware(
        {"motors": True, "imu": True, "bms": True, "joy": False},
        required,
    ) == []
    assert _missing_hardware(
        {"motors": True, "imu": False, "bms": False},
        required,
    ) == ["imu", "bms"]
