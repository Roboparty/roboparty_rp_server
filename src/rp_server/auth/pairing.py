# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Local pairing: one-time code + registered app public keys.

Flow:
1. Operator runs ``rp-server-pair code`` on the robot (localhost only).
2. App sends ``POST /pair/register`` with that code and its public key.
3. The server stores the app key in ``/etc/rp-server/auth/apps.json`` (0600).

The code is one-time and short-lived; it is generated on localhost so a remote
app cannot self-approve.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from typing import Optional

logger = logging.getLogger("rp_server.pairing")

DEFAULT_APPS = Path("/etc/rp-server/auth/apps.json")
CODE_TTL = 300
MAX_ATTEMPTS = 3
DEFAULT_SCOPES = ("read", "control")


class PairingError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _atomic_json(path: Path, data: dict):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".apps-", delete=False) as stream:
            name = stream.name
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _key_info(public_key_b64: str) -> tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519

    try:
        der = base64.b64decode(public_key_b64, validate=True)
        key = serialization.load_der_public_key(der)
    except Exception as exc:
        raise PairingError("INVALID_PUBLIC_KEY", f"invalid app public key: {exc}") from exc
    if not isinstance(key, (ec.EllipticCurvePublicKey, ed25519.Ed25519PublicKey)):
        raise PairingError("INVALID_PUBLIC_KEY", "unsupported app key type")
    key_id = hashlib.sha256(der).hexdigest()[:16]
    return key_id, base64.b64encode(der).decode("ascii")


class PairingManager:
    def __init__(self, apps_path: Path = DEFAULT_APPS, ttl: int = CODE_TTL,
                 now=time.time, single_owner: bool = False,
                 preserve_admin: bool = True):
        self.apps_path = Path(apps_path)
        self.ttl = ttl
        self._now = now
        self.single_owner = bool(single_owner)
        self.preserve_admin = bool(preserve_admin)
        self._lock = threading.Lock()
        self._codes: dict[str, dict] = {}

    def _clean(self):
        now = self._now()
        for code in list(self._codes):
            if self._codes[code]["expires"] < now:
                del self._codes[code]

    def generate_code(self) -> dict:
        with self._lock:
            self._clean()
            code = f"{secrets.randbelow(1_000_000):06d}"
            expires = self._now() + self.ttl
            self._codes[code] = {"expires": expires, "attempts": 0}
            return {"code": code, "expiresAt": expires, "ttl": self.ttl}

    def _load_apps(self) -> dict:
        try:
            data = json.loads(self.apps_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.warning("cannot read apps.json: %s", exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _save_apps(self, apps: dict):
        _atomic_json(self.apps_path, apps)

    def register(self, code: str, public_key: str, device_name: str = "") -> dict:
        with self._lock:
            self._clean()
            entry = self._codes.get(code)
            if entry is None:
                raise PairingError("PAIR_CODE_INVALID", "pair code is invalid or expired")
            if entry["attempts"] >= MAX_ATTEMPTS:
                del self._codes[code]
                raise PairingError("PAIR_CODE_LOCKED", "too many attempts")
            entry["attempts"] += 1
            key_id, normalized = _key_info(public_key)
            apps = self._load_apps()
            replaced = []
            if self.single_owner:
                for other_id, other in apps.items():
                    if other_id == key_id or other.get("revoked"):
                        continue
                    if self.preserve_admin and "admin" in set(other.get("scopes") or []):
                        continue
                    other["revoked"] = True
                    other["revokedAt"] = datetime.datetime.now(
                        datetime.timezone.utc).isoformat()
                    other["revokedReason"] = "replaced-by-new-pairing"
                    other["replacedBy"] = key_id
                    replaced.append(other_id)
            app = {
                "appKeyId": key_id,
                "publicKey": normalized,
                "deviceName": device_name[:80],
                "scopes": list(DEFAULT_SCOPES),
                "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "revoked": False,
            }
            apps[key_id] = app
            self._save_apps(apps)
            del self._codes[code]
            logger.info("paired app %s (%s); replaced=%d", key_id,
                        device_name[:40], len(replaced))
            public_app = dict(app)
            public_app["replaced"] = replaced
            return public_app

    def get_app(self, app_key_id: str) -> Optional[dict]:
        with self._lock:
            return self._load_apps().get(app_key_id)

    def list_apps(self) -> list[dict]:
        with self._lock:
            return list(self._load_apps().values())

    def revoke(self, app_key_id: str) -> bool:
        with self._lock:
            apps = self._load_apps()
            app = apps.get(app_key_id)
            if app is None:
                return False
            app["revoked"] = True
            app["revokedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self._save_apps(apps)
            return True
