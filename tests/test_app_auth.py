# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Registered-app challenge auth and JWT issuance."""

import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from rp_server.auth import app_auth


def app_key():
    private = ec.generate_private_key(ec.SECP256R1())
    der = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return private, {"publicKey": base64.b64encode(der).decode()}


def test_app_signature_roundtrip():
    private, app = app_key()
    message = "app-key:challenge"
    signature = private.sign(message.encode(), ec.ECDSA(hashes.SHA256()))
    encoded = base64.b64encode(signature).decode()
    assert app_auth.verify_app_signature(app, message, encoded) is True
    assert app_auth.verify_app_signature(app, "other", encoded) is False
    assert app_auth.verify_app_signature(app, message, "not-base64") is False


def test_token_issue_and_verify():
    robot = ed25519.Ed25519PrivateKey.generate()
    token, expires_ms = app_auth.issue_token(robot, "app-1", ["read", "control"])
    claims = app_auth.verify_token(robot.public_key(), token)
    assert claims["sub"] == "app-1"
    assert app_auth.has_scope(claims, "control")
    assert not app_auth.has_scope(claims, "admin")
    assert expires_ms > 0


def test_expired_token_rejected():
    robot = ed25519.Ed25519PrivateKey.generate()
    token, _ = app_auth.issue_token(robot, "app-1", ["read"], ttl=-1)
    with pytest.raises(app_auth.AuthError) as exc:
        app_auth.verify_token(robot.public_key(), token)
    assert exc.value.code == "INVALID_TOKEN"
