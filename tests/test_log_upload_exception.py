# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Exception records must keep their traceback in the upload event."""

import logging
from pathlib import Path
import sys
import tempfile
import unittest

from rp_server.log_upload import LogUploadHandler


class ExceptionFieldTests(unittest.TestCase):
    def test_exception_uses_traceback_format(self):
        with tempfile.TemporaryDirectory() as temp:
            handler = LogUploadHandler(
                "test-device",
                url="http://127.0.0.1:1",
                spool_path=str(Path(temp) / "spool.sqlite3"),
            )
            try:
                try:
                    raise ValueError("boom")
                except ValueError:
                    record = logging.LogRecord(
                        "rp_server", logging.ERROR, __file__, 1,
                        "upload failed", (), sys.exc_info(),
                    )
                event = handler._event(record)
            finally:
                handler.close()
        self.assertIn("ValueError: boom", event["fields"]["exception"])


if __name__ == "__main__":
    unittest.main()
