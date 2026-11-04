# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""subprocess → ros2 launch inference_node"""

import asyncio
import logging
import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("rp_server.policy")

# ROS 2 package names use underscores. {policy} is replaced with the validated
# PolicyCommand.name before launching.
DEFAULT_LAUNCH_CMD = "ros2 launch roboparty_inference inference.launch.py robot:=rpo policy:={policy}"
_POLICY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class PolicyDriver:
    """Manage ros2 inference_node as a subprocess.

    ``start`` only reports success after the optional readiness callback
    succeeds.  ``stop`` only reports success after the whole process group has
    exited.  A process that exits without an explicit stop is reported as
    ``FAIL`` instead of silently looking like a normal stop.
    """

    def __init__(self, launch_cmd: str = DEFAULT_LAUNCH_CMD, ready_check=None,
                 ready_timeout_s: float = 15.0, lock_path: str | None = None,
                 log_path: str | None = None):
        self._launch_cmd = launch_cmd
        self._log_path = log_path
        self._log_file = None
        self._proc: subprocess.Popen | None = None
        self._name = ""
        self._ready_check = ready_check
        self._ready_timeout_s = ready_timeout_s
        self._lock_path = lock_path
        self._stop_requested = False
        self._starting = False
        self._stopping = False
        self._failed = False
        self._exit_code: int | None = None
        self._message = ""
        self._updated_at_ms = int(time.time() * 1000)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, name: str = "default") -> bool:
        if self._proc is not None:
            if self._proc.poll() is None:
                return False
            try:
                self._proc.wait()
            except Exception:
                pass
        self._close_log()
        self._proc = None
        self._failed = False
        self._exit_code = None
        self._stop_requested = False
        self._starting = True
        self._stopping = False
        self._message = "starting"
        self._updated_at_ms = int(time.time() * 1000)

        policy = name or "default"
        if not _POLICY_NAME.fullmatch(policy):
            logger.error("invalid policy name: %r", name, extra={"event_type": "policy"})
            return False
        command = self._launch_cmd
        if "{policy}" in command:
            command = command.replace("{policy}", policy)
        elif re.search(r"policy:=\S+", command):
            command = re.sub(r"policy:=\S+", f"policy:={policy}", command)
        if self._lock_path:
            command = "flock -n {} bash -c {}".format(
                shlex.quote(self._lock_path), shlex.quote(command))
        if self._log_path:
            Path(self._log_path).parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(self._log_path, "ab", buffering=0)
            logger.info("policy log: %s", self._log_path, extra={"event_type": "policy"})
        try:
            self._proc = subprocess.Popen(
                command, shell=True, env=os.environ.copy(),
                stdout=self._log_file or subprocess.DEVNULL,
                stderr=subprocess.STDOUT if self._log_file else subprocess.DEVNULL,
                # Put the shell and all ros2-launched children in one process
                # group so stop() can terminate the whole tree.
                start_new_session=True,
            )
            self._name = policy
            logger.info("policy started: %s (pid %d)", policy, self._proc.pid,
                        extra={"event_type": "policy"})
        except Exception as exc:
            self._close_log()
            self._starting = False
            logger.error("policy start failed: %s", exc, extra={"event_type": "policy"})
            return False

        if self._lock_path:
            await asyncio.sleep(0.2)
            if self._proc is None or self._proc.poll() is not None:
                logger.error("policy failed to acquire control lock: %s", self._lock_path,
                             extra={"event_type": "policy"})
                self._proc = None
                self._name = ""
                self._starting = False
                self._failed = True
                self._message = "control lock busy"
                self._updated_at_ms = int(time.time() * 1000)
                return False

        if self._ready_check is not None and not await self._wait_ready():
            logger.error("policy readiness failed: %s", policy, extra={"event_type": "policy"})
            await self._terminate()
            self._proc = None
            self._name = ""
            self._starting = False
            self._failed = True
            self._message = "readiness probe failed"
            self._updated_at_ms = int(time.time() * 1000)
            return False
        self._starting = False
        self._message = "ready"
        self._updated_at_ms = int(time.time() * 1000)
        return True

    async def _wait_ready(self) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._ready_timeout_s
        while loop.time() < deadline:
            if self._proc is None or self._proc.poll() is not None:
                self._exit_code = self._proc.returncode if self._proc else None
                return False
            try:
                if await self._ready_check():
                    return True
            except Exception as exc:
                logger.warning("policy readiness probe failed: %s", exc, extra={"event_type": "policy"})
            await asyncio.sleep(0.2)
        return False

    async def stop(self) -> bool:
        proc = self._proc
        if proc is None:
            return True
        self._stop_requested = True
        self._stopping = True
        if proc.poll() is None:
            try:
                self._signal_group(proc, signal.SIGTERM)
                try:
                    await asyncio.to_thread(proc.wait, 5)
                except subprocess.TimeoutExpired:
                    logger.warning("policy did not exit in 5s, sending SIGKILL", extra={"event_type": "policy"})
                    self._signal_group(proc, signal.SIGKILL)
                    await asyncio.to_thread(proc.wait)
            except Exception as exc:
                logger.warning("policy stop error: %s", exc, extra={"event_type": "policy"})
                self._stop_requested = False
                self._failed = True
                self._stopping = False
                self._message = f"stop failed: {exc}"
                self._updated_at_ms = int(time.time() * 1000)
                return False
        self._exit_code = proc.returncode
        self._proc = None
        self._name = ""
        self._stopping = False
        self._message = "stopped"
        self._updated_at_ms = int(time.time() * 1000)
        self._close_log()
        return True

    async def _terminate(self) -> bool:
        proc = self._proc
        if proc is None:
            return True
        try:
            if proc.poll() is None:
                self._signal_group(proc, signal.SIGTERM)
                try:
                    await asyncio.to_thread(proc.wait, 5)
                except subprocess.TimeoutExpired:
                    self._signal_group(proc, signal.SIGKILL)
                    await asyncio.to_thread(proc.wait)
            self._exit_code = proc.returncode
            self._close_log()
            return True
        except Exception as exc:
            logger.warning("policy terminate error: %s", exc, extra={"event_type": "policy"})
            return False

    def _close_log(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None

    @staticmethod
    def _signal_group(proc: subprocess.Popen, sig: int) -> None:
        """Signal the whole process group, falling back to the shell only."""
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.send_signal(sig)
            except (ProcessLookupError, OSError):
                pass

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def failed(self) -> bool:
        if self._proc is not None and self._proc.poll() is not None and not self._stop_requested:
            return True
        return self._failed

    @property
    def state(self) -> str:
        if self._starting:
            return "STARTING"
        if self._stopping:
            return "STOPPING"
        if self._proc is not None and self._proc.poll() is None:
            return "RUNNING"
        if self._failed or (self._proc is not None and not self._stop_requested):
            if self._proc is not None and self._proc.poll() is not None:
                self._exit_code = self._proc.returncode
                self._message = f"exited unexpectedly (code {self._proc.returncode})"
                self._updated_at_ms = int(time.time() * 1000)
            return "FAIL"
        return "STOPPED"

    @property
    def name(self) -> str:
        return self._name

    @property
    def pid(self) -> int:
        return self._proc.pid if self._proc is not None else 0

    @property
    def exit_code(self) -> int:
        return self._exit_code if self._exit_code is not None else -1

    @property
    def message(self) -> str:
        return self._message

    @property
    def updated_at_ms(self) -> int:
        return self._updated_at_ms
