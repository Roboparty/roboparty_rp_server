# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""App authentication: registered-key challenge + short-lived JWT.

The app proves possession of the private key whose public key was registered
during pairing. Tokens are standard JWTs signed by the robot's Ed25519 device
key (EdDSA); this is the only app-facing auth path for the JSON/WSS gateway.
"""

from __future__ import annotations

import base64
import time
from typing import Optional

import jwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

ISSUER = "rp_server"
DEFAULT_TTL = 900


class AuthError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def issue_token(private_key, subject: str, scopes: list[str],
                ttl: int = DEFAULT_TTL) -> tuple[str, int]:
    now = int(time.time())
    expires = now + ttl
    token = jwt.encode({
        "iss": ISSUER,
        "sub": subject,
        "scope": " ".join(scopes),
        "iat": now,
        "exp": expires,
    }, private_key, algorithm="EdDSA")
    return token, expires * 1000


def verify_token(public_key, token: str) -> dict:
    try:
        return jwt.decode(token, public_key, algorithms=["EdDSA"], issuer=ISSUER,
                          options={"require": ["iss", "sub", "iat", "exp"]})
    except jwt.PyJWTError as exc:
        raise AuthError("INVALID_TOKEN", str(exc)) from exc


def verify_app_signature(app: dict, message: str, signature_b64: str) -> bool:
    """Verify an ECDSA-P256 or Ed25519 signature from a registered app key."""
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        public_key = serialization.load_der_public_key(
            base64.b64decode(app["publicKey"], validate=True))
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, message.encode(), ec.ECDSA(hashes.SHA256()))
            return True
        if isinstance(public_key, ed25519.Ed25519PublicKey):
            public_key.verify(signature, message.encode())
            return True
    except (InvalidSignature, KeyError, ValueError, TypeError):
        return False
    return False


def has_scope(claims: dict, scope: str) -> bool:
    return scope in str(claims.get("scope", "")).split()
