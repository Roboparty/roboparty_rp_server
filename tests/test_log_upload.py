# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from rp_server.log_upload import LogUploadHandler, attach_log_server


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.server.requests.append((self.path, dict(self.headers), body))
        data = b'{"accepted": 1, "duplicates": 0}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


class LogUploadTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / "test/tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="log-upload-test-", dir=root)
        self.spool = str(Path(self.tmp.name) / "spool.sqlite3")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.requests = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.logger = logging.getLogger("rp_server.test_upload")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            handler.close()
        self.tmp.cleanup()

    def test_batches_and_flushes_on_close(self):
        handler = LogUploadHandler(
            device_id="robot-a", service="rp_server", url=self.url, token="secret",
            session_id="boot-1", spool_path=self.spool,
            batch_size=10, flush_interval=0.1, timeout=0.5, max_attempts=1)
        self.logger.addHandler(handler)
        self.logger.info("server ready port=%s", 9000, extra={"event_type": "startup"})
        handler.close()

        self.assertEqual(len(self.server.requests), 1)
        path, headers, body = self.server.requests[0]
        self.assertEqual(path, "/v1/logs")
        self.assertEqual(headers.get("Authorization"), "Bearer secret")
        event = body["logs"][0]
        self.assertEqual(event["device_id"], "robot-a")
        self.assertEqual(event["service"], "rp_server")
        self.assertEqual(event["session_id"], "boot-1")
        self.assertEqual(event["event_type"], "startup")
        self.assertEqual(event["schema_version"], "1")
        self.assertEqual(event["level"], "INFO")
        self.assertEqual(event["message"], "server ready port=9000")
        self.assertEqual(event["fields"]["logger"], "rp_server.test_upload")
        self.assertIn("+00:00", event["timestamp"])

    def test_spool_survives_restart(self):
        offline = LogUploadHandler(
            device_id="robot-a", spool_path=self.spool, url="http://127.0.0.1:1",
            timeout=0.2, max_attempts=5, batch_size=10, flush_interval=0.1)
        self.logger.addHandler(offline)
        self.logger.info("queued while offline")
        offline.close()
        self.logger.removeHandler(offline)

        with sqlite3.connect(self.spool) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM spool").fetchone()[0], 1)

        online = LogUploadHandler(
            device_id="robot-a", spool_path=self.spool, url=self.url,
            timeout=0.5, max_attempts=1, batch_size=10, flush_interval=0.1)
        self.logger.addHandler(online)
        online.close()
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.server.requests[0][2]["logs"][0]["message"],
                         "queued while offline")

    def test_disabled_config_returns_none(self):
        self.assertIsNone(attach_log_server({"log_server": {"enabled": False}}))


if __name__ == "__main__":
    unittest.main()


class PublicLogPolicyTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / "test/tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="public-policy-test-", dir=root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_redacts_identity_and_sensitive_text(self):
        from rp_server.log_upload import PublicLogPolicy
        policy = PublicLogPolicy(alias="anonymous")
        event = {
            "event_id": "e1", "device_id": "SN-123", "service": "rp_server",
            "schema_version": "1", "event_type": "lease", "session_id": "s1",
            "inference_session_id": "inf-1", "phase": "running", "boot_id": "b1",
            "software_version": "1.4.0", "firmware_version": "1.0",
            "device_model": "rp1", "timestamp": "2026-11-04T00:00:00+00:00",
            "level": "INFO", "message": "client 192.168.1.5 /etc/rp-server/auth/key token=abcdef0123456789abcdef0123456789",
            "fields": {"logger": "rp_server.control", "module": "control",
                       "function": "acquire", "line": 1, "secret": "nope"},
        }
        result = policy.apply(event)
        self.assertIsNotNone(result)
        self.assertEqual(result["device_id"], "anonymous")
        self.assertEqual(result["session_id"], "")
        self.assertEqual(result["boot_id"], "")
        self.assertEqual(result["device_model"], "")
        self.assertIn("<ip>", result["message"])
        self.assertIn("<path>", result["message"])
        self.assertIn("<redacted>", result["message"])
        self.assertNotIn("secret", result["fields"])
        self.assertEqual(result["inference_session_id"], "inf-1")

    def test_non_allowlisted_event_is_dropped(self):
        from rp_server.log_upload import PublicLogPolicy
        policy = PublicLogPolicy()
        event = {"event_type": "auth", "message": "x", "fields": {}}
        self.assertIsNone(policy.apply(event))

    def test_public_requires_consent(self):
        self.assertIsNone(attach_log_server({
            "logging": {"dir": self.tmp.name},
            "log_server": {"enabled": True, "public": True, "public_consent": False},
        }))
