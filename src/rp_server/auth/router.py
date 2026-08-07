# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""QR-code login API: challenge → scan → poll JWT."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .jwt_util import decode_jwt, encode_jwt

router = APIRouter(prefix="/auth", tags=["auth"])


class ScanBody(BaseModel):
    challenge_id: str
    user_id: str = Field(default="app_user", min_length=1)


def _store(request: Request):
    store = request.app.state.rp.auth_store
    if store is None:
        raise HTTPException(503, "auth disabled")
    return store


def _cfg(request: Request) -> dict:
    return request.app.state.rp.config.get("auth", {})


@router.get("/qr")
async def create_qr(request: Request):
    """Create a login challenge. Client renders QR with payload.url / challenge_id."""
    store = _store(request)
    ch = store.create_challenge()
    host = request.headers.get("host", "127.0.0.1:8765")
    scheme = request.headers.get("x-forwarded-proto", "http")
    payload = {
        "challenge_id": ch.challenge_id,
        "url": f"{scheme}://{host}/auth/scan",
        "expires_in": store.qr_ttl_sec,
        "poll": f"{scheme}://{host}/auth/poll?challenge_id={ch.challenge_id}",
    }
    return {"ok": True, "challenge": payload}


@router.post("/scan")
async def scan_qr(body: ScanBody, request: Request):
    """Mobile app calls this after scanning the QR (marks challenge ready)."""
    store = _store(request)
    secret = os.environ.get("RP_JWT_SECRET") or _cfg(request).get("jwt_secret", "")
    if not secret:
        raise HTTPException(500, "jwt secret not configured")
    token = encode_jwt({"sub": body.user_id, "typ": "access"}, secret, store.jwt_ttl_sec)
    try:
        ch = store.mark_scanned(body.challenge_id, body.user_id, token)
    except KeyError:
        raise HTTPException(404, "unknown challenge")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "status": ch.status, "user_id": ch.user_id}


@router.get("/poll")
async def poll_qr(challenge_id: str, request: Request):
    """Web / head unit polls until status=scanned, then receives JWT once."""
    store = _store(request)
    ch = store.get(challenge_id)
    if ch is None:
        raise HTTPException(404, "unknown challenge")
    if ch.status == "pending":
        return {"ok": True, "status": "pending"}
    if ch.status == "expired":
        return {"ok": False, "status": "expired"}
    if ch.status == "consumed":
        return {"ok": False, "status": "consumed"}
    try:
        ch = store.consume(challenge_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {
        "ok": True,
        "status": "authorized",
        "token": ch.token,
        "user_id": ch.user_id,
        "token_type": "Bearer",
        "expires_in": store.jwt_ttl_sec,
    }


@router.get("/me")
async def me(request: Request, authorization: Optional[str] = Header(default=None)):
    secret = os.environ.get("RP_JWT_SECRET") or _cfg(request).get("jwt_secret", "")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_jwt(token, secret)
    except ValueError as exc:
        raise HTTPException(401, str(exc))
    return {"ok": True, "user_id": payload.get("sub"), "claims": payload}


def require_auth(request: Request, authorization: Optional[str] = Header(default=None)) -> dict:
    """FastAPI dependency — enforces JWT when auth.require_token is true."""
    cfg = _cfg(request)
    if not cfg.get("require_token", False):
        return {"sub": "anonymous"}
    secret = os.environ.get("RP_JWT_SECRET") or cfg.get("jwt_secret", "")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "authorization required")
    try:
        return decode_jwt(authorization.split(" ", 1)[1].strip(), secret)
    except ValueError as exc:
        raise HTTPException(401, str(exc))
