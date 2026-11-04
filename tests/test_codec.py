# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Protobuf codec + framing tests."""

from roboparty.v1 import commands_pb2, envelope_pb2

from rp_server.protocol.codec import (
    CODEC, StreamDecoder, frame_stream, frame_udp, unframe_udp,
)


def _button_env(name=commands_pb2.Button.BUTTON_A, down=True, event_id=7) -> envelope_pb2.Envelope:
    env = envelope_pb2.Envelope()
    env.header.timestamp_ms = 123
    env.header.sequence = 1
    env.button.button = name
    env.button.state = (
        commands_pb2.ButtonState.BUTTON_STATE_DOWN if down
        else commands_pb2.ButtonState.BUTTON_STATE_UP
    )
    env.button.id = event_id
    return env


def test_protobuf_roundtrip():
    env = _button_env()
    decoded = CODEC.decode(CODEC.encode(env))
    assert decoded.WhichOneof("body") == "button"
    assert decoded.button.state == commands_pb2.ButtonState.BUTTON_STATE_DOWN
    assert decoded.button.id == 7
    assert decoded.header.sequence == 1


def test_udp_framing_roundtrip():
    env = _button_env()
    framed = frame_udp(env)
    assert framed[0] == 0x52 and framed[1] == 1
    decoded = unframe_udp(framed)
    assert decoded is not None
    assert decoded.button.id == 7


def test_udp_framing_rejects_garbage():
    assert unframe_udp(b"") is None
    assert unframe_udp(b"\x00\x01\x02") is None
    assert unframe_udp(b"\x52\x99" + b"\x00" * 4) is None  # bad version


def test_stream_framing_single():
    env = _button_env(event_id=1)
    decoder = StreamDecoder()
    out = list(decoder.feed(frame_stream(env)))
    assert len(out) == 1 and out[0].button.id == 1


def test_stream_framing_multiple_in_one_chunk():
    frames = frame_stream(_button_env(event_id=1)) + frame_stream(_button_env(event_id=2))
    got = list(StreamDecoder().feed(frames))
    assert [e.button.id for e in got] == [1, 2]


def test_stream_framing_byte_by_byte():
    frames = frame_stream(_button_env(event_id=1)) + frame_stream(_button_env(event_id=2))
    decoder = StreamDecoder()
    got = []
    for byte in frames:
        got.extend(decoder.feed(bytes([byte])))
    assert [e.button.id for e in got] == [1, 2]
