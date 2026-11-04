# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from rp_server.monitors.segment import SegmentRecorder
from rp_server.protocol.codec import Envelope


def imu_envelope(value=1.0):
    env = Envelope()
    env.header.timestamp_ms = 1
    env.imu.w = value
    return env


class SegmentRecorderTests(unittest.TestCase):
    def test_segment_contains_pre_run_post_and_events(self):
        root = Path(__file__).resolve().parents[2] / "test/tmp"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="segment-test-", dir=root) as tmp:
            recorder = SegmentRecorder(tmp, pre_window_s=5, post_window_s=5,
                                       buffer_s=10)
            recorder.record(imu_envelope(0.5))
            recorder.on_lifecycle("starting", "sess-1", "walk", {"policy": "walk"})
            recorder.record(imu_envelope(0.7))
            recorder.on_lifecycle("running", "sess-1", "walk", {})
            recorder.on_lifecycle("stopping", "sess-1", "walk", {})
            recorder.on_lifecycle("stopped", "sess-1", "walk",
                                  {"exit_code": 0, "duration_s": 1.2})
            recorder.record(imu_envelope(0.9))
            recorder.close()

            directory = Path(tmp) / "sess-1"
            telemetry = [json.loads(line) for line in
                         (directory / "telemetry.jsonl").read_text().splitlines()]
            events = [json.loads(line) for line in
                      (directory / "events.jsonl").read_text().splitlines()]
            meta = json.loads((directory / "meta.json").read_text())

            self.assertGreaterEqual(len(telemetry), 3)
            self.assertEqual(telemetry[0]["inference_session_id"], "sess-1")
            self.assertEqual([event["phase"] for event in events],
                             ["starting", "running", "stopping", "stopped"])
            self.assertEqual(meta["inference_session_id"], "sess-1")
            self.assertEqual(meta["phase"], "stopped")
            self.assertEqual(meta["stop"]["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()


class SegmentPolicyIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_lifecycle_creates_segment(self):
        from rp_server.drivers.policy import PolicyDriver
        root = Path(__file__).resolve().parents[2] / "test/tmp"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="segment-policy-test-", dir=root) as tmp:
            recorder = SegmentRecorder(tmp)
            driver = PolicyDriver("echo policy-output",
                                  lifecycle_cb=recorder.on_lifecycle)
            try:
                self.assertTrue(await driver.start("walk"))
                await asyncio.sleep(0.2)
                await driver.stop()
            finally:
                recorder.close()
            directory = Path(tmp) / driver.session_id
            meta = json.loads((directory / "meta.json").read_text())
            self.assertEqual(meta["policy"], "walk")
            self.assertEqual(meta["phase"], "stopped")
            self.assertEqual(meta["stop"]["exit_code"], 0)
