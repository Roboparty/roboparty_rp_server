# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""TLS certificate helpers (standard library certificates, no custom crypto)."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("rp_server.tls")


def cert_spki_sha256(path: str | Path) -> Optional[str]:
    if not path:
        return None
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        certificate = x509.load_pem_x509_certificate(Path(path).read_bytes())
        der = certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return hashlib.sha256(der).hexdigest()
    except Exception:
        return None


def _default_sans() -> list[str]:
    import socket
    sans = {"localhost", "roboparty", socket.gethostname()}
    try:
        import psutil
        for addresses in psutil.net_if_addrs().values():
            for address in addresses:
                if address.family in (socket.AF_INET, socket.AF_INET6):
                    sans.add(address.address.split("%", 1)[0])
    except Exception:
        pass
    return sorted(sans)


def ensure_self_signed(cert_path, key_path, common_name: str = "roboparty",
                       sans: list[str] | None = None) -> bool:
    """Create a self-signed cert/key pair if missing. Returns True if usable."""
    cert_path = Path(cert_path)
    key_path = Path(key_path)
    if cert_path.is_file() and key_path.is_file():
        return True
    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except Exception:
        return False

    cert_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    names = []
    for value in sans or _default_sans():
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(value)))
        except ValueError:
            names.append(x509.DNSName(value))
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
    )
    cert = builder.sign(key, hashes.SHA256())
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
    logger.info("generated self-signed TLS certificate: %s", cert_path)
    return True
