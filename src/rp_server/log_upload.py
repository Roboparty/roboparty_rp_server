# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Best-effort, restart-safe upload of rp_server logs to roboparty-log-server.

Events are written to a bounded SQLite spool before the network is involved.
A daemon thread drains the spool, so a crash, restart or offline log server does
not lose events. Control threads only pay for a local SQLite insert; uploads are
never on the control path.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import threading
import time
import traceback
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

from . import __version__ as RP_SERVER_VERSION

LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
DEFAULT_URL = "http://127.0.0.1:8092"
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _record_time(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="microseconds")


def _text(value, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit]


def _boot_id() -> str:
    try:
        return BOOT_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class PublicLogPolicy:
    """Allow-list and redaction for public anonymous log submission."""

    DEFAULT_EVENT_TYPES = ("startup", "lease", "inference", "policy", "command", "skill", "log")
    DEFAULT_FIELDS = ("logger", "module", "function", "line")
    IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    PATH = re.compile(r"(?:/[A-Za-z0-9_.-]+){2,}")
    TOKEN = re.compile(r"(?:Bearer\s+\S+|[A-Fa-f0-9]{32,})")

    def __init__(self, alias="robot", event_types=None, fields=None):
        self.alias = alias or "robot"
        self.event_types = set(event_types or self.DEFAULT_EVENT_TYPES)
        self.fields = set(fields or self.DEFAULT_FIELDS)

    def _redact(self, value):
        text = str(value or "")
        text = self.IP.sub("<ip>", text)
        text = self.PATH.sub("<path>", text)
        text = self.TOKEN.sub("<redacted>", text)
        return text[:65536]

    def apply(self, event: dict) -> dict | None:
        if event.get("event_type") not in self.event_types:
            return None
        result = dict(event)
        result["device_id"] = self.alias
        result["session_id"] = ""
        result["boot_id"] = ""
        result["device_model"] = ""
        result["message"] = self._redact(result.get("message", ""))
        fields = {key: self._redact(value) for key, value in (result.get("fields") or {}).items()
                  if key in self.fields}
        result["fields"] = fields
        return result


class LogSpool:
    """Bounded, durable queue of serialized log events."""

    def __init__(self, path: str, max_events: int = 10000, max_attempts: int = 20):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.max_events = max(1, int(max_events))
        self.max_attempts = max(1, int(max_attempts))
        self.dropped = 0
        self.rejected = 0
        self.dead_letter_dropped = 0
        self._warned: dict[str, float] = {}
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("""CREATE TABLE IF NOT EXISTS spool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL)""")
            self._db.execute("CREATE INDEX IF NOT EXISTS spool_id ON spool(id)")
            self._db.execute("""CREATE TABLE IF NOT EXISTS dead_letter (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                failed_at TEXT NOT NULL,
                reason TEXT NOT NULL)""")
            self._db.execute("CREATE INDEX IF NOT EXISTS dead_letter_id ON dead_letter(id)")

    def add(self, event: dict) -> None:
        payload = json.dumps(event, ensure_ascii=False, allow_nan=False)
        with self._lock, self._db:
            self._db.execute("INSERT INTO spool(payload, created_at) VALUES (?, ?)",
                             (payload, _now()))
            count = self._db.execute("SELECT COUNT(*) FROM spool").fetchone()[0]
            if count > self.max_events:
                excess = count - self.max_events
                self._db.execute(
                    "DELETE FROM spool WHERE id IN (SELECT id FROM spool ORDER BY id LIMIT ?)",
                    (excess,))
                self.dropped += excess
        if count > self.max_events:
            self._warn("overflow", f"dropped {excess} oldest event(s) at capacity {self.max_events}")

    def peek(self, limit: int) -> list[tuple[int, str]]:
        with self._lock:
            return self._db.execute(
                "SELECT id, payload FROM spool ORDER BY id LIMIT ?", (limit,)).fetchall()

    def size(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM spool").fetchone()[0]

    def ack(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._lock, self._db:
            self._db.execute(f"DELETE FROM spool WHERE id IN ({placeholders})", ids)

    def fail(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._lock, self._db:
            self._db.execute(
                f"UPDATE spool SET attempts = attempts + 1 WHERE id IN ({placeholders})", ids)
            rows = self._db.execute(
                "SELECT id, payload, attempts, created_at FROM spool WHERE attempts >= ?",
                (self.max_attempts,)).fetchall()
            self._to_dead_letter(rows, "max_attempts")
        if rows:
            self._warn(
                "max_attempts",
                f"moved {len(rows)} event(s) to dead letter after {self.max_attempts} attempts",
            )

    def reject(self, ids: list[int], reason: str) -> None:
        """Isolate events the server will never accept, without blocking the queue."""
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._lock, self._db:
            rows = self._db.execute(
                f"SELECT id, payload, attempts, created_at FROM spool "
                f"WHERE id IN ({placeholders})", ids).fetchall()
            self._to_dead_letter(rows, reason)
        if rows:
            self._warn(reason, f"moved {len(rows)} event(s) to dead letter ({reason})")

    def status(self) -> dict:
        with self._lock:
            spooled = self._db.execute("SELECT COUNT(*) FROM spool").fetchone()[0]
            dead = self._db.execute("SELECT COUNT(*) FROM dead_letter").fetchone()[0]
        return {
            "spooled": spooled,
            "dead_letter": dead,
            "dropped": self.dropped,
            "rejected": self.rejected,
            "dead_letter_dropped": self.dead_letter_dropped,
            "max_events": self.max_events,
            "max_attempts": self.max_attempts,
        }

    def _to_dead_letter(self, rows, reason: str) -> None:
        failed_at = _now()
        for row in rows:
            self._db.execute(
                "INSERT INTO dead_letter(payload, attempts, created_at, failed_at, reason) "
                "VALUES (?, ?, ?, ?, ?)",
                (row[1], row[2], row[3], failed_at, reason),
            )
            self._db.execute("DELETE FROM spool WHERE id = ?", (row[0],))
        self.rejected += len(rows)
        self._enforce_dead_limit()

    def _enforce_dead_limit(self) -> None:
        count = self._db.execute("SELECT COUNT(*) FROM dead_letter").fetchone()[0]
        if count > self.max_events:
            excess = count - self.max_events
            self._db.execute(
                "DELETE FROM dead_letter WHERE id IN "
                "(SELECT id FROM dead_letter ORDER BY id LIMIT ?)", (excess,))
            self.dead_letter_dropped += excess

    def _warn(self, key: str, message: str) -> None:
        now = time.monotonic()
        if now - self._warned.get(key, 0.0) < 60.0:
            return
        self._warned[key] = now
        print(f"rp_server log spool: {message}", file=sys.stderr, flush=True)

    def close(self) -> None:
        with self._lock:
            self._db.close()


class LogUploadHandler(logging.Handler):
    def __init__(self, device_id: str, service: str = "rp_server",
                 url: str = DEFAULT_URL, token: str = "", session_id: str = "",
                 spool_path: str = "logs/log-spool.sqlite3",
                 spool_max_events: int = 10000, max_attempts: int = 20,
                 batch_size: int = 50, flush_interval: float = 2.0,
                 timeout: float = 5.0, level: int = logging.INFO,
                 software_version: str = RP_SERVER_VERSION,
                 policy: PublicLogPolicy | None = None,
                 firmware_version: str = "", device_model: str = ""):
        super().__init__(level)
        self.device_id = _text(device_id or socket.gethostname(), 256) or "unknown"
        self.service = _text(service or "rp_server", 256) or "rp_server"
        self.url = url.rstrip("/")
        self.token = token
        self.session_id = session_id or uuid.uuid4().hex
        self.boot_id = _boot_id() or self.session_id
        self.software_version = _text(software_version, 256)
        self.firmware_version = _text(firmware_version, 256)
        self.device_model = _text(device_model, 256)
        self.batch_size = max(1, int(batch_size))
        self.flush_interval = max(0.1, float(flush_interval))
        self.timeout = max(0.1, float(timeout))
        self.policy = policy
        self._spool = LogSpool(spool_path, spool_max_events, max_attempts)
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name="rp-log-upload", daemon=True)
        self._thread.start()

    @property
    def dropped(self) -> int:
        return self._spool.dropped

    def status(self) -> dict:
        return self._spool.status()

    def emit(self, record: logging.LogRecord):
        try:
            event = self._event(record)
            if self.policy is not None:
                event = self.policy.apply(event)
                if event is None:
                    return
            self._spool.add(event)
            self._wake.set()
        except Exception:
            self._spool.dropped += 1
            self.handleError(record)

    def _event(self, record: logging.LogRecord) -> dict:
        level = record.levelname if record.levelname in LEVELS else "INFO"
        fields = {
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.levelname not in LEVELS:
            fields["level_name"] = record.levelname
        if record.exc_info:
            fields["exception"] = "".join(traceback.format_exception(*record.exc_info))
        return {
            "event_id": uuid.uuid4().hex,
            "device_id": self.device_id,
            "service": self.service,
            "schema_version": "1",
            "event_type": _text(getattr(record, "event_type", ""), 256),
            "session_id": self.session_id,
            "inference_session_id": _text(getattr(record, "inference_session_id", ""), 256),
            "phase": _text(getattr(record, "phase", ""), 256),
            "boot_id": self.boot_id,
            "software_version": self.software_version,
            "firmware_version": self.firmware_version,
            "device_model": self.device_model,
            "timestamp": _record_time(record),
            "level": level,
            "message": _text(record.getMessage(), 65536),
            "fields": fields,
        }

    def _post(self, events: list[dict]) -> None:
        data = json.dumps({"logs": events}, ensure_ascii=False, allow_nan=False).encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(self.url + "/v1/logs", data=data, headers=headers, method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            response.read()

    def _run(self) -> None:
        try:
            self._run_loop()
        except Exception:
            print("rp_server log uploader stopped:\n" + traceback.format_exc(), file=sys.stderr)

    def _run_loop(self) -> None:
        while True:
            rows = self._spool.peek(self.batch_size)
            if rows:
                ids = [row[0] for row in rows]
                try:
                    events = [json.loads(row[1]) for row in rows]
                    self._post(events)
                    self._spool.ack(ids)
                    continue
                except HTTPError as exc:
                    if 400 <= exc.code < 500 and exc.code not in (408, 429):
                        self._spool.reject(ids, f"http_{exc.code}")
                    else:
                        self._spool.fail(ids)
                except (URLError, TimeoutError, OSError, ValueError):
                    self._spool.fail(ids)
                if self._stopped.is_set():
                    return
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            if self._stopped.is_set():
                return
            self._wake.wait(timeout=min(1.0, self.flush_interval))
            self._wake.clear()

    def close(self) -> None:
        if self._stopped.is_set():
            return
        self._stopped.set()
        self._wake.set()
        self._thread.join(timeout=self.timeout + 2.0)
        self._spool.close()
        super().close()


def attach_log_server(config: dict, logger_name: str = "rp_server") -> LogUploadHandler | None:
    cfg = config.get("log_server", {}) or {}
    if not (cfg.get("enabled") or os.environ.get("RP_LOG_SERVER_URL")):
        return None
    logger = logging.getLogger(logger_name)
    for handler in logger.handlers:
        if isinstance(handler, LogUploadHandler):
            return handler

    url = os.environ.get("RP_LOG_SERVER_URL") or cfg.get("url", DEFAULT_URL)
    token = os.environ.get("RP_LOG_TOKEN", cfg.get("token", ""))
    device_id = (os.environ.get("RP_LOG_DEVICE_ID") or cfg.get("device_id")
                 or socket.gethostname())
    device_model = os.environ.get("RP_DEVICE_MODEL", cfg.get("device_model", ""))
    firmware_version = os.environ.get("RP_FIRMWARE_VERSION", cfg.get("firmware_version", ""))
    spool_path = cfg.get("spool_path") or os.path.join(
        config.get("logging", {}).get("dir", "logs"), "log-spool.sqlite3")
    level_name = str(cfg.get("level", "INFO")).upper()
    policy = None
    if cfg.get("public"):
        if not cfg.get("public_consent"):
            logger.warning("public log upload disabled: public_consent is false",
                           extra={"event_type": "log"})
            return None
        policy = PublicLogPolicy(
            alias=cfg.get("public_alias", "robot"),
            event_types=cfg.get("public_event_types"),
            fields=cfg.get("public_fields"),
        )
    try:
        handler = LogUploadHandler(
            device_id=device_id,
            service=cfg.get("service", "rp_server"),
            url=url,
            token=token,
            spool_path=spool_path,
            spool_max_events=cfg.get("spool_max_events", 10000),
            max_attempts=cfg.get("max_attempts", 20),
            batch_size=cfg.get("batch_size", 50),
            flush_interval=cfg.get("flush_interval_s", 2.0),
            timeout=cfg.get("timeout_s", 5.0),
            level=getattr(logging, level_name, logging.INFO),
            firmware_version=firmware_version,
            device_model=device_model,
            policy=policy,
        )
    except Exception as exc:
        logger.warning("log server upload disabled: %s", exc, extra={"event_type": "log"})
        return None
    logger.addHandler(handler)
    logger.info("log server upload enabled: %s (spool %s)", url, spool_path,
                extra={"event_type": "log"})
    return handler
