# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Spool retention, acknowledgement and dead-letter isolation."""

from pathlib import Path
import tempfile
import unittest

from rp_server.log_upload import LogSpool


class SpoolTests(unittest.TestCase):
    def make(self, **kwargs):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return LogSpool(str(Path(temp.name) / "spool.sqlite3"), **kwargs)

    def test_ack_deletes_only_acked_events(self):
        spool = self.make()
        spool.add({"index": 1})
        spool.add({"index": 2})
        first = spool.peek(10)[0][0]
        spool.ack([first])
        self.assertEqual(1, spool.size())

    def test_capacity_drops_oldest_and_counts(self):
        spool = self.make(max_events=2)
        for index in range(4):
            spool.add({"index": index})
        status = spool.status()
        self.assertEqual(2, status["spooled"])
        self.assertEqual(2, status["dropped"])

    def test_fail_keeps_events_until_attempt_limit(self):
        spool = self.make(max_events=10, max_attempts=2)
        spool.add({"index": 1})
        ids = [row[0] for row in spool.peek(10)]
        spool.fail(ids)
        self.assertEqual(1, spool.size())
        self.assertEqual(0, spool.status()["rejected"])
        spool.fail(ids)
        status = spool.status()
        self.assertEqual(0, status["spooled"])
        self.assertEqual(1, status["rejected"])
        self.assertEqual(1, status["dead_letter"])

    def test_reject_isolates_without_blocking_queue(self):
        spool = self.make()
        spool.add({"index": 1})
        spool.add({"index": 2})
        first = spool.peek(10)[0][0]
        spool.reject([first], "http_400")
        status = spool.status()
        self.assertEqual(1, status["spooled"])
        self.assertEqual(1, status["rejected"])
        self.assertEqual(1, status["dead_letter"])


if __name__ == "__main__":
    unittest.main()
