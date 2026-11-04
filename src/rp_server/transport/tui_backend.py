# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""robopi-tui JSON-RPC backend adapter.

rp_server delegates board-management operations (snapshot, package checks,
HPM flashing, CAN checks) to robopi-tui's public protocol::

    robopi-tui rpc --protocol 1   # one JSON-RPC 2.0 request per invocation

Only board *management* is delegated — motion/joystick/telemetry remain in
rp_server. Job submission is disabled unless ``tui.allow_jobs`` is true
(apt upgrade / HPM flash are destructive).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("rp_server.tui")

DEFAULT_TIMEOUT = 120.0
CANDIDATES = (
    "/opt/roboparty/bin/robopi-tui",
    "/usr/bin/robopi-tui",
    "/usr/lib/robopi-tui/robopi-tui",
)


class TuiError(RuntimeError):
    def __init__(self, code: str, message: str, data: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.data = data or {}


class TuiBackend:
    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.allow_jobs = bool(cfg.get("allow_jobs", False))
        self.timeout = float(cfg.get("timeout_s", DEFAULT_TIMEOUT))
        self.executable = self._resolve(cfg.get("executable", ""))
        # Reported to robopi-tui as RP_TUI_SERVER so backend results say
        # which fronting server produced them.
        self.server = str(cfg.get("server", "rp_server") or "")

    @staticmethod
    def _resolve(explicit: str) -> str:
        if explicit:
            path = Path(explicit)
            return str(path) if path.is_file() else ""
        env = os.environ.get("RP_TUI_BIN", "")
        if env and Path(env).is_file():
            return env
        found = shutil.which("robopi-tui")
        if found:
            return found
        for candidate in CANDIDATES:
            if Path(candidate).is_file():
                return candidate
        return ""

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def _run(self, method: str, params: Optional[dict], timeout: Optional[float] = None):
        if not self.available:
            raise TuiError("UNAVAILABLE", "robopi-tui executable not found")
        request = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": method,
            "params": params or {},
        }
        env = os.environ.copy()
        if self.server:
            env["RP_TUI_SERVER"] = self.server
        try:
            proc = subprocess.run(
                [self.executable, "rpc", "--protocol", "1"],
                input=json.dumps(request, ensure_ascii=False) + "\n",
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise TuiError("TIMEOUT", f"robopi-tui {method} timed out") from exc
        lines = (proc.stdout or "").strip().splitlines()
        if not lines:
            detail = (proc.stderr or "empty response").strip()[-2000:]
            raise TuiError("BAD_RESPONSE", detail)
        try:
            response = json.loads(lines[-1])
        except ValueError as exc:
            raise TuiError("BAD_RESPONSE", lines[-1][:2000]) from exc
        if "error" in response:
            err = response.get("error") or {}
            data = err.get("data") or {}
            code = data.get("code") or str(err.get("code", "TUI_ERROR"))
            raise TuiError(code, str(err.get("message", "")), data)
        return response.get("result")

    async def request(self, method: str, params: Optional[dict] = None,
                      timeout: Optional[float] = None):
        return await asyncio.to_thread(self._run, method, params, timeout)

    # -- read-only ------------------------------------------------------
    async def tasks(self):
        return await self.request("tasks.list")

    async def identity(self):
        data = await self.request("tasks.list")
        return (data or {}).get("identity", {}) or {}

    async def describe(self, task_id: str):
        return await self.request("tasks.describe", {"taskId": task_id})

    async def snapshot(self):
        return await self.request("snapshot.get")

    async def motor_errors(self):
        """Read-only motor error/state snapshot (TUI never enables or sends)."""
        return await self.request("motors.get", {})

    async def job(self, job_id: str):
        return await self.request("jobs.get", {"jobId": job_id})

    async def jobs(self, limit: int = 20):
        return await self.request("jobs.list", {"limit": limit})

    async def active_job(self):
        return await self.request("jobs.active")

    # -- destructive ----------------------------------------------------
    async def start_job(self, task_id: str, request_id: Optional[str] = None):
        if not self.allow_jobs:
            raise TuiError("DISABLED", "job submission disabled (tui.allow_jobs=false)")
        return await self.request(
            "jobs.start",
            {"taskId": task_id, "requestId": request_id or str(uuid.uuid4())},
        )

    async def acknowledge(self, job_id: str):
        if not self.allow_jobs:
            raise TuiError("DISABLED", "job acknowledgement disabled (tui.allow_jobs=false)")
        return await self.request("jobs.acknowledge", {"jobId": job_id})
