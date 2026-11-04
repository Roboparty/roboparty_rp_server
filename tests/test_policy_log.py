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
            driver = PolicyDriver("echo policy-output", log_path=str(log_path))
            self.assertTrue(await driver.start("default"))
            await asyncio.sleep(0.2)
            await driver.stop()
            self.assertIn("policy-output", log_path.read_text())


if __name__ == "__main__":
    unittest.main()
