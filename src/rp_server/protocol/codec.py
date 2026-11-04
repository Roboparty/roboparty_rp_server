# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Wire codec — Protobuf only.

The contract is ``proto/roboparty/v1`` (generated into ``protocol/gen``); every
message on every transport is an ``Envelope``. The legacy AT/JSON encodings were
removed (see docs/plan-protocol-v1.md).

Framing per transport:
  - WebSocket : one ``Envelope`` per binary frame (no extra framing).
  - UDP       : ``MAGIC`` + ``VERSION`` + ``Envelope`` (magic guards against
                stray datagrams and lets the reader reject old traffic).
  - Serial/BT : varint length-delimited stream of ``Envelope`` messages
                (a byte stream has no message boundaries).
"""

from __future__ import annotations

from typing import Iterable, Optional

from roboparty.v1 import envelope_pb2

#: Re-exported for convenience: the only wire message type.
Envelope = envelope_pb2.Envelope


class ProtobufCodec:
    """Encode/decode a single ``Envelope`` to bytes."""

    name = "protobuf"

    def encode(self, envelope: Envelope) -> bytes:
        return envelope.SerializeToString()

    def decode(self, data: bytes) -> Envelope:
        envelope = Envelope()
        envelope.ParseFromString(data)
        return envelope


#: Default (stateless) codec instance.
CODEC = ProtobufCodec()


# ---------------------------------------------------------------------------
# UDP framing
# ---------------------------------------------------------------------------

UDP_MAGIC = 0x52  # 'R' for RoboParty
UDP_VERSION = 1
UDP_HEADER = bytes((UDP_MAGIC, UDP_VERSION))


def frame_udp(envelope: Envelope) -> bytes:
    return UDP_HEADER + envelope.SerializeToString()


def unframe_udp(data: bytes) -> Optional[Envelope]:
    """Return the Envelope if ``data`` is a valid v1 UDP frame, else None."""
    if len(data) < len(UDP_HEADER) or data[0] != UDP_MAGIC:
        return None
    if data[1] != UDP_VERSION:
        return None
    return CODEC.decode(data[len(UDP_HEADER):])


# ---------------------------------------------------------------------------
# Length-delimited stream framing (serial / Bluetooth)
# ---------------------------------------------------------------------------

def _encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def frame_stream(envelope: Envelope) -> bytes:
    payload = envelope.SerializeToString()
    return _encode_varint(len(payload)) + payload


class StreamDecoder:
    """Incremental decoder for ``frame_stream`` output."""

    def __init__(self, max_size: int = 1 << 20):
        self._buf = bytearray()
        self._max_size = max_size

    def feed(self, data: bytes) -> Iterable[Envelope]:
        self._buf.extend(data)
        while True:
            header = self._read_varint()
            if header is None:
                return
            length, offset = header
            if length > self._max_size:
                raise ValueError(f"frame too large: {length}")
            if len(self._buf) - offset < length:
                return
            payload = bytes(self._buf[offset:offset + length])
            del self._buf[:offset + length]
            yield CODEC.decode(payload)

    def _read_varint(self) -> Optional[tuple[int, int]]:
        value = 0
        shift = 0
        for i, byte in enumerate(self._buf):
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value, i + 1
            shift += 7
            if shift > 63:
                raise ValueError("varint too long")
        return None
