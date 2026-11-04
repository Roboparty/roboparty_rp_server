# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Per-robot Ed25519 device key."""

import base64
import tempfile
from pathlib import Path
from unittest.mock import patch

from rp_server.auth import device_key


def test_key_is_persisted_with_private_permissions():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'device.key'
        first = device_key.load_or_create(path)
        digest1, spki1 = device_key.public_key_info(first)
        second = device_key.load_or_create(path)
        digest2, spki2 = device_key.public_key_info(second)
        assert digest1 == digest2 and spki1 == spki2
        assert len(digest1) == 64
        assert base64.b64decode(spki1)[:2] == b'0*'  # Ed25519 SPKI DER
        assert path.stat().st_mode & 0o777 == 0o600


def test_identity_fields_exposes_spki():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'device.key'
        fields = device_key.identity_fields({'device_key': str(path)})
        assert len(fields['spkiSha256']) == 64
        assert fields['devicePublicKey']
        assert fields['deviceKeySource'] == str(path)


def test_identity_fields_degrades_when_unavailable():
    with patch.object(device_key, 'load_or_create', side_effect=OSError('denied')):
        fields = device_key.identity_fields({})
    assert fields == {'spkiSha256': None, 'devicePublicKey': None,
                      'deviceKeySource': 'unavailable'}
