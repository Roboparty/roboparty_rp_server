# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""Minimal HS256 JWT helpers (stdlib only)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def encode_jwt(payload: dict[str, Any], secret: str, ttl_sec: int = 86400) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    body = dict(payload)
    now = int(time.time())
    body.setdefault("iat", now)
    body.setdefault("exp", now + ttl_sec)
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(body, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


def decode_jwt(token: str, secret: str) -> dict[str, Any]:
    try:
        h, p, s = token.split(".")
    except ValueError as exc:
        raise ValueError("malformed token") from exc
    expect = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url(expect), s):
        raise ValueError("bad signature")
    payload = json.loads(_b64url_decode(p))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("token expired")
    return payload
