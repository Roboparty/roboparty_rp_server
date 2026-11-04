# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Per-robot Ed25519 identity key.

The private key is provisioned per board at ``/etc/rp-server/auth/device.key``
(mode 0600, never in git). ``/identity`` exposes the public SPKI SHA-256 so an
app can pin the robot it first paired with.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("rp_server.identity")

DEFAULT_PATH = Path("/etc/rp-server/auth/device.key")


def load_or_create(path: Path = DEFAULT_PATH):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        if path.stat().st_mode & 0o077:
            os.chmod(path, 0o600)
            logger.warning("device key permissions tightened to 0600: %s", path)
        return Ed25519PrivateKey.from_private_bytes(path.read_bytes())
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    logger.info("generated device key: %s", path)
    return key


def public_key_info(key) -> tuple[str, str]:
    """Return ``(spki_sha256_hex, spki_base64)`` for an Ed25519 private key."""
    from cryptography.hazmat.primitives import serialization

    der = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest(), base64.b64encode(der).decode("ascii")


def identity_fields(config: Optional[dict] = None) -> dict:
    config = config or {}
    key_path = Path(config.get("device_key") or os.environ.get("RP_DEVICE_KEY")
                    or DEFAULT_PATH)
    try:
        key = load_or_create(key_path)
        digest, spki = public_key_info(key)
    except Exception as exc:
        logger.warning("device key unavailable: %s", exc)
        return {"spkiSha256": None, "devicePublicKey": None, "deviceKeySource": "unavailable"}
    return {"spkiSha256": digest, "devicePublicKey": spki, "deviceKeySource": str(key_path)}
