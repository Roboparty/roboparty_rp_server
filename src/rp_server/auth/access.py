# SPDX-License-Identifier: GPL-3.0
"""Shared HTTP/WebSocket credentials, including live pairing revocation."""

import secrets

from .app_auth import AuthError, has_scope, verify_token


class AccessPolicy:
    def __init__(self, key, pairing, service_token="", service_scopes=("read", "control", "admin")):
        if service_token and len(service_token) < 32:
            raise ValueError("RP_SERVICE_TOKEN must contain at least 32 characters")
        if set(service_scopes) - {"read", "control", "admin"}:
            raise ValueError("invalid service_scopes")
        self.key = key
        self.pairing = pairing
        self.service_token = service_token
        self.service_scopes = tuple(service_scopes)

    @staticmethod
    def bearer(header):
        kind, _, token = (header or "").partition(" ")
        if kind.lower() != "bearer" or not token.strip():
            raise AuthError("UNAUTHORIZED", "Bearer credential required")
        return token.strip()

    def verify(self, token, scope="read"):
        if self.service_token and secrets.compare_digest(token.encode(), self.service_token.encode()):
            claims = {"sub": "local-service", "scope": " ".join(self.service_scopes)}
        else:
            if self.key is None:
                raise AuthError("UNAUTHORIZED", "server identity unavailable")
            claims = verify_token(self.key.public_key(), token)
            subject = claims.get("sub")
            app = self.pairing.get_app(subject) if isinstance(subject, str) else None
            if not app or app.get("revoked"):
                raise AuthError("UNAUTHORIZED", "app is unpaired or revoked")
            # A previously issued token cannot retain permissions removed locally.
            allowed = set(app.get("scopes", []))
            claims["scope"] = " ".join(set(str(claims.get("scope", "")).split()) & allowed)
        if scope and not has_scope(claims, scope):
            raise AuthError("FORBIDDEN", f"{scope} scope required")
        return claims
