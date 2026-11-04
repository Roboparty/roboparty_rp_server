# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

import asyncio
from pathlib import Path
import tempfile
import unittest

from rp_server.drivers.policy import PolicyDriver


class PolicyLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_subprocess_output_is_captured(self):
        root = Path(__file__).resolve().parents[2] / "test/tmp"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="policy-log-test-", dir=root) as tmp:
            log_path = Path(tmp) / "policy.log"
            phases = []
            driver = PolicyDriver("echo policy-output; sleep 0.5", log_path=str(log_path),
                                  lifecycle_cb=lambda phase, *_: phases.append(phase))
            self.assertTrue(await driver.start("default"))
            await asyncio.sleep(0.2)
            await driver.stop()
            self.assertIn("policy-output", log_path.read_text())
            self.assertEqual(phases, ["starting", "running", "stopping", "stopped"])

    async def test_unexpected_exit_emits_failed(self):
        root = Path(__file__).resolve().parents[2] / "test/tmp"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="policy-crash-test-", dir=root) as tmp:
            phases = []
            details = {}
            def cb(phase, session_id, policy, extra):
                phases.append(phase)
                details[phase] = extra
            driver = PolicyDriver("sleep 0.1", lifecycle_cb=cb)
            self.assertTrue(await driver.start("walk"))
            await asyncio.sleep(0.5)
            self.assertIn("failed", phases)
            self.assertEqual(details["failed"]["reason"], "exited")
            await driver.stop()


if __name__ == "__main__":
    unittest.main()


class PolicyLockCommandTests(unittest.TestCase):
    def test_lock_wrapper_sets_nested_lock_marker(self):
        from rp_server.drivers.policy import PolicyDriver
        command = PolicyDriver._locked_command(
            "/dev/shm/roboparty-control.lock", "ros2 launch demo")
        self.assertIn("flock -n", command)
        self.assertIn("ROBOPARTY_CONTROL_LOCK_HELD=1", command)
        self.assertIn("ros2 launch demo", command)
