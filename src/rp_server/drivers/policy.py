# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""subprocess → ros2 launch inference_node"""

import asyncio
import logging
import os
import subprocess

logger = logging.getLogger("rp_server.policy")


class PolicyDriver:
    """Manage ros2 inference_node as a subprocess."""

    def __init__(self, launch_cmd: str = "ros2 launch roboparty-inference inference.launch.py"):
        self._launch_cmd = launch_cmd
        self._proc: subprocess.Popen | None = None
        self._name = ""
        self._monitor_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, name: str = "default") -> bool:
        if self._proc is not None:
            return False
        try:
            self._proc = subprocess.Popen(
                self._launch_cmd, shell=True, env=os.environ.copy(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._name = name
            logger.info("policy started: %s (pid %d)", name, self._proc.pid)
            return True
        except Exception as exc:
            logger.error("policy start failed: %s", exc)
            return False

    async def stop(self):
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        except Exception as exc:
            logger.warning("policy stop error: %s", exc)
        self._proc = None
        self._name = ""

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def name(self) -> str:
        return self._name
