# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Local pairing code + registered app public keys."""

import base64
import json
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from rp_server.auth.pairing import PairingError, PairingManager


def app_public_key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(der).decode()


def test_register_is_one_time_and_persists(tmp_path):
    clock = [1000.0]
    manager = PairingManager(tmp_path / 'apps.json', ttl=60, now=lambda: clock[0])
    generated = manager.generate_code()
    app = manager.register(generated['code'], app_public_key(), 'phone')
    assert app['appKeyId'] and app['scopes'] == ['read', 'control']
    assert (tmp_path / 'apps.json').stat().st_mode & 0o777 == 0o600
    stored = json.loads((tmp_path / 'apps.json').read_text())
    assert app['appKeyId'] in stored
    with pytest.raises(PairingError) as exc:
        manager.register(generated['code'], app_public_key(), 'phone')
    assert exc.value.code == 'PAIR_CODE_INVALID'


def test_expired_code_is_rejected(tmp_path):
    clock = [1000.0]
    manager = PairingManager(tmp_path / 'apps.json', ttl=1, now=lambda: clock[0])
    code = manager.generate_code()['code']
    clock[0] += 2
    with pytest.raises(PairingError) as exc:
        manager.register(code, app_public_key())
    assert exc.value.code == 'PAIR_CODE_INVALID'


def test_revoke_and_invalid_key(tmp_path):
    manager = PairingManager(tmp_path / 'apps.json')
    code = manager.generate_code()['code']
    with pytest.raises(PairingError) as exc:
        manager.register(code, 'not-base64')
    assert exc.value.code == 'INVALID_PUBLIC_KEY'

    code = manager.generate_code()['code']
    app = manager.register(code, app_public_key(), 'tablet')
    assert manager.revoke(app['appKeyId']) is True
    listed = manager.list_apps()
    assert listed[0]['revoked'] is True
    assert manager.revoke('missing') is False
