# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""In-memory QR login challenge store."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QrChallenge:
    challenge_id: str
    status: str = "pending"  # pending | scanned | consumed | expired
    created_at: float = field(default_factory=time.time)
    user_id: str = ""
    token: str = ""


class AuthStore:
    def __init__(self, qr_ttl_sec: int = 120, jwt_secret: str = "", jwt_ttl_sec: int = 86400):
        self.qr_ttl_sec = qr_ttl_sec
        self.jwt_secret = jwt_secret
        self.jwt_ttl_sec = jwt_ttl_sec
        self._challenges: dict[str, QrChallenge] = {}

    def create_challenge(self) -> QrChallenge:
        self._purge()
        cid = secrets.token_urlsafe(16)
        ch = QrChallenge(challenge_id=cid)
        self._challenges[cid] = ch
        return ch

    def get(self, challenge_id: str) -> Optional[QrChallenge]:
        ch = self._challenges.get(challenge_id)
        if not ch:
            return None
        if ch.status == "pending" and time.time() - ch.created_at > self.qr_ttl_sec:
            ch.status = "expired"
        return ch

    def mark_scanned(self, challenge_id: str, user_id: str, token: str) -> QrChallenge:
        ch = self.get(challenge_id)
        if ch is None:
            raise KeyError("unknown challenge")
        if ch.status == "expired":
            raise ValueError("challenge expired")
        if ch.status != "pending":
            raise ValueError(f"invalid status: {ch.status}")
        ch.status = "scanned"
        ch.user_id = user_id
        ch.token = token
        return ch

    def consume(self, challenge_id: str) -> QrChallenge:
        ch = self.get(challenge_id)
        if ch is None:
            raise KeyError("unknown challenge")
        if ch.status == "expired":
            raise ValueError("challenge expired")
        if ch.status != "scanned":
            raise ValueError(f"not ready: {ch.status}")
        ch.status = "consumed"
        return ch

    def _purge(self):
        now = time.time()
        dead = [
            k for k, v in self._challenges.items()
            if now - v.created_at > self.qr_ttl_sec * 2 or v.status in ("consumed", "expired")
        ]
        for k in dead:
            self._challenges.pop(k, None)
